"use client";

import { useState } from "react";
import { relativeTime, summariseValue } from "@/lib/format";

/**
 * What NEXUS remembers, and how much it trusts each item.
 *
 * "Forget" does not call a delete endpoint — there isn't one. It composes the
 * ordinary sentence a user would type, so the request goes through the agent
 * and raises the same approval prompt any deletion raises. The button is a
 * shortcut for typing, not a second route to the same effect.
 */

const CONFIDENCE_STYLE = {
  HIGH: "chip-accent",
  MEDIUM: "",
  LOW: "chip-warn",
};

function MemoryCard({ memory, onForget, onVerify }) {
  const [open, setOpen] = useState(false);

  return (
    <li className="px-3 py-2.5">
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="min-w-0 flex-1 text-left"
          aria-expanded={open}
        >
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[13px] font-medium">{memory.key}</span>
            {memory.stale ? <span className="chip chip-warn">stale</span> : null}
          </div>
          <div className="mono mt-0.5 truncate text-[11px] text-[var(--ink-2)]">
            {summariseValue(memory.value)}
          </div>
        </button>
        <span className={`chip ${CONFIDENCE_STYLE[memory.confidence_level] ?? ""}`}>
          {memory.confidence_level}
        </span>
      </div>

      {open ? (
        <div className="mt-2 space-y-2 border-t border-[var(--line)] pt-2">
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
            <p className="rounded-[6px] bg-[var(--warn-soft)] px-2 py-1.5 text-[11px] text-[var(--warn)]">
              {memory.conflict}
            </p>
          ) : null}

          {memory.reasons?.length ? (
            <p className="text-[11px] text-[var(--ink-3)]">
              Used because: {memory.reasons.join("; ")}
            </p>
          ) : null}

          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => onVerify(memory)}
              className="chip hover:border-[var(--ink-3)]"
            >
              Is this current?
            </button>
            <button
              type="button"
              onClick={() => onForget(memory)}
              className="chip hover:border-[var(--danger)] hover:text-[var(--danger)]"
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
    <section className="panel flex min-h-0 flex-1 flex-col overflow-hidden">
      <header className="flex items-center justify-between border-b border-[var(--line)] px-3 py-2">
        <span className="panel-head">Memory</span>
        <span className="text-[11px] text-[var(--ink-3)]">
          {memories.length}
          {stale ? ` · ${stale} stale` : ""}
        </span>
      </header>

      {memories.length === 0 ? (
        <p className="px-3 py-4 text-[12px] leading-5 text-[var(--ink-3)]">
          Nothing remembered yet. Try &ldquo;Remember that my project is at
          ~/Documents/nexus&rdquo;.
        </p>
      ) : (
        <ul className="scroll min-h-0 flex-1 divide-y divide-[var(--line)]">
          {memories.map((memory) => (
            <MemoryCard
              key={memory.id}
              memory={memory}
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
