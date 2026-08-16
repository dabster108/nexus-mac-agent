"use client";

import { useEffect, useRef } from "react";
import { clockTime, eventLabel } from "@/lib/format";

/**
 * The execution timeline, from the existing WebSocket events.
 *
 * Deliberately the quietest panel: monospace, small, one accent for the
 * moments that need a person and one for failure. It should be glanceable
 * while something runs and completely ignorable when nothing is.
 *
 * A rail down the left turns a list of timestamps into a sequence, which is
 * the only thing anyone actually reads it for.
 */

const TONE = {
  permission_required: "text-[var(--warn)]",
  memory_conflict: "text-[var(--warn)]",
  task_error: "text-[var(--danger)]",
  mission_failed: "text-[var(--danger)]",
  task_completed: "text-[var(--ok)]",
  mission_completed: "text-[var(--ok)]",
  observation_created: "text-[var(--accent)]",
  suggestion_created: "text-[var(--accent)]",
};

export function Timeline({ events, expanded = false }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [events.length]);

  return (
    <section
      className={`card flex flex-col overflow-hidden ${
        expanded ? "max-h-[70vh]" : "max-h-[190px]"
      }`}
    >
      <header className="flex flex-none items-center justify-between border-b border-[var(--line)] px-3.5 py-2.5">
        <span className="t-label">Trace</span>
        {events.length ? (
          <span className="text-[11px] text-[var(--ink-3)]">
            {events.length}
          </span>
        ) : null}
      </header>

      {events.length === 0 ? (
        <p className="px-3.5 py-3 text-[11px] text-[var(--ink-3)]">
          Steps appear here as NEXUS works.
        </p>
      ) : (
        <ol className="scroll mono relative min-h-0 flex-1 py-2 pl-[26px] pr-3 text-[10.5px] leading-[19px]">
          {/* the rail */}
          <span
            aria-hidden
            className="absolute bottom-2 left-[13px] top-2 w-px bg-[var(--line)]"
          />
          {events.map((event, index) => (
            <li
              key={`${event.timestamp}-${index}`}
              className="enter-sm relative flex gap-2 whitespace-nowrap"
              style={{ "--i": Math.min(index, 6) }}
            >
              <span
                aria-hidden
                className="absolute -left-[17px] top-[7px] h-1 w-1 rounded-full bg-[var(--line-2)]"
              />
              <span className="text-[var(--ink-3)]">
                {clockTime(event.timestamp)}
              </span>
              <span className={TONE[event.type] ?? "text-[var(--ink-2)]"}>
                {eventLabel(event.type)}
              </span>
              {event.tool ? (
                <span className="truncate text-[var(--ink-3)]">
                  {event.tool}
                </span>
              ) : null}
            </li>
          ))}
          <li ref={endRef} />
        </ol>
      )}
    </section>
  );
}
