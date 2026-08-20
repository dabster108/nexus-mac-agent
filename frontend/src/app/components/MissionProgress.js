"use client";

/**
 * A multi-step objective, shown as one coherent thing.
 *
 * The user should understand progress without meeting the words "mission",
 * "step id", "tool node" or "task record" — so this shows the plan's own
 * descriptions and nothing about how the engine runs them. Advanced detail is
 * one expansion away in the trace, which is where it belongs.
 *
 * Every state here corresponds to a real engine state: pending, running, done,
 * failed, skipped. Nothing is inferred and nothing is animated for effect.
 */

function Check() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="8" cy="8" r="7" fill="var(--ok)" />
      <path
        d="M5 8.2l2.1 2.1L11 6.4"
        stroke="#fff"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Running() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="8" cy="8" r="7" fill="var(--accent-bg)" stroke="var(--accent)" />
      <circle cx="8" cy="8" r="2.6" fill="var(--accent)" />
    </svg>
  );
}

function Failed() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="8" cy="8" r="7" fill="var(--danger)" />
      <path
        d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"
        stroke="#fff"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function Pending() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="8" cy="8" r="6.5" stroke="var(--line-2)" strokeDasharray="2.5 2.5" />
    </svg>
  );
}

const STATE = {
  done: { Icon: Check, label: "done", tone: "text-[var(--ink-2)]" },
  running: { Icon: Running, label: "running", tone: "text-[var(--ink)] font-medium" },
  failed: { Icon: Failed, label: "failed", tone: "text-[var(--ink)]" },
  skipped: { Icon: Pending, label: "skipped", tone: "text-[var(--ink-3)]" },
  pending: { Icon: Pending, label: "waiting", tone: "text-[var(--ink-3)]" },
};

export function MissionProgress({ mission }) {
  if (!mission || !mission.steps?.length) return null;

  const total = mission.steps.length;
  const done = mission.steps.filter((s) => s.state === "done").length;
  const failed = mission.steps.some((s) => s.state === "failed");
  const running = mission.steps.find((s) => s.state === "running");

  return (
    <section
      aria-label="Multi-step progress"
      className="enter overflow-hidden rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface)]"
    >
      <div className="px-4 pb-3 pt-3.5">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-[13.5px] font-semibold leading-5">
            {mission.objective || "Working through this"}
          </h3>
          <span className="mono flex-none text-[11.5px] text-[var(--ink-3)]">
            {done}/{total}
          </span>
        </div>

        {/* One bar, driven by the real completed count. */}
        <div
          className="mt-2.5 h-[3px] overflow-hidden rounded-full bg-[var(--surface-3)]"
          role="progressbar"
          aria-valuenow={done}
          aria-valuemin={0}
          aria-valuemax={total}
        >
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{
              width: `${(done / total) * 100}%`,
              background: failed ? "var(--danger)" : "var(--accent)",
            }}
          />
        </div>

        {running ? (
          <p className="mt-2 text-[12.5px] text-[var(--ink-2)]">
            Currently: {running.label}
          </p>
        ) : null}
      </div>

      <ol className="border-t border-[var(--line)] px-4 py-2.5">
        {mission.steps.map((step) => {
          const state = STATE[step.state] ?? STATE.pending;
          const { Icon } = state;
          return (
            <li key={step.id} className="flex items-start gap-2.5 py-[5px]">
              <span className="mt-[2px] flex-none">
                <Icon />
              </span>
              <span className={`text-[13px] leading-[1.45] ${state.tone}`}>
                {step.label}
                {/* Status in words too: colour alone must never carry it. */}
                <span className="sr-only"> — {state.label}</span>
              </span>
            </li>
          );
        })}
      </ol>

      {failed && mission.finished ? (
        <p className="border-t border-[var(--line)] bg-[var(--surface-2)] px-4 py-2.5 text-[12.5px] leading-[1.5] text-[var(--ink-2)]">
          One step did not succeed. The steps that depended on it were skipped.
        </p>
      ) : null}
    </section>
  );
}
