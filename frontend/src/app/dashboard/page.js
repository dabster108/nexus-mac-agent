"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useNexus } from "@/lib/useNexus";
import { basename } from "@/lib/format";
import { ApprovalStack } from "../components/Approval";
import { Composer } from "../components/Composer";
import { Conversation } from "../components/Conversation";
import { ContextRail } from "../components/ContextRail";

/**
 * The application.
 *
 * Two regions: the conversation, and a rail of what NEXUS currently
 * understands. There is deliberately no navigation — "Trace", "Processes" and
 * "Memory" were sections in an earlier version, which meant the sidebar was a
 * map of the backend's architecture rather than of anything the user wants.
 * Those things now appear where they are relevant: a trace under the answer it
 * explains, processes beside the workspace they belong to.
 *
 * The interface gets louder only when the system does. An approval replaces
 * the composer; a failure raises the rail's badge; everything else stays
 * quiet, which is the state it is in almost all of the time.
 */

function MenuIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** What NEXUS is doing right now, in the user's language. */
function workingLabel(events) {
  const last = [...events].reverse().find((e) =>
    [
      "context_collected",
      "tool_started",
      "verification_started",
      "permission_required",
      "mission_plan_created",
    ].includes(e.type),
  );
  return (
    {
      context_collected: "Checking your environment",
      tool_started: "Working",
      verification_started: "Verifying the result",
      permission_required: "Waiting for approval",
      mission_plan_created: "Planning the steps",
    }[last?.type] ?? "Thinking"
  );
}

export default function Dashboard() {
  const {
    online,
    context,
    memories,
    observations,
    suggestions,
    pending,
    messages,
    events,
    outcomes,
    mission,
    busy,
    error,
    send,
    decide,
    dismiss,
    dismissSuggestion,
    acceptSuggestion,
    stop,
  } = useNexus();

  const [railOpen, setRailOpen] = useState(false);

  useEffect(() => {
    const onKey = (event) => event.key === "Escape" && setRailOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const attention =
    observations.filter((o) => ["ERROR", "WARNING"].includes(o.severity)).length +
    suggestions.length;

  const workspace = context?.active_workspace;

  const rail = (
    <ContextRail
      context={context}
      memories={memories}
      observations={observations}
      suggestions={suggestions}
      onSend={(text) => {
        send(text);
        setRailOpen(false);
      }}
      onDismissObservation={dismiss}
      onAcceptSuggestion={(s) => {
        acceptSuggestion(s);
        setRailOpen(false);
      }}
      onDismissSuggestion={dismissSuggestion}
    />
  );

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      {/* --- a thin header: identity, where you are, connection ----------- */}
      <header className="flex h-14 flex-none items-center gap-3 border-b border-[var(--line)] bg-[var(--surface)] px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="grid h-[26px] w-[26px] place-items-center rounded-[8px] bg-[var(--accent)] text-[12px] font-bold text-white">
            N
          </span>
          <span className="text-[13.5px] font-bold tracking-[0.14em]">NEXUS</span>
        </Link>

        {workspace ? (
          <span className="hidden items-center gap-2 text-[12.5px] sm:flex">
            <span aria-hidden className="text-[var(--ink-4)]">/</span>
            <span className="font-medium text-[var(--ink)]">
              {basename(workspace.path)}
            </span>
            {workspace.git_branch ? (
              <span className="mono text-[12px] text-[var(--ink-3)]">
                {workspace.git_branch}
              </span>
            ) : null}
          </span>
        ) : null}

        <div className="ml-auto flex items-center gap-2">
          {online === false ? (
            <span className="chip chip-warn">
              <span className="dot dot-danger" />
              reconnecting
            </span>
          ) : null}

          <button
            type="button"
            onClick={() => setRailOpen((open) => !open)}
            aria-expanded={railOpen}
            aria-label="What NEXUS understands"
            className="btn btn-ghost !border-transparent !px-2 xl:hidden"
          >
            <MenuIcon />
            {attention > 0 ? (
              <span className="chip chip-accent !px-2 !py-0 !text-[11px]">
                {attention}
              </span>
            ) : null}
          </button>
        </div>
      </header>

      {/* One live indicator for the whole app: work is happening. */}
      <div className="h-[2px] flex-none">
        {busy ? <div className="progress-bar h-[2px] bg-[var(--accent)]" /> : null}
      </div>

      {/* --- conversation + rail ------------------------------------------ */}
      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col bg-[var(--bg-1)]">
          <Conversation
            messages={messages}
            busy={busy}
            outcomes={outcomes}
            mission={mission}
            workingLabel={workingLabel(events)}
            onSend={send}
          />

          {error ? (
            <p
              role="alert"
              className="enter-sm mx-auto w-full max-w-3xl px-6 pb-2 text-[12.5px] text-[var(--danger-ink)]"
            >
              {error}
            </p>
          ) : null}

          {/* An approval replaces the composer: it is the only thing to do. */}
          {pending.length ? (
            <ApprovalStack requests={pending} onDecide={decide} />
          ) : (
            <Composer busy={busy} onSend={send} onStop={stop} />
          )}
        </main>

        <aside className="hidden w-[300px] flex-none border-l border-[var(--line)] xl:block">
          {rail}
        </aside>
      </div>

      {/* --- the rail as a sheet on narrow screens ------------------------ */}
      {railOpen ? (
        <div className="fixed inset-0 z-50 xl:hidden">
          <button
            type="button"
            aria-label="Close"
            onClick={() => setRailOpen(false)}
            className="enter-fade absolute inset-0 bg-[rgb(15_23_42/0.32)]"
          />
          <div
            className="absolute inset-y-0 right-0 flex w-[310px] max-w-[86vw] flex-col border-l border-[var(--line)] bg-[var(--bg)] shadow-[var(--shadow-lg)]"
            style={{ animation: "slide-x var(--t-slow) var(--ease) both" }}
          >
            <div className="flex h-14 flex-none items-center justify-between border-b border-[var(--line)] px-4">
              <span className="t-label">What NEXUS understands</span>
              <button
                type="button"
                onClick={() => setRailOpen(false)}
                aria-label="Close"
                className="btn btn-ghost !border-transparent !px-2"
              >
                <CloseIcon />
              </button>
            </div>
            <div className="min-h-0 flex-1">{rail}</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
