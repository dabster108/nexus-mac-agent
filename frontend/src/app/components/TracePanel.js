"use client";

import { useState } from "react";
import { fetchTrace } from "@/lib/api";

/**
 * "How NEXUS reached this result."
 *
 * Compact by default — a one-line summary and a link — because the trace is
 * for the moment you doubt an answer, not for every answer. Expanding fetches
 * the trace once and shows the phases in order.
 *
 * Everything here is a projection of events that already fired. There is no
 * action in this panel and no endpoint behind it that could take one: opening
 * a trace cannot change anything, which is why it is safe to make it this easy
 * to open.
 */

const MARK = {
  ok: { glyph: "✓", tone: "text-[var(--ok-ink)]" },
  failed: { glyph: "✕", tone: "text-[var(--danger-ink)]" },
  waiting: { glyph: "◔", tone: "text-[var(--warn-ink)]" },
  denied: { glyph: "✕", tone: "text-[var(--warn-ink)]" },
  skipped: { glyph: "–", tone: "text-[var(--ink-3)]" },
  info: { glyph: "·", tone: "text-[var(--ink-3)]" },
};

const PHASE_LABEL = {
  CONTEXT: "Context",
  ACTION: "Action",
  APPROVAL: "Approval",
  VERIFICATION: "Verification",
  OUTCOME: "Outcome",
  MISSION: "Mission",
};

function Step({ step }) {
  const mark = MARK[step.mark] ?? MARK.info;
  return (
    <li className="flex items-start gap-2 py-[3px]">
      <span className={`mono mt-[1px] w-3 flex-none text-center ${mark.tone}`}>
        {mark.glyph}
      </span>
      <div className="min-w-0">
        <p className="break-words text-[12.5px] leading-[1.5] text-[var(--ink)]">{step.label}</p>
        {step.reason ? (
          <p className="text-[12px] leading-[1.45] text-[var(--ink-3)]">
            {step.reason}
          </p>
        ) : null}
      </div>
    </li>
  );
}

function Section({ phase, steps }) {
  if (!steps.length) return null;
  return (
    <div className="border-t border-[var(--line)] px-3 py-2.5 first:border-t-0">
      <p className="t-label mb-1.5">{PHASE_LABEL[phase] ?? phase}</p>
      <ul>
        {steps.map((step, index) => (
          <Step key={`${step.label}-${index}`} step={step} />
        ))}
      </ul>
    </div>
  );
}

function ContextSection({ items }) {
  if (!items.length) return null;
  return (
    <div className="border-t border-[var(--line)] px-3 py-2.5 first:border-t-0">
      <p className="t-label mb-1.5">Context</p>
      <ul>
        {items.map((item, index) => (
          <li key={index} className="flex items-start gap-2 py-[3px]">
            <span
              className={`mono mt-[1px] w-3 flex-none text-center ${
                item.provided ? "text-[var(--ok-ink)]" : "text-[var(--ink-3)]"
              }`}
            >
              {item.provided ? "✓" : "–"}
            </span>
            <div className="min-w-0">
              <p className="text-[12.5px] leading-[1.5]">
                {item.label}
                {item.provided ? null : (
                  <span className="text-[var(--ink-3)]"> · gathered, not used</span>
                )}
              </p>
              {item.detail ? (
                <p className="mono truncate text-[12px] text-[var(--ink-2)]">
                  {item.detail}
                </p>
              ) : null}
              {item.reason ? (
                <p className="text-[12px] leading-[1.45] text-[var(--ink-3)]">
                  {item.reason}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function TracePanel({ taskId, summary, time }) {
  const [open, setOpen] = useState(false);
  const [trace, setTrace] = useState(null);
  const [state, setState] = useState("idle");

  const toggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (trace || state === "loading") return;
    setState("loading");
    try {
      setTrace(await fetchTrace(taskId));
      setState("ready");
    } catch {
      setState("error");
    }
  };

  const phases = ["ACTION", "APPROVAL", "VERIFICATION", "OUTCOME", "MISSION"];

  return (
    <div className="w-full">
      <div className="flex items-center gap-2.5">
        {time ? (
          <span className="mono text-[11.5px] text-[var(--ink-3)]">{time}</span>
        ) : null}
        {time ? <span aria-hidden className="text-[var(--ink-4)]">·</span> : null}
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          className="text-[12px] font-semibold text-[var(--ink-3)] transition-colors hover:text-[var(--accent-ink)]"
        >
          {open ? "Hide details" : "How NEXUS reached this"}
        </button>
      </div>

      {summary ? (
        <p className="mt-1 text-[12.5px] leading-[1.5] text-[var(--ink-2)]">
          {summary}
        </p>
      ) : null}

      {open ? (
        <div className="enter-sm mt-2 overflow-hidden rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface-2)]">
          {state === "loading" ? (
            <div className="space-y-2 p-3">
              <div className="shimmer h-2.5 w-2/3" />
              <div className="shimmer h-2.5 w-1/2" />
            </div>
          ) : null}

          {state === "error" ? (
            <p className="px-3 py-2.5 text-[12px] text-[var(--ink-3)]">
              No trace is available for this task.
            </p>
          ) : null}

          {trace ? (
            <>
              <ContextSection items={trace.context ?? []} />
              {phases.map((phase) => (
                <Section
                  key={phase}
                  phase={phase}
                  steps={(trace.steps ?? []).filter((s) => s.phase === phase)}
                />
              ))}
              {trace.outcome_reason ? (
                <p className="border-t border-[var(--line)] px-3 py-2.5 text-[12px] leading-[1.5] text-[var(--ink-2)]">
                  {trace.outcome_reason}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
