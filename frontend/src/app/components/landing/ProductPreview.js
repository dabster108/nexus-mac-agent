"use client";

import { useEffect, useRef, useState } from "react";

/**
 * The product preview.
 *
 * Built out of the same primitives as the real dashboard rather than a
 * screenshot, so it stays truthful as the product changes and stays crisp at
 * any density. It tilts very slightly towards the pointer — enough to read as
 * a physical object, far short of the spinning-card effect that makes a page
 * feel like a template.
 *
 * It shows the shape of the real interface — a conversation on white, an
 * approval, and a quiet slate rail — because a marketing image of an interface
 * the product does not have is the most expensive kind of lie. The content is
 * illustrative and labelled as such in the caption below it.
 */

const RAIL_NOTICED = [
  { dot: "dot-danger", title: "Backend stopped unexpectedly", meta: "exit 143 · 2m" },
  { dot: "dot-warn", title: "Saved port looks out of date", meta: "8123 → 8199 · 5m" },
  { dot: "dot-ok", title: "Frontend recovered", meta: "127.0.0.1:3000 · 9m" },
];

function Spark({ size = 11 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M8 2.2l1.5 3.9 3.9 1.5-3.9 1.5L8 13l-1.5-3.9L2.6 7.6l3.9-1.5L8 2.2z"
        fill="var(--accent)"
      />
    </svg>
  );
}

export function ProductPreview() {
  const wrapRef = useRef(null);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (window.matchMedia("(pointer: coarse)").matches) return;

    const onMove = (event) => {
      const rect = node.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;
      setTilt({ x: y * -2.4, y: x * 3.4 });
    };
    const onLeave = () => setTilt({ x: 0, y: 0 });

    node.addEventListener("pointermove", onMove);
    node.addEventListener("pointerleave", onLeave);
    return () => {
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  return (
    <div ref={wrapRef} className="relative" style={{ perspective: "1600px" }}>
      <div
        className="relative overflow-hidden rounded-[var(--r-xl)] border border-[var(--line)] bg-[var(--surface)] shadow-[var(--shadow-lg)]"
        style={{
          transform: `rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
          transformStyle: "preserve-3d",
          transition: "transform 500ms var(--ease)",
        }}
      >
        {/* window chrome */}
        <div className="flex items-center gap-2 border-b border-[var(--line)] bg-[var(--bg)] px-4 py-2.5">
          <span className="flex gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[var(--line-2)]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[var(--line-2)]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[var(--line-2)]" />
          </span>
          <span className="mono mx-auto text-[11px] text-[var(--ink-3)]">
            nexus · localhost
          </span>
        </div>

        <div className="grid sm:grid-cols-[1fr_158px]">
          {/* the conversation — the product */}
          <div className="min-w-0 bg-[var(--surface)] p-4">
            <div className="flex justify-end">
              <p className="max-w-[78%] rounded-[10px] rounded-br-[3px] bg-[var(--ink)] px-2.5 py-1.5 text-[11px] leading-[1.5] text-white">
                the api died again, restart it
              </p>
            </div>

            <div className="mt-3 flex gap-2">
              <span className="mt-[1px] grid h-[18px] w-[18px] flex-none place-items-center rounded-[6px] border border-[var(--accent-line)] bg-[var(--accent-bg)]">
                <Spark />
              </span>
              <p className="text-[11px] leading-[1.6] text-[var(--ink)]">
                The backend on port 8123 exited two minutes ago with code 143.
                Restarting it needs your approval.
              </p>
            </div>

            {/* the approval: the one moment NEXUS asks for responsibility */}
            <div className="mt-3 rounded-[9px] border border-[var(--line-2)] bg-[var(--surface)] px-3 py-2.5 shadow-[var(--shadow-sm)]">
              <p className="flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.07em] text-[var(--warn-ink)]">
                <span className="dot dot-warn !h-1.5 !w-1.5" />
                Approval needed
              </p>
              <p className="mt-1 text-[11px] font-semibold leading-4">
                Start the development server in distributed-systems-lab
              </p>
              <div className="mt-2 flex items-center gap-1.5">
                <span className="rounded-[6px] bg-[var(--accent)] px-2.5 py-1 text-[10px] font-semibold text-white">
                  Approve
                </span>
                <span className="rounded-[6px] border border-[var(--line-2)] px-2.5 py-1 text-[10px] font-semibold text-[var(--ink)]">
                  Don&rsquo;t run it
                </span>
                <span className="mono ml-auto text-[9px] text-[var(--ink-3)]">
                  start_process
                </span>
              </div>
            </div>

            {/* multi-step progress, as the real MissionProgress renders it */}
            <div className="mt-2 rounded-[9px] border border-[var(--line)] bg-[var(--surface)] px-3 py-2.5">
              <div className="flex items-baseline justify-between">
                <p className="text-[10.5px] font-semibold">Restart and verify</p>
                <span className="mono text-[9px] text-[var(--ink-3)]">2/3</span>
              </div>
              <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-[var(--surface-3)]">
                <div className="h-full w-2/3 rounded-full bg-[var(--accent)]" />
              </div>
              <div className="mt-1.5 flex items-center gap-1.5">
                <span className="dot dot-ok" />
                <span className="text-[9.5px] text-[var(--ink-2)]">
                  Started · verified on 127.0.0.1:8123
                </span>
              </div>
            </div>
          </div>

          {/* the rail: quiet, slate, and only what it actually knows */}
          <div className="hidden divide-y divide-[var(--line)] border-l border-[var(--line)] bg-[var(--bg)] sm:block">
            <div className="p-3">
              <p className="t-label !text-[9px]">Understands</p>
              <p className="mt-1.5 text-[10.5px] font-semibold leading-4">
                distributed-systems-lab
              </p>
              <p className="mono mt-0.5 text-[9px] text-[var(--ink-3)]">
                dikshanta · 4 changes
              </p>
            </div>

            <div className="p-3">
              <p className="t-label !text-[9px]">Noticed</p>
              <div className="mt-1.5 space-y-1.5">
                {RAIL_NOTICED.map((row) => (
                  <div key={row.title} className="flex items-start gap-1.5">
                    <span className={`dot ${row.dot} mt-[4px]`} />
                    <div className="min-w-0">
                      <p className="text-[9.5px] leading-[13px] text-[var(--ink-2)]">
                        {row.title}
                      </p>
                      <p className="mono text-[8.5px] text-[var(--ink-3)]">
                        {row.meta}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="p-3">
              <p className="t-label !text-[9px]">Remembers</p>
              <p className="mt-1.5 text-[9.5px] font-medium leading-[13px]">
                backend port
              </p>
              <p className="mono text-[9px] text-[var(--ink-2)]">8123</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
