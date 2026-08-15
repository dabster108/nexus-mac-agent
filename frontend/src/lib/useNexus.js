"use client";

/**
 * The client's whole connection to NEXUS: one WebSocket for events, and
 * polling for the panels.
 *
 * The WebSocket is the source of truth for anything happening *now* — events
 * arrive as the agent produces them, including the permission request that
 * blocks a run mid-flight. Panels poll instead, because workspace and memory
 * state change on human timescales and the backend already caches that view.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  WS_URL,
  acceptSuggestion,
  cancelTask,
  dismissObservation,
  dismissSuggestion,
  fetchContext,
  fetchHealth,
  fetchMemories,
  fetchObservations,
  fetchPending,
  fetchSuggestions,
  fetchTask,
  resolvePermission,
  sendMessage,
} from "./api";

const PANEL_POLL_MS = 6000;
const MAX_EVENTS = 200;

export function useNexus() {
  const [online, setOnline] = useState(null);
  const [context, setContext] = useState(null);
  const [memories, setMemories] = useState([]);
  const [events, setEvents] = useState([]);
  const [messages, setMessages] = useState([]);
  const [pending, setPending] = useState([]);
  const [observations, setObservations] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const activeTask = useRef(null);
  const socket = useRef(null);

  // --- panels ------------------------------------------------------------
  const refreshPanels = useCallback(async (signal) => {
    try {
      const [ctx, mem, obs, sug] = await Promise.all([
        fetchContext({ signal }),
        fetchMemories({ signal }),
        fetchObservations({ signal }),
        fetchSuggestions({ signal }),
      ]);
      setContext(ctx);
      setMemories(mem.memories ?? []);
      setObservations(obs.observations ?? []);
      setSuggestions(sug.suggestions ?? []);
      setOnline(true);
    } catch (err) {
      if (err?.name !== "AbortError") setOnline(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    // Deferred to a microtask so no state is set during the effect body
    // itself; both of these resolve well after this effect has returned.
    Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      fetchHealth({ signal: controller.signal })
        .then(() => setOnline(true))
        .catch(() => setOnline(false));
      refreshPanels(controller.signal);
    });
    const timer = setInterval(() => refreshPanels(), PANEL_POLL_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [refreshPanels]);

  // --- pending approvals -------------------------------------------------
  const refreshPending = useCallback(async () => {
    try {
      const body = await fetchPending();
      setPending(body.requests ?? []);
    } catch {
      /* the panel poll already reports connectivity */
    }
  }, []);

  // --- the event stream --------------------------------------------------
  useEffect(() => {
    let closed = false;
    let retry;

    const connect = () => {
      if (closed) return;
      let ws;
      try {
        ws = new WebSocket(WS_URL);
      } catch {
        retry = setTimeout(connect, 2000);
        return;
      }
      socket.current = ws;

      ws.onmessage = (raw) => {
        let event;
        try {
          event = JSON.parse(raw.data);
        } catch {
          return;
        }
        if (event.type === "connected") return;

        // Observations arrive on the same socket but are not task events:
        // they belong to the session, so they update their own panel and stay
        // out of the per-task timeline.
        if (event.type === "observation_created" && event.observation) {
          setObservations((current) => [
            event.observation,
            ...current.filter(
              (item) => item.observation_id !== event.observation.observation_id,
            ),
          ]);
          return;
        }
        if (event.type === "suggestion_created" && event.suggestion) {
          setSuggestions((current) => [
            event.suggestion,
            ...current.filter(
              (item) => item.suggestion_id !== event.suggestion.suggestion_id,
            ),
          ]);
          return;
        }
        if (
          ["suggestion_dismissed", "suggestion_expired"].includes(event.type) &&
          event.suggestion
        ) {
          setSuggestions((current) =>
            current.filter(
              (item) => item.suggestion_id !== event.suggestion.suggestion_id,
            ),
          );
          return;
        }
        if (event.type === "observation_dismissed" && event.observation) {
          setObservations((current) =>
            current.filter(
              (item) => item.observation_id !== event.observation.observation_id,
            ),
          );
          return;
        }

        setEvents((current) => [...current, event].slice(-MAX_EVENTS));

        // A permission request blocks the run, so ask immediately rather than
        // waiting for the next poll.
        if (event.type === "permission_required") refreshPending();

        if (event.task_id && event.task_id === activeTask.current) {
          if (event.type === "agent_message") {
            setMessages((current) => [
              ...current,
              { role: "nexus", text: event.message, taskId: event.task_id },
            ]);
          }
          if (["task_completed", "task_error", "task_cancelled"].includes(event.type)) {
            setBusy(false);
            activeTask.current = null;
            refreshPending();
            refreshPanels();
            if (event.type === "task_error") setError(event.message ?? "That failed.");
          }
        }
      };

      ws.onclose = () => {
        if (!closed) retry = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket.current?.close();
    };
  }, [refreshPanels, refreshPending]);

  // --- actions -----------------------------------------------------------
  const send = useCallback(async (text) => {
    const message = text.trim();
    if (!message) return;
    setError(null);
    setMessages((current) => [...current, { role: "user", text: message }]);
    setBusy(true);
    try {
      const { task_id: taskId } = await sendMessage(message);
      activeTask.current = taskId;

      // The stream carries the answer, but a task that finishes before the
      // socket delivers its last event would otherwise leave the UI busy.
      setTimeout(async () => {
        if (activeTask.current !== taskId) return;
        try {
          const task = await fetchTask(taskId);
          if (["completed", "error", "cancelled"].includes(task.status)) {
            if (task.response) {
              setMessages((current) =>
                current.some((m) => m.taskId === taskId)
                  ? current
                  : [...current, { role: "nexus", text: task.response, taskId }],
              );
            }
            setBusy(false);
            activeTask.current = null;
          }
        } catch {
          /* the stream is still the primary path */
        }
      }, 1500);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }, []);

  const decide = useCallback(
    async (requestId, decision) => {
      try {
        await resolvePermission(requestId, decision);
      } catch (err) {
        setError(err.message);
      } finally {
        refreshPending();
      }
    },
    [refreshPending],
  );

  const dismiss = useCallback(async (observationId) => {
    setObservations((current) =>
      current.filter((item) => item.observation_id !== observationId),
    );
    try {
      await dismissObservation(observationId);
    } catch {
      /* the panel poll restores it if the call really failed */
    }
  }, []);

  /**
   * Taking up a suggestion. Two separate things, in this order:
   * the suggestion's own prompt goes to /api/chat exactly as if it had been
   * typed, and the suggestion is marked accepted so it stops being offered.
   * Nothing here executes anything — the agent decides which tools to use,
   * and a CONFIRM tool still raises the ordinary approval prompt.
   */
  const acceptSuggestionById = useCallback(
    async (suggestion) => {
      const prompt = suggestion?.suggested_action?.prompt;
      if (!prompt) return;
      setSuggestions((current) =>
        current.filter((item) => item.suggestion_id !== suggestion.suggestion_id),
      );
      send(prompt);
      try {
        await acceptSuggestion(suggestion.suggestion_id);
      } catch {
        /* the message is already on its way; the record is cosmetic */
      }
    },
    [send],
  );

  const dismissSuggestionById = useCallback(async (suggestionId) => {
    setSuggestions((current) =>
      current.filter((item) => item.suggestion_id !== suggestionId),
    );
    try {
      await dismissSuggestion(suggestionId);
    } catch {
      /* the panel poll restores it if the call really failed */
    }
  }, []);

  const stop = useCallback(async () => {
    const taskId = activeTask.current;
    if (!taskId) return;
    try {
      await cancelTask(taskId);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  return {
    online,
    context,
    memories,
    events,
    messages,
    pending,
    observations,
    suggestions,
    busy,
    error,
    send,
    decide,
    dismiss,
    dismissSuggestion: dismissSuggestionById,
    acceptSuggestion: acceptSuggestionById,
    stop,
    refreshPanels,
  };
}
