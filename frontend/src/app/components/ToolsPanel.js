"use client";

import { useState } from "react";
import { groupTools, toolLabel } from "@/lib/tools";

/**
 * What the agent can reach on this Mac — discovered from GET /api/tools.
 *
 * Information only: clicking a row sends an ordinary chat message, never a
 * direct tool call. That keeps the approval path intact for CONFIRM tools.
 */

function PermissionBadge({ permission }) {
  if (permission === "CONFIRM") {
    return (
      <span className="chip chip-warn !px-1.5 !py-0 !text-[10px]">
        approval
      </span>
    );
  }
  if (permission === "RESTRICTED") {
    return (
      <span className="chip !px-1.5 !py-0 !text-[10px] text-[var(--ink-3)]">
        blocked
      </span>
    );
  }
  return (
    <span className="text-[10px] text-[var(--ink-4)]">read-only</span>
  );
}

function Category({ category, defaultOpen, onTry }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border-b border-[var(--line)] last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-[var(--surface-3)]"
      >
        <span className="text-[12.5px] font-medium text-[var(--ink)]">
          {category.label}
        </span>
        <span className="mono text-[11px] text-[var(--ink-3)]">
          {category.items.length}
        </span>
      </button>
      {open ? (
        <ul className="space-y-0.5 px-2 pb-2">
          {category.items.map((tool) => (
            <li key={tool.name}>
              <button
                type="button"
                onClick={() =>
                  onTry?.(
                    `Tell me what ${toolLabel(tool.name)} can do on my Mac and give a short example.`,
                  )
                }
                className="reveal group flex w-full items-start gap-2 rounded-[7px] px-2 py-1.5 text-left hover:bg-[var(--surface-3)]"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-[12.5px] font-medium leading-5">
                    {toolLabel(tool.name)}
                  </p>
                  <p className="mt-0.5 line-clamp-2 text-[11.5px] leading-4 text-[var(--ink-3)]">
                    {tool.description}
                  </p>
                </div>
                <PermissionBadge permission={tool.permission} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function ToolsPanel({ tools = [], state = "ready", onTry }) {
  const groups = groupTools(tools);
  const safe = tools.filter((t) => t.permission === "SAFE").length;
  const confirm = tools.filter((t) => t.permission === "CONFIRM").length;

  return (
    <section className="px-4 py-4">
      <div className="mb-2.5 flex items-baseline justify-between gap-2">
        <h2 className="t-label">Can do on your Mac</h2>
        {tools.length ? (
          <span className="mono text-[11.5px] text-[var(--ink-3)]">
            {tools.length}
          </span>
        ) : null}
      </div>

      {state === "loading" ? (
        <div className="space-y-2" aria-hidden>
          <div className="shimmer h-3 w-3/4" />
          <div className="shimmer h-3 w-1/2" />
        </div>
      ) : null}

      {state === "offline" ? (
        <p className="text-[12.5px] leading-[1.55] text-[var(--ink-3)]">
          Not connected — tool list unavailable until the backend is back.
        </p>
      ) : null}

      {state === "ready" && tools.length === 0 ? (
        <p className="text-[12.5px] leading-[1.55] text-[var(--ink-3)]">
          No Mac tools reported yet. If the MCP server is starting, this fills
          in once it connects.
        </p>
      ) : null}

      {state === "ready" && tools.length > 0 ? (
        <>
          <p className="mb-2.5 text-[12.5px] leading-[1.55] text-[var(--ink-2)]">
            {safe} read-only · {confirm} need your approval before they run
          </p>
          <div className="-mx-2 overflow-hidden rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface)]">
            {groups.map((category, index) => (
              <Category
                key={category.id}
                category={category}
                defaultOpen={index === 0}
                onTry={onTry}
              />
            ))}
          </div>
          <p className="mt-2 text-[11.5px] leading-4 text-[var(--ink-3)]">
            Tap a tool to ask about it. Nothing here runs without going through
            chat{confirm ? " and approval where required" : ""}.
          </p>
        </>
      ) : null}
    </section>
  );
}
