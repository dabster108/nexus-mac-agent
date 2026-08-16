"use client";

import Link from "next/link";

/**
 * The application sidebar.
 *
 * Deliberately missing the things a hosted product would put here: there is no
 * account menu, no billing, no workspace switcher. NEXUS runs as you, on your
 * machine, and the "workspace" is whichever project it detected — shown here
 * as state, not as a dropdown that implies a choice you don't have.
 *
 * Sections are views over one live connection rather than separate pages, so
 * switching is instant and nothing refetches.
 */

const ICONS = {
  overview: (
    <path d="M2.5 8.5L8 3l5.5 5.5M4 7.5V13h8V7.5" strokeLinecap="round" strokeLinejoin="round" />
  ),
  activity: (
    <path d="M2 8h2.5l2-4.5L9.5 12l2-4h2.5" strokeLinecap="round" strokeLinejoin="round" />
  ),
  memory: (
    <path
      d="M8 2.5c-2 0-3.5 1.4-3.5 3.2 0 .8.3 1.5.8 2-.5.5-.8 1.2-.8 2C4.5 11.6 6 13 8 13s3.5-1.4 3.5-3.3c0-.8-.3-1.5-.8-2 .5-.5.8-1.2.8-2C11.5 3.9 10 2.5 8 2.5zM8 2.5V13"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  ),
  processes: (
    <path
      d="M3 4.5h10M3 8h10M3 11.5h10"
      strokeLinecap="round"
    />
  ),
  trace: (
    <path
      d="M4 3v9.5M4 12.5h8.5M6.5 10V7M9 10V4.5M11.5 10V8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  ),
};

function Icon({ name }) {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden
      className="flex-none opacity-80"
    >
      {ICONS[name]}
    </svg>
  );
}

export const SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "activity", label: "Activity" },
  { id: "memory", label: "Memory" },
  { id: "processes", label: "Processes" },
  { id: "trace", label: "Trace" },
];

export function SidebarContent({ view, onView, counts, workspace, online, onNavigate }) {
  return (
    <>
      <div className="flex items-center justify-between px-2 pb-4">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="grid h-7 w-7 place-items-center rounded-[8px] bg-gradient-to-b from-[var(--accent-2)] to-[var(--accent)] text-[12px] font-bold text-white">
            N
          </span>
          <span className="text-[13px] font-semibold tracking-[0.16em]">
            NEXUS
          </span>
        </Link>
        <span
          className={`dot ${online ? "dot-live" : "dot-danger"}`}
          title={online ? "connected" : "backend unreachable"}
        />
      </div>

      {/* Workspace as state, not as a switcher. */}
      <div className="mb-4 rounded-[10px] border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2.5">
        <p className="t-label !text-[9px]">Workspace</p>
        {workspace ? (
          <>
            <p className="mt-1 truncate text-[12.5px] font-medium">
              {workspace.name}
            </p>
            <p className="mono mt-0.5 flex items-center gap-1.5 truncate text-[10px] text-[var(--ink-3)]">
              {workspace.branch ? (
                <>
                  <span className="truncate">{workspace.branch}</span>
                  {workspace.changed ? (
                    <span className="text-[var(--warn)]">
                      +{workspace.changed}
                    </span>
                  ) : null}
                </>
              ) : (
                workspace.path
              )}
            </p>
          </>
        ) : (
          <p className="mt-1 text-[11.5px] leading-4 text-[var(--ink-3)]">
            Not established yet
          </p>
        )}
      </div>

      <nav className="space-y-0.5">
        {SECTIONS.map((section) => (
          <button
            key={section.id}
            type="button"
            onClick={() => {
              onView(section.id);
              onNavigate?.();
            }}
            data-active={view === section.id}
            className="nav-item w-full text-left"
          >
            <Icon name={section.id} />
            <span className="flex-1">{section.label}</span>
            {counts[section.id] ? (
              <span className="chip !px-1.5 !py-0 !text-[10px]">
                {counts[section.id]}
              </span>
            ) : null}
          </button>
        ))}
      </nav>

      <div className="mt-auto space-y-2 pt-4">
        <div className="rounded-[10px] border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2.5">
          <p className="t-label !text-[9px]">Session</p>
          <p className="mt-1 text-[11.5px] leading-[1.5] text-[var(--ink-3)]">
            Local · no account. Memory persists on this Mac.
          </p>
        </div>
      </div>
    </>
  );
}

export function Sidebar(props) {
  return (
    <aside className="relative hidden w-[236px] flex-none flex-col border-r border-[var(--line)] bg-[var(--bg-1)] p-3 lg:flex">
      {/* the sidebar's share of the aurora, very faint */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          background:
            "radial-gradient(30rem 18rem at 0% 0%, color-mix(in srgb, var(--accent) 12%, transparent), transparent 70%)",
        }}
      />
      <div className="relative flex min-h-0 flex-1 flex-col">
        <SidebarContent {...props} />
      </div>
    </aside>
  );
}
