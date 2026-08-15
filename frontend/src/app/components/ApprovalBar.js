"use client";

/**
 * The approval prompt.
 *
 * Deliberately the loudest thing on the screen and deliberately un-dismissable
 * except by deciding: a run is blocked waiting for this, and a CONFIRM tool is
 * the one moment NEXUS asks a person to take responsibility. The arguments are
 * shown in full — approving something described only as "run a command" is not
 * consent.
 */

export function ApprovalBar({ requests, onDecide }) {
  if (!requests.length) return null;

  return (
    <div className="space-y-2 border-t border-[var(--line)] bg-[var(--warn-soft)] px-4 py-3">
      {requests.map((request) => (
        <div
          key={request.request_id}
          className="flex flex-wrap items-center justify-between gap-3"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="dot dot-warn" />
              <span className="panel-head text-[var(--warn)]">
                Approval needed
              </span>
            </div>
            <p className="mt-1 text-[13px] leading-5 text-[var(--ink)]">
              {request.description}
            </p>
            <p className="mono mt-0.5 text-[11px] text-[var(--ink-3)]">
              {request.tool}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => onDecide(request.request_id, "deny")}
              className="rounded-[7px] border border-[var(--line-strong)] px-3 py-1.5 text-[13px] text-[var(--ink-2)] hover:border-[var(--danger)] hover:text-[var(--danger)]"
            >
              Deny
            </button>
            <button
              type="button"
              onClick={() => onDecide(request.request_id, "approve")}
              className="rounded-[7px] bg-[var(--ink)] px-3 py-1.5 text-[13px] text-[var(--bg)] hover:opacity-90"
            >
              Approve
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
