"use client";

import { basename, shortenPath } from "@/lib/format";
import { SuggestionCard } from "../SuggestionCard";

/**
 * The dashboard home.
 *
 * Answers "what should I do next?" in the order a person actually asks it:
 * where am I, is anything wrong, what can I say. Every number is read from a
 * real endpoint — there are no charts here, because NEXUS has no time-series
 * data and inventing one to fill the grid would be decoration pretending to
 * be information.
 */

const PROMPTS = [
  "Continue where I left off",
  "What am I working on?",
  "What changed recently?",
  "What happened?",
];

function greeting() {
  const hour = new Date().getHours();
  if (hour < 5) return "Still up";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function Metric({ value, label, tone = "", index }) {
  return (
    <div
      className="card enter p-4"
      style={{ "--i": index }}
    >
      <p className={`t-metric ${tone}`}>{value}</p>
      <p className="t-label mt-1.5">{label}</p>
    </div>
  );
}

function MetricSkeleton({ index }) {
  return (
    <div className="card p-4" style={{ "--i": index }}>
      <div className="shimmer h-7 w-10" />
      <div className="shimmer mt-2.5 h-2.5 w-16" />
    </div>
  );
}

export function Overview({
  context,
  memories,
  observations,
  suggestions,
  loading,
  onSend,
  onAcceptSuggestion,
  onDismissSuggestion,
  onView,
}) {
  const workspace = context?.active_workspace;
  const processes = context?.processes ?? [];
  const running = processes.filter((p) => p.status === "RUNNING").length;
  const attention = observations.filter((o) =>
    ["ERROR", "WARNING"].includes(o.severity),
  ).length;

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      {/* --- context ------------------------------------------------------ */}
      <header className="enter" style={{ "--i": 0 }}>
        <h1 className="t-h1">{greeting()}.</h1>
        {workspace ? (
          <p className="t-body mt-1.5">
            You&rsquo;re in{" "}
            <span className="font-medium text-[var(--ink)]">
              {basename(workspace.path)}
            </span>
            {workspace.git_branch ? (
              <>
                {" "}
                on <span className="mono text-[var(--ink)]">{workspace.git_branch}</span>
                {workspace.changed_files ? (
                  <> with {workspace.changed_files} uncommitted changes</>
                ) : (
                  <> with a clean tree</>
                )}
              </>
            ) : null}
            .
          </p>
        ) : (
          <p className="t-body mt-1.5">
            No workspace established yet — mention a path and NEXUS will verify it.
          </p>
        )}
      </header>

      {/* --- primary action ----------------------------------------------- */}
      <section className="enter" style={{ "--i": 1 }}>
        <div className="card relative overflow-hidden p-5 sm:p-6">
          <div className="aurora absolute inset-0 opacity-40" />
          <div className="relative">
            <h2 className="t-h2">Pick up where you left off</h2>
            <p className="t-body mt-1.5 max-w-lg text-[0.875rem]">
              NEXUS will read your workspace, its recent commits and anything
              still running, then tell you what state you&rsquo;re in.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => onSend("Continue where I left off.")}
                className="btn btn-primary"
              >
                Continue where I left off
              </button>
              <button
                type="button"
                onClick={() => onSend("What changed recently?")}
                className="btn btn-ghost"
              >
                What changed?
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* --- metrics ------------------------------------------------------- */}
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {loading ? (
          [0, 1, 2, 3].map((index) => <MetricSkeleton key={index} index={index} />)
        ) : (
          <>
            <Metric value={running} label="Running" index={0} />
            <Metric value={memories.length} label="Memories" index={1} />
            <Metric
              value={attention}
              label="To review"
              tone={attention ? "text-[var(--warn)]" : ""}
              index={2}
            />
            <Metric value={suggestions.length} label="Suggested" index={3} />
          </>
        )}
      </section>

      {/* --- suggestions --------------------------------------------------- */}
      {suggestions.length > 0 ? (
        <section className="enter" style={{ "--i": 2 }}>
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="t-h2">Needs a decision</h2>
            <button
              type="button"
              onClick={() => onView("activity")}
              className="text-[12px] text-[var(--ink-3)] hover:text-[var(--ink)]"
            >
              All activity
            </button>
          </div>
          <ul className="space-y-2">
            {suggestions.slice(0, 3).map((suggestion, index) => (
              <SuggestionCard
                key={suggestion.suggestion_id}
                suggestion={suggestion}
                index={index}
                onAccept={onAcceptSuggestion}
                onDismiss={onDismissSuggestion}
              />
            ))}
          </ul>
        </section>
      ) : null}

      {/* --- processes ----------------------------------------------------- */}
      {processes.length > 0 ? (
        <section className="enter" style={{ "--i": 3 }}>
          <h2 className="t-h2 mb-3">Running</h2>
          <div className="card divide-y divide-[var(--line)]">
            {processes.map((process) => (
              <div
                key={process.process_id}
                className="flex items-center gap-3 px-4 py-3"
              >
                <span
                  className={`dot ${
                    process.status === "RUNNING" ? "dot-live" : "dot-idle"
                  }`}
                />
                <span className="min-w-0 flex-1 truncate text-[13px]">
                  {process.name}
                </span>
                {process.port ? (
                  <span className="mono text-[11px] text-[var(--ink-3)]">
                    :{process.port}
                  </span>
                ) : null}
                <span className="chip !text-[10px]">{process.status}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* --- ways in ------------------------------------------------------- */}
      <section className="enter" style={{ "--i": 4 }}>
        <h2 className="t-h2 mb-3">Try asking</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          {PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => onSend(prompt)}
              className="card card-hover px-4 py-3 text-left text-[13px]"
            >
              {prompt}
            </button>
          ))}
        </div>
      </section>

      {workspace ? (
        <p className="mono pb-2 text-[10.5px] text-[var(--ink-4)]">
          {shortenPath(workspace.path)}
        </p>
      ) : null}
    </div>
  );
}
