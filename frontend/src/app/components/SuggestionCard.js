"use client";

/**
 * A suggestion, and the two things a person can do with it.
 *
 * Accepting sends the suggestion's own `prompt` to /api/chat — the same path
 * as typing it. There is no execute endpoint behind the button, and the label
 * is never a vague "Fix": a button that hides what it will do is how a
 * proactive assistant becomes an autonomous one by accident. The verb comes
 * from the intent, so "Restart backend" reads as a change and "Investigate"
 * reads as a look.
 *
 * These arrive unprompted, so they are the one surface that gets a spring on
 * entry — a small overshoot is how a panel says "this is new" without
 * resorting to colour.
 */

const SEVERITY = {
  ERROR: { dot: "dot-danger", edge: "var(--danger)" },
  WARNING: { dot: "dot-warn", edge: "var(--warn)" },
  NOTICE: { dot: "dot-idle", edge: "var(--line-2)" },
  INFO: { dot: "dot-ok", edge: "var(--ok)" },
};

/** Explicit verbs only — never "Fix". */
const ACTION_LABEL = {
  investigate_process: "Investigate",
  investigate_service: "Investigate",
  investigate_task: "Investigate",
  inspect_process: "Check it",
  review_changes: "Review changes",
  update_memory: "Update memory",
  save_memory: "Remember it",
};

export function SuggestionCard({ suggestion, onAccept, onDismiss, index = 0 }) {
  const style = SEVERITY[suggestion.severity] ?? SEVERITY.INFO;
  const action = suggestion.suggested_action ?? {};
  const label = ACTION_LABEL[action.intent] ?? "Look into it";

  return (
    <li
      className="enter-pop relative overflow-hidden rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface)] p-3"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      {/* A coloured edge carries the severity without tinting the whole card. */}
      <span
        aria-hidden
        className="absolute left-0 top-0 h-full w-[2px]"
        style={{ background: style.edge }}
      />

      <div className="flex items-start gap-2 pl-1">
        <span className={`dot ${style.dot} mt-[7px]`} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold leading-5">
            {suggestion.title}
          </p>
          <p className="mt-1 text-[12.5px] leading-[1.5] text-[var(--ink-2)]">
            {suggestion.description}
          </p>
          {suggestion.reason ? (
            <p className="mt-1 text-[12px] leading-[1.5] text-[var(--ink-3)]">
              {suggestion.reason}
            </p>
          ) : null}

          <div className="mt-2.5 flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => onAccept(suggestion)}
              className="btn btn-primary btn-sm"
            >
              {label}
            </button>
            <button
              type="button"
              onClick={() => onDismiss(suggestion.suggestion_id)}
              className="btn btn-ghost btn-sm"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}
