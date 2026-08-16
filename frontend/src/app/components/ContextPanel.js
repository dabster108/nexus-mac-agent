"use client";

import { basename, shortenPath } from "@/lib/format";

/**
 * Where the user is, what is running, and what machine this is.
 *
 * Every value comes from `/api/context`, gathered through SAFE tools. Nothing
 * here is placeholder text: when a field is unknown the panel says so rather
 * than showing a plausible default, because a status panel that guesses is
 * worse than one that admits it cannot see.
 */

function Row({ label, children }) {
  return (
    <div className="px-3.5 py-3">
      <div className="t-label mb-1.5">{label}</div>
      <div className="text-[13px] leading-5 text-[var(--ink)]">{children}</div>
    </div>
  );
}

function Unknown({ children }) {
  return <span className="text-[13px] text-[var(--ink-3)]">{children}</span>;
}

function Skeleton() {
  return (
    <section className="card overflow-hidden">
      <header className="border-b border-[var(--line)] px-3.5 py-2.5">
        <span className="t-label">Workspace</span>
      </header>
      <div className="space-y-2.5 p-3.5">
        <div className="shimmer h-3 w-2/3 rounded" />
        <div className="shimmer h-2.5 w-full rounded" />
        <div className="shimmer h-2.5 w-1/2 rounded" />
      </div>
    </section>
  );
}

export function ContextPanel({ context }) {
  if (!context) return <Skeleton />;

  const workspace = context.active_workspace;
  const processes = context.processes ?? [];
  const machine = context.machine;

  return (
    <section className="card overflow-hidden">
      <header className="flex items-center justify-between border-b border-[var(--line)] px-3.5 py-2.5">
        <span className="t-label">Workspace</span>
        {workspace?.verified ? (
          <span className="chip chip-accent">active</span>
        ) : null}
      </header>

      <div className="divide-y divide-[var(--line)]">
        {workspace ? (
          <>
            <Row label="Project">
              <div className="font-medium">{basename(workspace.path)}</div>
              <div className="mono mt-0.5 truncate text-[11px] text-[var(--ink-3)]">
                {shortenPath(workspace.path)}
              </div>
              {workspace.project_types?.length ? (
                <div className="mt-2 flex flex-wrap gap-1">
                  {workspace.project_types.slice(0, 4).map((type, index) => (
                    <span
                      key={type}
                      className="chip enter-sm"
                      style={{ "--i": index }}
                    >
                      {type}
                    </span>
                  ))}
                </div>
              ) : null}
            </Row>

            {workspace.is_git_repository ? (
              <Row label="Branch">
                <div className="flex items-center justify-between gap-2">
                  <span className="mono truncate">
                    {workspace.git_branch ?? "—"}
                  </span>
                  <span
                    className={`chip ${workspace.git_clean ? "chip-ok" : ""}`}
                  >
                    {workspace.git_clean
                      ? "clean"
                      : `${workspace.changed_files ?? "some"} changed`}
                  </span>
                </div>
              </Row>
            ) : null}
          </>
        ) : (
          <Row label="Project">
            <Unknown>
              No workspace established yet. Mention a path, or ask NEXUS to
              remember where a project lives.
            </Unknown>
          </Row>
        )}

        <Row label="Processes">
          {processes.length === 0 ? (
            <Unknown>None running</Unknown>
          ) : (
            <ul className="space-y-2">
              {processes.map((process, index) => {
                const live = process.status === "RUNNING";
                return (
                  <li
                    key={process.process_id}
                    className="enter-sm flex items-center gap-2"
                    style={{ "--i": index }}
                  >
                    <span className={`dot ${live ? "dot-live" : "dot-idle"}`} />
                    <span className="truncate text-[12px]">{process.name}</span>
                    {process.port ? (
                      <span className="mono ml-auto text-[11px] text-[var(--ink-3)]">
                        :{process.port}
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </Row>

        <Row label="System">
          {machine ? (
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px]">
                {machine.platform} {machine.architecture}
              </span>
              {machine.battery_percentage != null ? (
                <span className="chip">
                  {machine.battery_percentage}%
                  {machine.charging ? " charging" : ""}
                </span>
              ) : null}
            </div>
          ) : (
            <Unknown>Not inspected for this request</Unknown>
          )}
        </Row>
      </div>
    </section>
  );
}
