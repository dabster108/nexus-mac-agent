"use client";

/**
 * A suggestion, and the two things a person can do with it.
 *
 * The accept button sends the suggestion's own `prompt` to /api/chat — the
 * same path as typing it. There is no execute endpoint behind it, and the
 * label is never a vague "Fix": a button that hides what it will do is how a
 * proactive assistant becomes an autonomous one by accident. The verb comes
 * from the intent, so "Restart backend" reads as a change and "Investigate"
 * reads as a look.
 */

const SEVERITY = {
  ERROR: { dot: "dot-danger", ring: "border-[var(--danger)]" },
  WARNING: { dot: "dot-warn", ring: "border-[var(--line-strong)]" },
  NOTICE: { dot: "dot-idle", ring: "border-[var(--line-strong)]" },
  INFO: { dot: "dot-ok", ring: "border-[var(--line-strong)]" },
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

export function SuggestionCard({ suggestion, onAccept, onDismiss }) {
  const style = SEVERITY[suggestion.severity] ?? SEVERITY.INFO;
  const action = suggestion.suggested_action ?? {};
  const label = ACTION_LABEL[action.intent] ?? "Look into it";

  return (
    <li className={`rounded-[8px] border ${style.ring} bg-[var(--panel-2)] p-2.5`}>
      <div className="flex items-start gap-2">
        <span className={`dot ${style.dot} mt-[6px]`} />
        <div className="min-w-0 flex-1">
          <p className="text-[12px] font-medium leading-5">{suggestion.title}</p>
          <p className="mt-0.5 text-[11px] leading-4 text-[var(--ink-2)]">
            {suggestion.description}
          </p>
          {suggestion.reason ? (
            <p className="mt-1 text-[11px] leading-4 text-[var(--ink-3)]">
              {suggestion.reason}
            </p>
          ) : null}

          <div className="mt-2 flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => onAccept(suggestion)}
              className="rounded-[6px] bg-[var(--ink)] px-2.5 py-1 text-[11px] text-[var(--bg)] hover:opacity-90"
            >
              {label}
            </button>
            <button
              type="button"
              onClick={() => onDismiss(suggestion.suggestion_id)}
              className="rounded-[6px] border border-[var(--line-strong)] px-2.5 py-1 text-[11px] text-[var(--ink-2)] hover:border-[var(--ink-3)]"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}
