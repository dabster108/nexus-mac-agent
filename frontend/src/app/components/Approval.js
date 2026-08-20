"use client";

import { useEffect, useRef } from "react";

/**
 * The approval request.
 *
 * This is the one moment NEXUS asks a person to take responsibility, so it is
 * deliberately the strongest thing on screen while it is open: the composer
 * is replaced rather than merely outranked, focus moves to it, and it cannot
 * be dismissed by anything except deciding.
 *
 * Important, not alarming. There is no red panel and no warning stripe — the
 * weight comes from position and focus. What makes it serious is the sentence
 * naming the consequence and the arguments printed in full.
 *
 * It states what will happen in the backend's own terms and adds nothing.
 * Writing "this is safe" here would be the frontend inventing a guarantee the
 * runtime does not make.
 */

function Argument({ name, value }) {
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return (
    <div className="flex gap-3 py-[3px] text-[12.5px] leading-[1.5]">
      <dt className="w-28 flex-none text-[var(--ink-3)]">{name}</dt>
      <dd className="mono min-w-0 flex-1 break-all text-[var(--ink)]">{text}</dd>
    </div>
  );
}

export function Approval({ request, onDecide }) {
  const approveRef = useRef(null);

  // Focus the decision, not the page. Someone who has just been interrupted
  // should be able to answer from the keyboard without hunting for it.
  useEffect(() => {
    approveRef.current?.focus();
  }, [request.request_id]);

  const args = request.arguments ?? {};
  const hasArgs = Object.keys(args).length > 0;

  return (
    <section
      role="alertdialog"
      aria-modal="false"
      aria-labelledby="approval-title"
      aria-describedby="approval-body"
      className="enter-pop border-t border-[var(--line)] bg-[var(--surface)] px-4 py-4 sm:px-6"
    >
      <div className="mx-auto max-w-2xl rounded-[var(--r-lg)] border border-[var(--line-2)] bg-[var(--surface)] px-5 py-4 shadow-[var(--shadow-md)]">
        <p className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.07em] text-[var(--warn-ink)]">
          <span aria-hidden className="dot dot-warn" />
          Approval needed
        </p>

        <h2 id="approval-title" className="t-h2 mt-2.5">
          {request.description}
        </h2>

        <p
          id="approval-body"
          className="mt-1.5 text-[13.5px] leading-[1.6] text-[var(--ink-2)]"
        >
          This changes something on your Mac. NEXUS cannot run it without your
          approval, and will not ask again for this request if you decline.
        </p>

        {hasArgs ? (
          <dl className="mt-3 rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface-2)] px-3.5 py-2.5">
            {Object.entries(args).map(([name, value]) => (
              <Argument key={name} name={name} value={value} />
            ))}
          </dl>
        ) : null}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            ref={approveRef}
            type="button"
            onClick={() => onDecide(request.request_id, "approve")}
            className="btn btn-primary btn-lg"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={() => onDecide(request.request_id, "deny")}
            className="btn btn-ghost btn-lg"
          >
            Don&rsquo;t run it
          </button>
          <span className="mono ml-auto text-[11.5px] text-[var(--ink-3)]">
            {request.tool}
          </span>
        </div>
      </div>
    </section>
  );
}

export function ApprovalStack({ requests, onDecide }) {
  if (!requests.length) return null;
  // One decision at a time: stacking them invites answering the wrong one.
  return <Approval request={requests[0]} onDecide={onDecide} />;
}
