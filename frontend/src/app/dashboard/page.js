"use client";

import { useEffect, useState } from "react";
import { useNexus } from "@/lib/useNexus";
import { basename } from "@/lib/format";
import { ActivityPanel } from "../components/ActivityPanel";
import { ApprovalBar } from "../components/ApprovalBar";
import { Composer } from "../components/Composer";
import { Conversation } from "../components/Conversation";
import { ContextPanel } from "../components/ContextPanel";
import { MemoryPanel } from "../components/MemoryPanel";
import { Timeline } from "../components/Timeline";
import { Overview } from "../components/shell/Overview";
import { SECTIONS, Sidebar, SidebarContent } from "../components/shell/Sidebar";

/**
 * The application.
 *
 * Three columns on a wide screen: navigation, the conversation, and the
 * context NEXUS is working from. The right rail is the argument the whole
 * product makes — an assistant claiming to understand your environment should
 * show what it believes about it, beside its answers, so a wrong answer and a
 * wrong belief are visibly the same bug.
 *
 * Below `lg` the rail collapses into the section views the sidebar already
 * offers, so nothing is lost on a tablet; below `sm` the nav becomes a sheet.
 * The conversation is never the thing that gets dropped.
 */

function MenuIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M4 4l8 8M12 4l-8 8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function Dashboard() {
  const {
    online,
    context,
    memories,
    events,
    messages,
    pending,
    observations,
    suggestions,
    verifications,
    busy,
    error,
    send,
    decide,
    dismiss,
    dismissSuggestion,
    acceptSuggestion,
    stop,
  } = useNexus();

  const [view, setView] = useState("overview");
  const [navOpen, setNavOpen] = useState(false);
  const loading = context === null;

  // Sending a message moves you to the conversation: the answer is the point,
  // and staying on a metrics screen while it streams in would hide it.
  const sendAndFocus = (text) => {
    send(text);
    setView("conversation");
  };

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") setNavOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const workspace = context?.active_workspace
    ? {
        name: basename(context.active_workspace.path),
        path: context.active_workspace.path,
        branch: context.active_workspace.git_branch,
        changed: context.active_workspace.changed_files,
      }
    : null;

  const counts = {
    activity: observations.filter((o) => ["ERROR", "WARNING"].includes(o.severity))
      .length,
    memory: memories.length,
    processes: (context?.processes ?? []).filter((p) => p.status === "RUNNING")
      .length,
  };

  const navProps = {
    view,
    onView: setView,
    counts,
    workspace,
    online,
    onNavigate: () => setNavOpen(false),
  };

  const sectionTitle =
    view === "conversation"
      ? "Conversation"
      : (SECTIONS.find((s) => s.id === view)?.label ?? "Overview");

  return (
    <div className="flex h-full overflow-hidden bg-[var(--bg)]">
      <Sidebar {...navProps} />

      {/* --- mobile navigation sheet --------------------------------------- */}
      {navOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setNavOpen(false)}
            className="enter-fade absolute inset-0 bg-black/60 backdrop-blur-sm"
          />
          <div
            className="absolute inset-y-0 left-0 flex w-[264px] flex-col border-r border-[var(--line)] bg-[var(--bg-1)] p-3"
            style={{ animation: "slide-x var(--t-slow) var(--ease) both" }}
          >
            <SidebarContent {...navProps} />
          </div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* --- top bar ----------------------------------------------------- */}
        <header className="flex h-14 flex-none items-center gap-3 border-b border-[var(--line)] px-3 sm:px-5">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
            className="btn btn-ghost !border-transparent !px-2 lg:hidden"
          >
            <MenuIcon />
          </button>

          <h1 className="text-[13.5px] font-medium">{sectionTitle}</h1>

          {view !== "conversation" && messages.length > 0 ? (
            <button
              type="button"
              onClick={() => setView("conversation")}
              className="chip hover:border-[var(--line-3)]"
            >
              {messages.length} messages
            </button>
          ) : null}

          <div className="ml-auto flex items-center gap-2">
            {busy ? (
              <span className="chip chip-accent">
                <span className="dot dot-accent thinking-dot" />
                working
              </span>
            ) : null}
            <span className={`chip ${online ? "chip-ok" : "chip-danger"}`}>
              <span className={`dot ${online ? "dot-live" : "dot-danger"}`} />
              <span className="hidden sm:inline">
                {online ? "connected" : "offline"}
              </span>
            </span>
          </div>
        </header>

        <div className="h-px w-full flex-none bg-[var(--line)]">
          {busy ? <div className="progress-bar h-px bg-[var(--accent)]" /> : null}
        </div>

        {/* --- workspace ---------------------------------------------------- */}
        <div className="flex min-h-0 flex-1">
          <main className="flex min-w-0 flex-1 flex-col">
            {view === "overview" ? (
              <div className="scroll flex-1 p-4 sm:p-6 lg:p-8">
                <Overview
                  context={context}
                  memories={memories}
                  observations={observations}
                  suggestions={suggestions}
                  loading={loading}
                  onSend={sendAndFocus}
                  onAcceptSuggestion={acceptSuggestion}
                  onDismissSuggestion={dismissSuggestion}
                  onView={setView}
                />
              </div>
            ) : null}

            {view === "conversation" ? (
              <>
                <Conversation
                  messages={messages}
                  busy={busy}
                  onSend={sendAndFocus}
                  verifications={verifications}
                />
                {error ? (
                  <p className="enter-sm border-t border-[var(--line)] bg-[var(--danger-bg)] px-5 py-2.5 text-[12px] text-[var(--danger)]">
                    {error}
                  </p>
                ) : null}
                <ApprovalBar requests={pending} onDecide={decide} />
                <Composer busy={busy} onSend={send} onStop={stop} />
              </>
            ) : null}

            {view === "activity" ? (
              <div className="scroll flex-1 p-4 sm:p-6">
                <div className="mx-auto max-w-3xl">
                  <ActivityPanel
                    observations={observations}
                    suggestions={suggestions}
                    onSend={sendAndFocus}
                    onDismiss={dismiss}
                    onAcceptSuggestion={acceptSuggestion}
                    onDismissSuggestion={dismissSuggestion}
                  />
                </div>
              </div>
            ) : null}

            {view === "memory" ? (
              <div className="scroll flex-1 p-4 sm:p-6">
                <div className="mx-auto max-w-3xl">
                  <MemoryPanel memories={memories} onSend={sendAndFocus} />
                </div>
              </div>
            ) : null}

            {view === "processes" ? (
              <div className="scroll flex-1 p-4 sm:p-6">
                <div className="mx-auto max-w-3xl">
                  <ContextPanel context={context} />
                </div>
              </div>
            ) : null}

            {view === "trace" ? (
              <div className="scroll flex-1 p-4 sm:p-6">
                <div className="mx-auto max-w-3xl">
                  <Timeline events={events} expanded />
                </div>
              </div>
            ) : null}
          </main>

          {/* --- context rail: desktop only ---------------------------------- */}
          <aside className="hidden w-[300px] flex-none flex-col gap-3 overflow-hidden border-l border-[var(--line)] bg-[var(--bg-1)] p-3 xl:flex">
            <ContextPanel context={context} />
            <div className="flex min-h-0 flex-1 flex-col">
              <ActivityPanel
                observations={observations}
                suggestions={suggestions}
                onSend={sendAndFocus}
                onDismiss={dismiss}
                onAcceptSuggestion={acceptSuggestion}
                onDismissSuggestion={dismissSuggestion}
              />
            </div>
            <Timeline events={events} />
          </aside>
        </div>

        {/* The composer follows you: on any view but the conversation it sits
            at the bottom, so asking never costs a navigation. */}
        {view !== "conversation" ? (
          <div className="flex-none border-t border-[var(--line)]">
            <ApprovalBar requests={pending} onDecide={decide} />
            <Composer busy={busy} onSend={sendAndFocus} onStop={stop} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
