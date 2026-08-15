"use client";

import { useNexus } from "@/lib/useNexus";
import { ApprovalBar } from "./components/ApprovalBar";
import { Composer } from "./components/Composer";
import { Conversation } from "./components/Conversation";
import { ContextPanel } from "./components/ContextPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import { Timeline } from "./components/Timeline";

/**
 * The NEXUS control centre.
 *
 * Two columns: what NEXUS can see on the left, the conversation on the right.
 * The sidebar is the point — an assistant that claims to understand your
 * environment should be able to show you what it thinks that environment is,
 * so the same facts that reached the model are on screen next to its answers.
 */

function StatusDot({ online }) {
  if (online === null) {
    return (
      <span className="chip">
        <span className="dot dot-idle" />
        connecting
      </span>
    );
  }
  return online ? (
    <span className="chip">
      <span className="dot dot-ok" />
      online
    </span>
  ) : (
    <span className="chip chip-warn">
      <span className="dot dot-danger" />
      backend unreachable
    </span>
  );
}

export default function Home() {
  const {
    online,
    context,
    memories,
    events,
    messages,
    pending,
    busy,
    error,
    send,
    decide,
    stop,
  } = useNexus();

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-[var(--line)] px-4 py-2.5">
        <div className="flex items-baseline gap-2">
          <span className="text-[14px] font-semibold tracking-[0.14em]">NEXUS</span>
          <span className="text-[11px] text-[var(--ink-3)]">
            AI operating layer
          </span>
        </div>
        <StatusDot online={online} />
      </header>

      <div className="flex min-h-0 flex-1 gap-3 p-3">
        <aside className="flex w-[290px] flex-none flex-col gap-3">
          <ContextPanel context={context} />
          <MemoryPanel memories={memories} onSend={send} />
          <Timeline events={events} />
        </aside>

        <main className="panel flex min-w-0 flex-1 flex-col overflow-hidden">
          <Conversation messages={messages} busy={busy} onSend={send} />

          {error ? (
            <p className="border-t border-[var(--line)] px-4 py-2 text-[12px] text-[var(--danger)]">
              {error}
            </p>
          ) : null}

          <ApprovalBar requests={pending} onDecide={decide} />
          <Composer busy={busy} onSend={send} onStop={stop} />
        </main>
      </div>
    </div>
  );
}
