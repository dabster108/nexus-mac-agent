"use client";

/**
 * The client's entire connection to NEXUS.
 *
 * The reconciliation rule, stated once and followed everywhere below:
 *
 *   REST      = authoritative state (on load, and again on every reconnect)
 *   WebSocket = incremental updates while connected
 *   Backend   = the source of truth, always
 *
 * The frontend therefore keeps no state the backend does not own, except for
 * the conversation transcript — which is a view of the session, not of the
 * server. Anything derived from events (mission progress, outcomes) is keyed
 * by task id so it can be attached to the turn that caused it rather than
 * floating in a global list.
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
  fetchMcpServers,
  fetchMemories,
  fetchObservations,
  fetchPending,
  fetchSuggestions,
  fetchTask,
  fetchTools,
  resolvePermission,
  sendMessage,
} from "./api";

/** Context has no event of its own, so it is the one thing still polled. */
const CONTEXT_POLL_MS = 15000;

/** Bounded so a long session cannot grow the tab's memory without limit. */
const MAX_EVENTS = 150;

const TERMINAL = ["completed", "error", "cancelled"];

/** Rebuild mission progress and outcomes from a task's event log. Used when
 *  the WebSocket dropped but the backend finished the run. */
function rebuildFromEvents(events, taskId) {
  let mission = null;
  const outcomes = [];

  for (const event of events ?? []) {
    const type = event.type;

    if (type === "mission_started") {
      mission = { taskId, objective: event.message ?? "", steps: [] };
    }
    if (type === "mission_plan_created" && mission) {
      mission = {
        ...mission,
        steps: (event.steps ?? []).map((step) => ({
          id: step.id,
          label: step.description ?? step.tool ?? "step",
          state: "pending",
        })),
      };
    }
    if (type === "mission_waiting_approval" && mission) {
      const stepId = event.step_id;
      mission = {
        ...mission,
        steps: mission.steps.map((s) =>
          s.id === stepId ? { ...s, state: "waiting" } : s,
        ),
      };
    }
    if (type?.startsWith("mission_step_")) {
      const state = {
        mission_step_started: "running",
        mission_step_completed: "done",
        mission_step_failed: "failed",
        mission_step_skipped: "skipped",
      }[type];
      if (state && mission) {
        const stepId = event.step_id;
        mission = {
          ...mission,
          steps: mission.steps.map((s) =>
            s.id === stepId ? { ...s, state } : s,
          ),
        };
      }
    }
    if (
      ["mission_completed", "mission_failed", "mission_cancelled"].includes(type) &&
      mission
    ) {
      mission = { ...mission, finished: true };
    }
    if (type === "verification_completed") {
      outcomes.push({
        tool: event.tool,
        outcome: event.outcome,
        summary: event.message,
        evidence: event.evidence ?? [],
        unknowns: event.unknowns ?? [],
      });
    }
  }

  return { mission, outcomes };
}

/** When a turn appeared in *this session* — a transcript detail, not backend
 *  state. The backend timestamps events; it does not timestamp the reply. */
const _now = () => new Date().toISOString();

export function useNexus() {
  const [online, setOnline] = useState(null);
  const [context, setContext] = useState(null);
  const [memories, setMemories] = useState([]);
  const [observations, setObservations] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [pending, setPending] = useState([]);
  const [messages, setMessages] = useState([]);
  const [events, setEvents] = useState([]);
  /** taskId -> verification[]; attached to the turn that produced them. */
  const [outcomes, setOutcomes] = useState({});
  /** taskId -> { objective, steps[] }; only while a mission is running. */
  const [mission, setMission] = useState(null);
  /** MCP server status from GET /api/mcp/servers — confirms Mac tools are reachable. */
  const [mcp, setMcp] = useState([]);
  /** Mac tools from GET /api/tools — what the agent can call. */
  const [tools, setTools] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  /** Has the authoritative REST read finished once? Until it has, the UI
   *  must not claim there is nothing to show — it does not know yet. */
  const [hydrated, setHydrated] = useState(false);

  const activeTask = useRef(null);
  const socket = useRef(null);

  // --- authoritative state ------------------------------------------------

  const loadAuthoritative = useCallback(async (signal) => {
    try {
      const [ctx, mem, obs, sug, perm, mcpBody, toolBody] = await Promise.all([
        fetchContext({ signal }),
        fetchMemories({ signal }),
        fetchObservations({ signal }),
        fetchSuggestions({ signal }),
        fetchPending({ signal }),
        fetchMcpServers({ signal }).catch(() => ({ servers: [] })),
        fetchTools({ signal }).catch(() => ({ tools: [] })),
      ]);
      setContext(ctx);
      setMemories(mem.memories ?? []);
      setObservations(obs.observations ?? []);
      setSuggestions(sug.suggestions ?? []);
      setPending(perm.requests ?? []);
      setMcp(mcpBody.servers ?? []);
      setTools(toolBody.tools ?? []);
      setOnline(true);
      setHydrated(true);
      return true;
    } catch (err) {
      if (err?.name !== "AbortError") {
        setOnline(false);
        // Hydrated means "we tried", not "we succeeded". A failed first read
        // still ends the loading state — it just ends it as offline.
        setHydrated(true);
      }
      return false;
    }
  }, []);

  const refreshContext = useCallback(async () => {
    try {
      setContext(await fetchContext());
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  const refreshMemories = useCallback(async () => {
    try {
      const body = await fetchMemories();
      setMemories(body.memories ?? []);
    } catch {
      /* connectivity is reported by the context poll */
    }
  }, []);

  const refreshPending = useCallback(async () => {
    try {
      const body = await fetchPending();
      setPending(body.requests ?? []);
    } catch {
      /* connectivity is reported by the context poll */
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    // Deferred to a microtask so no state is set during the effect body.
    Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      fetchHealth({ signal: controller.signal })
        .then(() => setOnline(true))
        .catch(() => setOnline(false));
      loadAuthoritative(controller.signal);
    });
    // Only context is polled: observations, suggestions and approvals all
    // arrive as events, so polling them would be asking for what we already
    // have. Context has no event, and changes when the user switches branch.
    const timer = setInterval(refreshContext, CONTEXT_POLL_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [loadAuthoritative, refreshContext]);

  // --- the event stream ----------------------------------------------------

  useEffect(() => {
    let closed = false;
    let retry;
    let everConnected = false;

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
      let ping;

      ws.onopen = () => {
        setOnline(true);
        // Anything that happened while disconnected was missed, so the
        // authoritative state is re-read rather than assumed still correct.
        if (everConnected) loadAuthoritative();
        everConnected = true;
        // Keep the connection warm through long approval waits.
        ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        }, 30000);
      };

      ws.onmessage = (raw) => {
        let event;
        try {
          event = JSON.parse(raw.data);
        } catch {
          return;
        }
        const type = event.type;
        if (type === "connected") return;

        // --- session-level events: their own panels, not the transcript ---
        if (type === "observation_created" && event.observation) {
          setObservations((current) => [
            event.observation,
            ...current.filter(
              (o) => o.observation_id !== event.observation.observation_id,
            ),
          ]);
          return;
        }
        if (type === "observation_dismissed" && event.observation) {
          setObservations((current) =>
            current.filter(
              (o) => o.observation_id !== event.observation.observation_id,
            ),
          );
          return;
        }
        if (type === "suggestion_created" && event.suggestion) {
          setSuggestions((current) => [
            event.suggestion,
            ...current.filter(
              (s) => s.suggestion_id !== event.suggestion.suggestion_id,
            ),
          ]);
          return;
        }
        if (
          ["suggestion_dismissed", "suggestion_expired"].includes(type) &&
          event.suggestion
        ) {
          setSuggestions((current) =>
            current.filter(
              (s) => s.suggestion_id !== event.suggestion.suggestion_id,
            ),
          );
          return;
        }

        setEvents((current) => [...current, event].slice(-MAX_EVENTS));

        if (type === "permission_required") refreshPending();

        // Memory changes go straight to the rail; no dedicated WS panel for them.
        if (["memory_saved", "memory_deleted", "memory_conflict"].includes(type)) {
          refreshMemories();
        }

        // --- everything below belongs to the task in flight ---------------
        if (!event.task_id || event.task_id !== activeTask.current) return;
        const taskId = event.task_id;

        if (type === "verification_completed") {
          setOutcomes((current) => ({
            ...current,
            [taskId]: [
              ...(current[taskId] ?? []),
              {
                tool: event.tool,
                outcome: event.outcome,
                summary: event.message,
                evidence: event.evidence ?? [],
                unknowns: event.unknowns ?? [],
              },
            ],
          }));
        }

        // Mission progress, derived from the lifecycle events the engine
        // already emits — the frontend adds no state the backend lacks.
        if (type === "mission_started") {
          setMission({ taskId, objective: event.message ?? "", steps: [] });
        }
        if (type === "mission_plan_created") {
          setMission((current) =>
            current?.taskId === taskId
              ? {
                  ...current,
                  steps: (event.steps ?? []).map((step) => ({
                    id: step.id,
                    label: step.description ?? step.tool ?? "step",
                    state: "pending",
                  })),
                }
              : current,
          );
        }
        if (type?.startsWith("mission_step_")) {
          const state = {
            mission_step_started: "running",
            mission_step_completed: "done",
            mission_step_failed: "failed",
            mission_step_skipped: "skipped",
          }[type];
          setMission((current) => {
            if (current?.taskId !== taskId || !state) return current;
            const stepId = event.step_id;
            const steps = current.steps.length
              ? current.steps.map((s) =>
                  s.id === stepId ? { ...s, state } : s,
                )
              : current.steps;
            return { ...current, steps };
          });
        }
        if (type === "mission_waiting_approval") {
          setMission((current) => {
            if (current?.taskId !== taskId) return current;
            const stepId = event.step_id;
            return {
              ...current,
              steps: current.steps.map((s) =>
                s.id === stepId ? { ...s, state: "waiting" } : s,
              ),
            };
          });
        }
        if (["mission_completed", "mission_failed", "mission_cancelled"].includes(type)) {
          setMission((current) =>
            current?.taskId === taskId ? { ...current, finished: true } : current,
          );
        }

        if (type === "agent_message" && event.message) {
          setMessages((current) => [
            ...current,
            { role: "nexus", text: event.message, taskId, at: _now() },
          ]);
        }

        if (TERMINAL.includes(type.replace("task_", ""))) {
          setBusy(false);
          activeTask.current = null;
          refreshPending();
          refreshContext();
          if (type === "task_error") setError(event.message ?? "That request failed.");
        }
      };

      ws.onclose = () => {
        clearInterval(ping);
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
  }, [loadAuthoritative, refreshContext, refreshMemories, refreshPending]);

  // --- sending -------------------------------------------------------------

  const send = useCallback(async (text) => {
    const message = text.trim();
    if (!message) return;
    setError(null);
    setBusy(true);
    setMessages((current) => [
      ...current,
      { role: "user", text: message, at: _now() },
    ]);

    let taskId;
    try {
      ({ task_id: taskId } = await sendMessage(message));
    } catch (err) {
      setError(err.message);
      setBusy(false);
      return;
    }

    activeTask.current = taskId;
    setMission(null);
    // Tag the user's turn so the answer beneath it can offer its trace.
    setMessages((current) => {
      const next = [...current];
      for (let i = next.length - 1; i >= 0; i -= 1) {
        if (next[i].role === "user" && !next[i].taskId) {
          next[i] = { ...next[i], taskId };
          break;
        }
      }
      return next;
    });

    // Safety net for an answer the socket never delivered. The guard checks
    // for an *assistant* turn: an earlier version matched any message with
    // this task id, which the user's own turn now satisfies — so the net
    // never fired and a dropped event silently lost the answer.
    setTimeout(async () => {
      if (activeTask.current !== taskId) return;
      try {
        const task = await fetchTask(taskId);
        if (!TERMINAL.includes(task.status)) return;
        if (task.response) {
          setMessages((current) =>
            current.some((m) => m.role === "nexus" && m.taskId === taskId)
              ? current
              : [
                  ...current,
                  { role: "nexus", text: task.response, taskId, at: _now() },
                ],
          );
        }
        const rebuilt = rebuildFromEvents(task.events, taskId);
        if (rebuilt.outcomes.length) {
          setOutcomes((current) => ({
            ...current,
            [taskId]: rebuilt.outcomes,
          }));
        }
        if (rebuilt.mission) {
          setMission(rebuilt.mission);
        }
        setBusy(false);
        activeTask.current = null;
      } catch {
        /* the stream remains the primary path */
      }
    }, 2000);
  }, []);

  // --- decisions -----------------------------------------------------------

  const decide = useCallback(
    async (requestId, decision) => {
      // Removed optimistically: an approval prompt that lingers after you
      // answer it is the one piece of stale UI that actually matters.
      setPending((current) => current.filter((p) => p.request_id !== requestId));
      try {
        await resolvePermission(requestId, decision);
      } catch (err) {
        setError(err.message);
        refreshPending();
      }
    },
    [refreshPending],
  );

  const dismiss = useCallback(async (observationId) => {
    setObservations((current) =>
      current.filter((o) => o.observation_id !== observationId),
    );
    try {
      await dismissObservation(observationId);
    } catch {
      loadAuthoritative();
    }
  }, [loadAuthoritative]);

  const dismissSuggestionById = useCallback(
    async (suggestionId) => {
      setSuggestions((current) =>
        current.filter((s) => s.suggestion_id !== suggestionId),
      );
      try {
        await dismissSuggestion(suggestionId);
      } catch {
        loadAuthoritative();
      }
    },
    [loadAuthoritative],
  );

  /**
   * Taking up a suggestion sends its own prompt to /api/chat, exactly as if it
   * had been typed. Nothing here executes anything: the agent chooses the
   * tools, and a CONFIRM tool still raises the ordinary approval prompt.
   */
  const acceptSuggestionById = useCallback(
    async (suggestion) => {
      const prompt = suggestion?.suggested_action?.prompt;
      if (!prompt) return;
      setSuggestions((current) =>
        current.filter((s) => s.suggestion_id !== suggestion.suggestion_id),
      );
      send(prompt);
      try {
        await acceptSuggestion(suggestion.suggestion_id);
      } catch {
        /* the message is already sent; the record is cosmetic */
      }
    },
    [send],
  );

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
    hydrated,
    context,
    memories,
    observations,
    suggestions,
    pending,
    messages,
    events,
    outcomes,
    mission,
    mcp,
    tools,
    busy,
    error,
    send,
    decide,
    dismiss,
    dismissSuggestion: dismissSuggestionById,
    acceptSuggestion: acceptSuggestionById,
    stop,
  };
}
