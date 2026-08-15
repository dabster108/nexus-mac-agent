"use client";

import { basename, shortenPath } from "@/lib/format";

/**
 * Where the user is, what is running, and what machine this is.
 *
 * Every value comes from `/api/context`, which is gathered through SAFE tools.
 * Nothing here is placeholder text: when a field is unknown the panel says so
 * rather than showing a plausible default, because a status panel that guesses
 * is worse than one that admits it cannot see.
 */

function Row({ label, children }) {
  return (
    <div className="px-3 py-2.5">
      <div className="panel-head mb-1">{label}</div>
      <div className="text-[13px] leading-5 text-[var(--ink)]">{children}</div>
    </div>
  );
}

function Unknown({ children }) {
  return <span className="text-[var(--ink-3)]">{children}</span>;
}

export function ContextPanel({ context }) {
  const workspace = context?.active_workspace;
  const processes = context?.processes ?? [];
  const machine = context?.machine;

  return (
    <section className="panel flex flex-col overflow-hidden">
      <header className="flex items-center justify-between border-b border-[var(--line)] px-3 py-2">
        <span className="panel-head">Workspace</span>
        {workspace?.verified ? (
          <span className="chip chip-accent">active</span>
        ) : null}
      </header>

      <div className="divide-y divide-[var(--line)]">
        {workspace ? (
          <>
            <Row label="Project">
              <div className="font-medium">{basename(workspace.path)}</div>
              <div className="mono mt-0.5 text-[11px] text-[var(--ink-3)]">
                {shortenPath(workspace.path)}
              </div>
              {workspace.project_types?.length ? (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {workspace.project_types.map((type) => (
                    <span key={type} className="chip">
                      {type}
                    </span>
                  ))}
                </div>
              ) : null}
            </Row>

            {workspace.is_git_repository ? (
              <Row label="Branch">
                <div className="flex items-center justify-between gap-2">
                  <span className="mono">{workspace.git_branch ?? "—"}</span>
                  <span className="chip">
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
            <ul className="space-y-1.5">
              {processes.map((process) => (
                <li key={process.process_id} className="flex items-center gap-2">
                  <span
                    className={`dot ${
                      process.status === "RUNNING" ? "dot-ok" : "dot-idle"
                    }`}
                  />
                  <span className="truncate">{process.name}</span>
                  {process.port ? (
                    <span className="mono ml-auto text-[11px] text-[var(--ink-3)]">
                      :{process.port}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Row>

        <Row label="System">
          {machine ? (
            <div className="flex items-center justify-between gap-2">
              <span>
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
