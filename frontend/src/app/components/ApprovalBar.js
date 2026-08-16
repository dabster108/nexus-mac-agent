"use client";

/**
 * The approval prompt.
 *
 * Deliberately the loudest thing on screen, and deliberately un-dismissable
 * except by deciding: a run is blocked on this, and a CONFIRM tool is the one
 * moment NEXUS asks a person to take responsibility.
 *
 * The arguments are shown in full. Approving something described only as "run
 * a command" is not consent, so the dialog spends its space on exactly what
 * will happen rather than on styling.
 */

function Argument({ name, value }) {
  return (
    <div className="flex gap-2 text-[11px] leading-5">
      <span className="text-[var(--ink-3)]">{name}</span>
      <span className="mono min-w-0 flex-1 break-all text-[var(--ink)]">
        {typeof value === "object" ? JSON.stringify(value) : String(value)}
      </span>
    </div>
  );
}

export function ApprovalBar({ requests, onDecide }) {
  if (!requests.length) return null;

  return (
    <div className="border-t border-[var(--warn)]/25 bg-[var(--warn-bg)]">
      {requests.map((request, index) => (
        <div
          key={request.request_id}
          className="enter-pop px-5 py-3.5"
          style={{ "--i": index }}
        >
          <div className="flex items-center gap-2">
            <span className="dot dot-warn thinking-dot" />
            <span className="t-label text-[var(--warn)]">
              Waiting for you
            </span>
          </div>

          <p className="mt-1.5 text-[14px] leading-6 text-[var(--ink)]">
            {request.description}
          </p>

          {request.arguments && Object.keys(request.arguments).length ? (
            <div className="mt-2 space-y-0.5 rounded-[8px] border border-[var(--warn)]/20 bg-[var(--surface)]/60 px-2.5 py-2">
              {Object.entries(request.arguments).map(([name, value]) => (
                <Argument key={name} name={name} value={value} />
              ))}
            </div>
          ) : null}

          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              onClick={() => onDecide(request.request_id, "approve")}
              className="btn btn-primary"
            >
              Approve
            </button>
            <button
              type="button"
              onClick={() => onDecide(request.request_id, "deny")}
              className="btn btn-ghost btn-danger"
            >
              Deny
            </button>
            <span className="mono ml-auto text-[10px] text-[var(--ink-3)]">
              {request.tool}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
