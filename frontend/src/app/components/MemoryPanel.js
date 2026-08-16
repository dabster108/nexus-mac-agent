"use client";

import { useState } from "react";
import { relativeTime, summariseValue } from "@/lib/format";

/**
 * What NEXUS remembers, and how much it trusts each item.
 *
 * "Forget" does not call a delete endpoint — there isn't one. It composes the
 * sentence a user would type, so the request goes through the agent and raises
 * the same approval prompt any deletion raises. The button is a shortcut for
 * typing, not a second route to the same effect.
 */

const CONFIDENCE = {
  HIGH: "chip-accent",
  MEDIUM: "",
  LOW: "chip-warn",
};

function Chevron({ open }) {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
      className="transition-transform duration-200"
      style={{ transform: open ? "rotate(90deg)" : "none" }}
    >
      <path
        d="M6 4l4 4-4 4"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MemoryCard({ memory, onForget, onVerify, index }) {
  const [open, setOpen] = useState(false);

  return (
    <li
      className="enter-x px-3.5 py-2.5 transition-colors duration-200 hover:bg-[var(--surface-2)]"
      style={{ "--i": Math.min(index, 8) }}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex min-w-0 flex-1 items-start gap-1.5 text-left"
          aria-expanded={open}
        >
          <span className="mt-[5px] flex-none text-[var(--ink-3)]">
            <Chevron open={open} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5">
              <span className="truncate text-[12.5px] font-medium">
                {memory.key}
              </span>
              {memory.stale ? (
                <span className="chip chip-warn !px-1.5 !py-0 !text-[10px]">
                  stale
                </span>
              ) : null}
            </span>
            <span className="mono mt-0.5 block truncate text-[11px] text-[var(--ink-2)]">
              {summariseValue(memory.value)}
            </span>
          </span>
        </button>
        <span
          className={`chip !px-2 !py-0 !text-[10px] ${
            CONFIDENCE[memory.confidence_level] ?? ""
          }`}
        >
          {memory.confidence_level}
        </span>
      </div>

      {open ? (
        <div className="enter-sm mt-2.5 space-y-2 border-t border-[var(--line)] pt-2.5">
          <dl className="space-y-1 text-[11px] text-[var(--ink-2)]">
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--ink-3)]">Type</dt>
              <dd className="mono">{memory.type}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--ink-3)]">Verified</dt>
              <dd>{relativeTime(memory.last_verified_at)}</dd>
            </div>
          </dl>

          {memory.conflict ? (
            <p className="rounded-[7px] bg-[var(--warn-bg)] px-2.5 py-1.5 text-[11px] leading-[1.5] text-[var(--warn)]">
              {memory.conflict}
            </p>
          ) : null}

          {memory.reasons?.length ? (
            <p className="text-[11px] leading-[1.5] text-[var(--ink-3)]">
              Used because: {memory.reasons.join("; ")}
            </p>
          ) : null}

          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => onVerify(memory)}
              className="btn btn-ghost !px-2 !py-1 !text-[10px]"
            >
              Still current?
            </button>
            <button
              type="button"
              onClick={() => onForget(memory)}
              className="btn btn-ghost btn-danger !px-2 !py-1 !text-[10px]"
            >
              Forget
            </button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

export function MemoryPanel({ memories, onSend }) {
  const stale = memories.filter((memory) => memory.stale).length;

  return (
    <section className="card flex min-h-0 flex-1 flex-col overflow-hidden">
      <header className="flex flex-none items-center justify-between border-b border-[var(--line)] px-3.5 py-2.5">
        <span className="t-label">Memory</span>
        <span className="text-[11px] text-[var(--ink-3)]">
          {memories.length}
          {stale ? ` · ${stale} stale` : ""}
        </span>
      </header>

      {memories.length === 0 ? (
        <p className="px-3.5 py-3.5 text-[12px] leading-[1.6] text-[var(--ink-3)]">
          Nothing remembered yet. Try &ldquo;Remember that my project is at
          ~/Documents/nexus&rdquo;.
        </p>
      ) : (
        <ul className="scroll min-h-0 flex-1 divide-y divide-[var(--line)]">
          {memories.map((memory, index) => (
            <MemoryCard
              key={memory.id}
              memory={memory}
              index={index}
              onForget={(item) => onSend(`Forget the memory "${item.key}".`)}
              onVerify={(item) =>
                onSend(`Is what you remember about "${item.key}" still current?`)
              }
            />
          ))}
        </ul>
      )}
    </section>
  );
}
