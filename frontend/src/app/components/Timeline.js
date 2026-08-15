"use client";

import { useEffect, useRef } from "react";
import { clockTime, eventLabel } from "@/lib/format";

/**
 * The execution timeline, from the existing WebSocket events.
 *
 * Kept deliberately quiet — monospace, small, one accent for the moments that
 * need a person (a permission request) and one for failure. It is meant to be
 * glanceable while something runs and ignorable when nothing is.
 */

const TONE = {
  permission_required: "text-[var(--warn)]",
  task_error: "text-[var(--danger)]",
  memory_conflict: "text-[var(--warn)]",
  task_completed: "text-[var(--ok)]",
  mission_completed: "text-[var(--ok)]",
};

export function Timeline({ events }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [events.length]);

  return (
    <section className="panel flex min-h-0 flex-col overflow-hidden">
      <header className="border-b border-[var(--line)] px-3 py-2">
        <span className="panel-head">Activity</span>
      </header>

      {events.length === 0 ? (
        <p className="px-3 py-3 text-[12px] text-[var(--ink-3)]">
          Events appear here as NEXUS works.
        </p>
      ) : (
        <ol className="scroll mono min-h-0 flex-1 space-y-0.5 px-3 py-2 text-[11px] leading-[18px]">
          {events.map((event, index) => (
            <li
              key={`${event.timestamp}-${index}`}
              className="flex gap-2 whitespace-nowrap"
            >
              <span className="text-[var(--ink-3)]">
                {clockTime(event.timestamp)}
              </span>
              <span className={TONE[event.type] ?? "text-[var(--ink-2)]"}>
                {eventLabel(event.type)}
              </span>
              {event.tool ? (
                <span className="truncate text-[var(--ink-3)]">{event.tool}</span>
              ) : null}
            </li>
          ))}
          <li ref={endRef} />
        </ol>
      )}
    </section>
  );
}
