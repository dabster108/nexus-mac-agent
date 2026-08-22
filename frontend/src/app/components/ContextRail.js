"use client";

import { basename, relativeTime, shortenPath, summariseValue } from "@/lib/format";
import { SuggestionCard } from "./SuggestionCard";

/**
 * Quiet environmental awareness.
 *
 * Not a navigation menu and not a monitoring dashboard: a short answer to
 * "what does NEXUS currently understand about my environment?", with each
 * section present only when it has something to say. An empty rail is the
 * correct look for a fresh session, and every section carries a deliberate
 * empty state rather than a zero.
 *
 * It sits on the slate ground while the conversation sits on white, so it
 * recedes without needing a single heavier border. Blue appears here only on
 * something you can act on; everything else is slate.
 *
 * Ordering is by what needs attention: things asking for a decision first,
 * then what changed, then standing state.
 */

function Section({ title, count, children }) {
  return (
    <section className="px-4 py-4">
      <div className="mb-2.5 flex items-baseline justify-between">
        <h2 className="t-label">{title}</h2>
        {count ? (
          <span className="mono text-[11.5px] text-[var(--ink-3)]">{count}</span>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function Empty({ children }) {
  return (
    <p className="text-[12.5px] leading-[1.55] text-[var(--ink-3)]">{children}</p>
  );
}

/** Placeholder rows for the moment before the first authoritative read. */
function Loading({ rows = 2 }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="shimmer h-3" style={{ width: `${88 - i * 22}%` }} />
      ))}
    </div>
  );
}

function Workspace({ context, state }) {
  const workspace = context?.active_workspace;
  const processes = context?.processes ?? [];

  return (
    <Section title="Understands">
      {workspace ? (
        <div className="rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface)] px-3 py-2.5">
          <p className="truncate text-[13.5px] font-semibold leading-5">
            {basename(workspace.path)}
          </p>
          <p className="mono mt-0.5 truncate text-[11.5px] text-[var(--ink-3)]">
            {shortenPath(workspace.path)}
          </p>
          {workspace.git_branch ? (
            <p className="mt-2 flex items-center gap-2 text-[12.5px] text-[var(--ink-2)]">
              <span className="mono text-[var(--ink)]">{workspace.git_branch}</span>
              <span className="text-[var(--ink-4)]">·</span>
              <span>
                {workspace.git_clean
                  ? "clean"
                  : `${workspace.changed_files ?? "some"} changes`}
              </span>
            </p>
          ) : null}
        </div>
      ) : state === "loading" ? (
        <Loading rows={2} />
      ) : state === "offline" ? (
        <Empty>Not connected, so NEXUS cannot say where you are working.</Empty>
      ) : (
        <Empty>
          No workspace identified yet. Mention a project and NEXUS will verify
          it before using it.
        </Empty>
      )}

      {processes.length ? (
        <ul className="mt-2 space-y-px">
          {processes.map((process) => {
            const live = process.status === "RUNNING";
            return (
              <li
                key={process.process_id}
                className="flex items-center gap-2.5 rounded-[7px] px-2 py-1.5 hover:bg-[var(--surface-3)]"
              >
                <span
                  aria-hidden
                  className={`dot ${live ? "dot-live" : "dot-idle"}`}
                />
                <span className="min-w-0 flex-1 truncate text-[12.5px] text-[var(--ink-2)]">
                  {process.name}
                </span>
                <span className="mono text-[11.5px] text-[var(--ink-3)]">
                  {process.port ? `:${process.port}` : process.status.toLowerCase()}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </Section>
  );
}

function Attention({ suggestions, onAccept, onDismiss }) {
  if (!suggestions.length) return null;
  return (
    <Section title="Suggested">
      <ul className="space-y-2">
        {suggestions.slice(0, 2).map((suggestion, index) => (
          <SuggestionCard
            key={suggestion.suggestion_id}
            suggestion={suggestion}
            index={index}
            onAccept={onAccept}
            onDismiss={onDismiss}
          />
        ))}
      </ul>
    </Section>
  );
}

function Activity({ observations, onSend, onDismiss, state }) {
  const recent = observations.slice(0, 5);
  return (
    <Section title="Noticed" count={observations.length || null}>
      {recent.length === 0 ? (
        state === "loading" ? (
          <Loading rows={2} />
        ) : state === "offline" ? (
          <Empty>Not connected — NEXUS may have noticed things since.</Empty>
        ) : (
          <Empty>Nothing needs your attention.</Empty>
        )
      ) : (
        <ul className="space-y-0.5">
          {recent.map((observation) => {
            const notable = ["ERROR", "WARNING"].includes(observation.severity);
            return (
              <li
                key={observation.observation_id}
                className="reveal group -mx-2 rounded-[8px] px-2 py-1.5 hover:bg-[var(--surface-3)]"
              >
                <div className="flex items-start gap-2.5">
                  <span
                    aria-hidden
                    className={`dot mt-[7px] ${
                      observation.severity === "ERROR"
                        ? "dot-danger"
                        : observation.severity === "WARNING"
                          ? "dot-warn"
                          : "dot-idle"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <p
                      className={`text-[12.5px] leading-[1.45] ${
                        notable ? "text-[var(--ink)]" : "text-[var(--ink-2)]"
                      }`}
                    >
                      {observation.title}
                    </p>
                    <div className="mt-1 flex items-center gap-2.5">
                      <span className="text-[11.5px] text-[var(--ink-3)]">
                        {relativeTime(observation.created_at)}
                      </span>
                      {observation.actionable ? (
                        <button
                          type="button"
                          onClick={() =>
                            onSend(
                              `Investigate this and tell me what is going on — do not change anything: ${observation.title}`,
                            )
                          }
                          className="reveal-target text-[11.5px] font-semibold text-[var(--accent-ink)] hover:underline"
                        >
                          Investigate
                        </button>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => onDismiss(observation.observation_id)}
                        className="reveal-target text-[11.5px] text-[var(--ink-3)] hover:text-[var(--ink)]"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}

function Memory({ memories, onSend, state }) {
  // Conflicting and stale first: those are the ones worth reading.
  const ordered = [...memories].sort(
    (a, b) => Number(Boolean(b.stale)) - Number(Boolean(a.stale)),
  );
  const shown = ordered.slice(0, 4);

  return (
    <Section title="Remembers" count={memories.length || null}>
      {shown.length === 0 ? (
        state === "loading" ? (
          <Loading rows={2} />
        ) : state === "offline" ? (
          <Empty>Not connected, so what NEXUS remembers is unknown.</Empty>
        ) : (
          <Empty>NEXUS is not carrying anything forward yet.</Empty>
        )
      ) : (
        <ul className="space-y-0.5">
          {shown.map((memory) => (
            <li
              key={memory.id}
              className="reveal group -mx-2 rounded-[8px] px-2 py-1.5 hover:bg-[var(--surface-3)]"
            >
              <div className="flex items-baseline justify-between gap-2">
                <p className="min-w-0 truncate text-[12.5px] font-medium">
                  {memory.key}
                </p>
                {memory.stale ? (
                  <span className="chip chip-warn !px-2 !py-0 !text-[11px]">
                    outdated
                  </span>
                ) : (
                  <span className="flex-none text-[11px] text-[var(--ink-3)]">
                    {memory.confidence_level?.toLowerCase()}
                  </span>
                )}
              </div>
              <p className="mono mt-0.5 truncate text-[11.5px] text-[var(--ink-2)]">
                {summariseValue(memory.value)}
              </p>
              {memory.conflict ? (
                <p className="mt-1 text-[11.5px] leading-[1.45] text-[var(--warn-ink)]">
                  {memory.conflict}
                </p>
              ) : null}
              <button
                type="button"
                onClick={() => onSend(`Forget the memory "${memory.key}".`)}
                className="reveal-target mt-1 text-[11.5px] text-[var(--ink-3)] hover:text-[var(--danger-ink)]"
              >
                Forget
              </button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function ContextRail({
  context,
  memories,
  observations,
  suggestions,
  online,
  hydrated,
  mcp = [],
  onSend,
  onDismissObservation,
  onAcceptSuggestion,
  onDismissSuggestion,
}) {
  // Three states, and they are not interchangeable: "still reading",
  // "cannot reach the backend" and "read it, there is nothing".
  const state = !hydrated ? "loading" : online === false ? "offline" : "ready";

  const macServer = mcp.find((s) => s.name === "nexus-mac") ?? mcp[0];

  return (
    <div className="scroll flex h-full flex-col bg-[var(--bg)]">
      <div className="min-h-0 flex-1 divide-y divide-[var(--line)]">
        {state === "offline" ? (
          <p className="flex items-center gap-2 bg-[var(--warn-bg)] px-4 py-2.5 text-[12.5px] text-[var(--warn-ink)]">
            <span aria-hidden className="dot dot-warn" />
            Reconnecting — this is the last state NEXUS reported.
          </p>
        ) : null}
        <Attention
          suggestions={suggestions}
          onAccept={onAcceptSuggestion}
          onDismiss={onDismissSuggestion}
        />
        <Workspace context={context} state={state} />
        <Activity
          observations={observations}
          onSend={onSend}
          onDismiss={onDismissObservation}
          state={state}
        />
        <Memory memories={memories} onSend={onSend} state={state} />
      </div>

      {macServer ? (
        <footer className="flex-none border-t border-[var(--line)] px-4 py-2.5">
          <p className="flex items-center gap-2 text-[11.5px] text-[var(--ink-3)]">
            <span
              aria-hidden
              className={`dot ${
                macServer.status === "connected" ? "dot-live" : "dot-warn"
              }`}
            />
            {macServer.status === "connected" ? (
              <>
                Mac connected · {macServer.tools} tools available
              </>
            ) : (
              <>
                Mac tools unavailable
                {macServer.reason ? ` — ${macServer.reason}` : ""}
              </>
            )}
          </p>
        </footer>
      ) : null}
    </div>
  );
}
