"use client";

import { relativeTime } from "@/lib/format";
import { SuggestionCard } from "./SuggestionCard";

/**
 * What NEXUS noticed on its own.
 *
 * "Investigate" composes an ordinary chat message and sends it — there is no
 * remediation button, and no endpoint behind one. Anything NEXUS then does
 * goes through the agent, the tool registry and the approval prompt, exactly
 * as if the sentence had been typed. The panel notices; the user decides.
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
 * Built from the observation's *category* and its already-sanitised title, and
 * always prefixed so the text reads as the subject of a question rather than
 * as a instruction to follow. The title cannot contain newlines or control
 * characters — the backend strips both at creation — so it cannot fabricate
 * structure once it lands in the message.
 */
function investigationFor(observation) {
  return `Investigate this and tell me what is going on — do not change anything: ${observation.title}`;
}

function Entry({ observation, onSend, onDismiss }) {
  const style = SEVERITY[observation.severity] ?? SEVERITY.INFO;

  return (
    <li className="group px-3 py-2">
      <div className="flex items-start gap-2">
        <span className={`dot ${style.dot} mt-[6px]`} />
        <div className="min-w-0 flex-1">
          <p className={`text-[12px] leading-5 ${style.tone}`}>{observation.title}</p>
          {observation.summary ? (
            <p className="mt-0.5 text-[11px] leading-4 text-[var(--ink-3)]">
              {observation.summary}
            </p>
          ) : null}
          <div className="mt-1 flex items-center gap-2">
            <span className="text-[10px] text-[var(--ink-3)]">
              {relativeTime(observation.created_at)}
            </span>
            {observation.actionable ? (
              <button
                type="button"
                onClick={() => onSend(investigationFor(observation))}
                className="text-[10px] text-[var(--accent)] opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
              >
                Investigate
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => onDismiss(observation.observation_id)}
              className="text-[10px] text-[var(--ink-3)] opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
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
    <section className="panel flex min-h-0 flex-col overflow-hidden">
      <header className="flex items-center justify-between border-b border-[var(--line)] px-3 py-2">
        <span className="panel-head">Activity</span>
        {attention > 0 ? (
          <span className="chip chip-warn">{attention} need attention</span>
        ) : (
          <span className="text-[11px] text-[var(--ink-3)]">
            {observations.length || "nothing"} noticed
          </span>
        )}
      </header>

      {suggestions.length > 0 ? (
        <div className="border-b border-[var(--line)] p-2">
          <p className="panel-head mb-1.5 px-1">Suggested</p>
          <ul className="space-y-1.5">
            {suggestions.map((suggestion) => (
              <SuggestionCard
                key={suggestion.suggestion_id}
                suggestion={suggestion}
                onAccept={onAcceptSuggestion}
                onDismiss={onDismissSuggestion}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {observations.length === 0 ? (
        <p className="px-3 py-3 text-[12px] leading-5 text-[var(--ink-3)]">
          NEXUS will note things it notices here — a process stopping, a service
          going quiet, a remembered fact going out of date.
        </p>
      ) : (
        <ul className="scroll min-h-0 flex-1 divide-y divide-[var(--line)]">
          {observations.map((observation) => (
            <Entry
              key={observation.observation_id}
              observation={observation}
              onSend={onSend}
              onDismiss={onDismiss}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
