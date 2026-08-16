"use client";

import { relativeTime } from "@/lib/format";
import { SuggestionCard } from "./SuggestionCard";

/**
 * What NEXUS noticed, and what it suggests doing about it.
 *
 * "Investigate" composes an ordinary chat message and sends it — there is no
 * remediation button and no endpoint behind one. Anything NEXUS then does goes
 * through the agent, the tool registry and the approval prompt, exactly as if
 * the sentence had been typed. The panel notices; the user decides.
 */

const SEVERITY = {
  ERROR: { dot: "dot-danger", tone: "text-[var(--danger)]" },
  WARNING: { dot: "dot-warn", tone: "text-[var(--warn)]" },
  NOTICE: { dot: "dot-idle", tone: "text-[var(--ink-2)]" },
  INFO: { dot: "dot-ok", tone: "text-[var(--ink-2)]" },
};

/**
 * The investigation sentence.
 *
 * Prefixed so the observation reads as the subject of a question rather than
 * as an instruction to follow. The title cannot contain newlines or control
 * characters — the backend strips both at creation — so it cannot fabricate
 * structure once it lands in the message.
 */
function investigationFor(observation) {
  return `Investigate this and tell me what is going on — do not change anything: ${observation.title}`;
}

function Entry({ observation, onSend, onDismiss, index }) {
  const style = SEVERITY[observation.severity] ?? SEVERITY.INFO;

  return (
    <li
      className="reveal enter-x px-3.5 py-2.5 transition-colors duration-200 hover:bg-[var(--surface-2)]"
      style={{ "--i": Math.min(index, 8) }}
    >
      <div className="flex items-start gap-2.5">
        <span className={`dot ${style.dot} mt-[7px]`} />
        <div className="min-w-0 flex-1">
          <p className={`text-[12px] leading-5 ${style.tone}`}>
            {observation.title}
          </p>
          {observation.summary ? (
            <p className="mt-0.5 text-[11px] leading-[1.45] text-[var(--ink-3)]">
              {observation.summary}
            </p>
          ) : null}

          <div className="mt-1 flex items-center gap-2.5">
            <span className="text-[10px] text-[var(--ink-3)]">
              {relativeTime(observation.created_at)}
            </span>
            {observation.actionable ? (
              <button
                type="button"
                onClick={() => onSend(investigationFor(observation))}
                className="reveal-target text-[10px] font-medium text-[var(--accent)] hover:underline"
              >
                Investigate
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => onDismiss(observation.observation_id)}
              className="reveal-target text-[10px] text-[var(--ink-3)] hover:text-[var(--ink)]"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}

export function ActivityPanel({
  observations,
  suggestions = [],
  onSend,
  onDismiss,
  onAcceptSuggestion,
  onDismissSuggestion,
}) {
  const attention = observations.filter((item) =>
    ["ERROR", "WARNING"].includes(item.severity),
  ).length;

  return (
    <section className="card flex min-h-0 flex-1 flex-col overflow-hidden">
      <header className="flex flex-none items-center justify-between border-b border-[var(--line)] px-3.5 py-2.5">
        <span className="t-label">Activity</span>
        {attention > 0 ? (
          <span className="chip chip-warn enter-pop">{attention} to look at</span>
        ) : (
          <span className="text-[11px] text-[var(--ink-3)]">
            {observations.length || "nothing"} noticed
          </span>
        )}
      </header>

      <div className="scroll min-h-0 flex-1">
        {suggestions.length > 0 ? (
          <div className="border-b border-[var(--line)] p-2.5">
            <p className="t-label mb-2 px-1">Suggested</p>
            <ul className="space-y-2">
              {suggestions.map((suggestion, index) => (
                <SuggestionCard
                  key={suggestion.suggestion_id}
                  suggestion={suggestion}
                  index={index}
                  onAccept={onAcceptSuggestion}
                  onDismiss={onDismissSuggestion}
                />
              ))}
            </ul>
          </div>
        ) : null}

        {observations.length === 0 ? (
          <p className="px-3.5 py-3.5 text-[12px] leading-[1.6] text-[var(--ink-3)]">
            NEXUS will note things it notices here — a process stopping, a
            service going quiet, a remembered fact going out of date.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {observations.map((observation, index) => (
              <Entry
                key={observation.observation_id}
                observation={observation}
                index={index}
                onSend={onSend}
                onDismiss={onDismiss}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
