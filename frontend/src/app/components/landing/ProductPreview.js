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
 * The content is illustrative and labelled as such in the caption below it;
 * the numbers here are not pretending to be live.
 */

const ROWS = [
  { dot: "dot-danger", title: "Backend stopped unexpectedly", meta: "exit 143 · 2m ago" },
  { dot: "dot-warn", title: "Saved port looks out of date", meta: "8123 → 8199 · 5m ago" },
  { dot: "dot-ok", title: "Frontend recovered", meta: "127.0.0.1:3000 · 9m ago" },
];

const TRACE = [
  ["12:04:11", "context collected", "text-[var(--ink-2)]"],
  ["12:04:11", "tool started", "text-[var(--ink-2)]"],
  ["12:04:12", "permission required", "text-[var(--warn)]"],
  ["12:04:19", "approved", "text-[var(--ok)]"],
  ["12:04:21", "task completed", "text-[var(--ok)]"],
];

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
      setTilt({ x: y * -3.2, y: x * 4.4 });
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
      {/* the glow the panel casts on the page behind it */}
      <div
        aria-hidden
        className="absolute -inset-x-10 -top-6 bottom-0 rounded-[40px] opacity-60 blur-3xl"
        style={{
          background:
            "radial-gradient(60% 50% at 50% 0%, color-mix(in srgb, var(--accent) 30%, transparent), transparent 70%)",
        }}
      />

      <div
        className="relative overflow-hidden rounded-[var(--r-xl)] border border-[var(--line-2)] bg-[var(--bg-1)] shadow-[var(--shadow-lg)]"
        style={{
          transform: `rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
          transformStyle: "preserve-3d",
          transition: "transform 500ms var(--ease)",
        }}
      >
        {/* window chrome */}
        <div className="flex items-center gap-2 border-b border-[var(--line)] bg-[var(--surface)] px-4 py-2.5">
          <span className="flex gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[var(--line-3)]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[var(--line-3)]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[var(--line-3)]" />
          </span>
          <span className="mono mx-auto text-[10.5px] text-[var(--ink-3)]">
            nexus · localhost
          </span>
        </div>

        <div className="grid grid-cols-[132px_1fr] sm:grid-cols-[168px_1fr]">
          {/* sidebar */}
          <div className="hidden border-r border-[var(--line)] bg-[var(--surface)] p-2.5 sm:block">
            <div className="mb-3 flex items-center gap-2 px-1.5">
              <span className="grid h-5 w-5 place-items-center rounded-[6px] bg-[var(--accent)] text-[9px] font-bold text-white">
                N
              </span>
              <span className="text-[11px] font-semibold tracking-[0.1em]">
                NEXUS
              </span>
            </div>
            {["Overview", "Activity", "Memory", "Processes", "Trace"].map(
              (item, index) => (
                <div
                  key={item}
                  className="nav-item !py-1.5 !text-[11px]"
                  data-active={index === 0}
                >
                  <span className="h-1 w-1 rounded-full bg-current opacity-50" />
                  {item}
                </div>
              ),
            )}
          </div>

          {/* workspace */}
          <div className="min-w-0 space-y-2.5 p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[12.5px] font-medium">Good evening</p>
                <p className="text-[10.5px] text-[var(--ink-3)]">
                  distributed-systems-lab · dikshanta
                </p>
              </div>
              <span className="chip chip-ok !text-[9.5px]">
                <span className="dot dot-live" />
                online
              </span>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {[
                ["3", "processes"],
                ["12", "memories"],
                ["2", "to review"],
              ].map(([value, label]) => (
                <div
                  key={label}
                  className="rounded-[9px] border border-[var(--line)] bg-[var(--surface-2)] px-2.5 py-2"
                >
                  <p className="text-[15px] font-medium leading-none tracking-[-0.02em]">
                    {value}
                  </p>
                  <p className="mt-1 text-[9.5px] text-[var(--ink-3)]">{label}</p>
                </div>
              ))}
            </div>

            <div className="rounded-[9px] border border-[var(--line)] bg-[var(--surface-2)] p-2.5">
              <p className="t-label mb-1.5 !text-[9px]">Needs a decision</p>
              <div className="space-y-1.5">
                {ROWS.map((row) => (
                  <div key={row.title} className="flex items-start gap-2">
                    <span className={`dot ${row.dot} mt-[5px]`} />
                    <div className="min-w-0">
                      <p className="truncate text-[10.5px] leading-4">
                        {row.title}
                      </p>
                      <p className="mono text-[9px] text-[var(--ink-3)]">
                        {row.meta}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="mono hidden rounded-[9px] border border-[var(--line)] bg-[var(--surface-2)] p-2.5 text-[9px] leading-[15px] sm:block">
              {TRACE.map(([time, label, tone]) => (
                <div key={time + label} className="flex gap-2">
                  <span className="text-[var(--ink-4)]">{time}</span>
                  <span className={tone}>{label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* a soft sheen across the glass */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "linear-gradient(155deg, color-mix(in srgb, #fff 6%, transparent), transparent 42%)",
          }}
        />
      </div>
    </div>
  );
}
