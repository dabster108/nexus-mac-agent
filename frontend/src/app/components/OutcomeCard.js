"use client";

/**
 * What an action actually achieved.
 *
 * The distinction this card exists to draw: a tick beside "action completed"
 * means the tool returned, and that is *not* the same as the goal being met.
 * So the evidence is listed line by line with its own marks, and the verdict
 * sits at the bottom where it reads as a conclusion drawn from them rather
 * than as a status the tool reported.
 *
 * The Investigate button composes an ordinary chat message. There is no
 * execution endpoint behind it and no remediation button anywhere on this
 * card — a failed action is diagnosed, never silently retried.
 */

const OUTCOME = {
  SUCCESS: {
    label: "Success",
    tone: "text-[var(--ok)]",
    edge: "var(--ok)",
    chip: "chip-ok",
  },
  PARTIAL_SUCCESS: {
    label: "Partly verified",
    tone: "text-[var(--warn)]",
    edge: "var(--warn)",
    chip: "chip-warn",
  },
  FAILED: {
    label: "Failed",
    tone: "text-[var(--danger)]",
    edge: "var(--danger)",
    chip: "chip-danger",
  },
  UNKNOWN: {
    label: "Unverified",
    tone: "text-[var(--ink-2)]",
    edge: "var(--line-3)",
    chip: "",
  },
};

function Tick() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden className="flex-none">
      <path
        d="M3.5 8.5l3 3 6-7"
        stroke="var(--ok)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Cross() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden className="flex-none">
      <path
        d="M4 4l8 8M12 4l-8 8"
        stroke="var(--danger)"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function Dash() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden className="flex-none">
      <path d="M4 8h8" stroke="var(--ink-3)" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function OutcomeCard({ verification, onSend }) {
  const style = OUTCOME[verification.outcome] ?? OUTCOME.UNKNOWN;
  const failed = verification.outcome === "FAILED";
  const evidence = verification.evidence ?? [];
  const unknowns = verification.unknowns ?? [];

  return (
    <div className="enter-pop relative overflow-hidden rounded-[10px] border border-[var(--line)] bg-[var(--surface-2)]">
      <span
        aria-hidden
        className="absolute left-0 top-0 h-full w-[2px]"
        style={{ background: style.edge }}
      />

      <div className="px-3.5 py-3 pl-4">
        <div className="flex items-center gap-2">
          <span className="mono text-[11px] text-[var(--ink-3)]">
            {verification.tool}
          </span>
          <span className={`chip ml-auto ${style.chip}`}>{style.label}</span>
        </div>

        <ul className="mt-2 space-y-1">
          {/* The action itself. Always a tick — it ran. */}
          <li className="flex items-start gap-2 text-[12px] leading-[1.5]">
            <span className="mt-[3px]">
              <Tick />
            </span>
            <span className="text-[var(--ink-2)]">Action completed</span>
          </li>

          {evidence.map((statement, index) => (
            <li
              key={index}
              className="flex items-start gap-2 text-[12px] leading-[1.5]"
            >
              <span className="mt-[3px]">{failed ? <Cross /> : <Tick />}</span>
              <span className="text-[var(--ink)]">{statement}</span>
            </li>
          ))}

          {unknowns.map((statement, index) => (
            <li
              key={`u-${index}`}
              className="flex items-start gap-2 text-[12px] leading-[1.5]"
            >
              <span className="mt-[3px]">
                <Dash />
              </span>
              <span className="text-[var(--ink-3)]">{statement}</span>
            </li>
          ))}
        </ul>

        {verification.summary ? (
          <p className={`mt-2.5 text-[12.5px] font-medium ${style.tone}`}>
            {verification.summary}
          </p>
        ) : null}

        {failed ? (
          <button
            type="button"
            onClick={() =>
              onSend(
                `Investigate why ${verification.tool} did not work — read the logs and status and tell me what you find. Do not change anything.`,
              )
            }
            className="btn btn-ghost mt-2.5 !px-2.5 !py-1 !text-[11px]"
          >
            Investigate logs
          </button>
        ) : null}
      </div>
    </div>
  );
}
