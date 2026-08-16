"use client";

import { useEffect, useRef } from "react";
import { OutcomeCard } from "./OutcomeCard";

/**
 * The conversation.
 *
 * NEXUS's answers keep their line breaks. The "continue where I left off"
 * reply is several short lines by design, and flattening it into a paragraph
 * is precisely what makes an operating environment read like a chatbot.
 *
 * The assistant's turns are unbubbled — they are the page's content, not
 * quoted speech — while the user's are contained. That asymmetry does more for
 * legibility than any amount of styling on either.
 */

const SUGGESTIONS = [
  { label: "Continue where I left off", hint: "picks up your last session" },
  { label: "What am I working on?", hint: "workspace, branch, processes" },
  { label: "What changed recently?", hint: "reads your git history" },
  { label: "What happened?", hint: "anything NEXUS noticed" },
];

/** Renders **bold** and `code` without pulling in a markdown dependency. */
function RichText({ text }) {
  const parts = String(text ?? "").split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={index} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={index}
          className="mono rounded-[5px] bg-[var(--surface-2)] px-1.5 py-0.5 text-[0.9em] text-[var(--ink)]"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

function Turn({ message, index }) {
  const mine = message.role === "user";

  if (mine) {
    return (
      <div className="enter flex justify-end" style={{ "--i": Math.min(index, 6) }}>
        <div className="max-w-[78%] rounded-[14px] rounded-br-[4px] bg-[var(--accent-bg)] px-4 py-2.5 text-[14px] leading-6 text-[var(--accent-ink)]">
          {message.text}
        </div>
      </div>
    );
  }

  return (
    <div className="enter flex gap-3" style={{ "--i": Math.min(index, 6) }}>
      <span
        aria-hidden
        className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-[var(--accent)]"
      />
      <div className="min-w-0 whitespace-pre-wrap text-[14px] leading-[1.7] text-[var(--ink)]">
        <RichText text={message.text} />
      </div>
    </div>
  );
}

function Working() {
  return (
    <div className="enter-fade flex items-center gap-2.5 pl-[18px]">
      <span className="flex gap-1">
        <span className="thinking-dot dot dot-idle" />
        <span className="thinking-dot dot dot-idle" />
        <span className="thinking-dot dot dot-idle" />
      </span>
      <span className="text-[12px] text-[var(--ink-3)]">working</span>
    </div>
  );
}

function Empty({ onSend }) {
  return (
    <div className="flex flex-1 flex-col items-start justify-center gap-6 px-8">
      <div className="enter" style={{ "--i": 0 }}>
        <h2 className="text-[22px] font-medium tracking-[-0.01em]">
          Good to see you.
        </h2>
        <p className="mt-1.5 max-w-md text-[14px] leading-[1.7] text-[var(--ink-2)]">
          I can see your workspace, what&rsquo;s running, and what I&rsquo;ve
          been told to remember. Ask me where you left off.
        </p>
      </div>

      <div className="grid w-full max-w-lg gap-1.5 sm:grid-cols-2">
        {SUGGESTIONS.map((item, index) => (
          <button
            key={item.label}
            type="button"
            onClick={() => onSend(item.label)}
            style={{ "--i": index + 1 }}
            className="enter lift group rounded-[10px] border border-[var(--line)] bg-[var(--surface)] px-3.5 py-2.5 text-left"
          >
            <span className="block text-[13px] font-medium text-[var(--ink)]">
              {item.label}
            </span>
            <span className="mt-0.5 block text-[11px] text-[var(--ink-3)]">
              {item.hint}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function Conversation({ messages, busy, onSend, verifications = [] }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  if (messages.length === 0) {
    return <Empty onSend={onSend} />;
  }

  return (
    <div className="scroll flex-1 space-y-6 px-6 py-6">
      {messages.map((message, index) => (
        <Turn key={`${message.role}-${index}`} message={message} index={index} />
      ))}

      {verifications.length > 0 ? (
        <div className="space-y-2 pl-[18px]">
          {verifications.slice(-3).map((verification, index) => (
            <OutcomeCard
              key={`${verification.taskId}-${verification.tool}-${index}`}
              verification={verification}
              onSend={onSend}
            />
          ))}
        </div>
      ) : null}

      {busy ? <Working /> : null}
      <div ref={endRef} />
    </div>
  );
}
