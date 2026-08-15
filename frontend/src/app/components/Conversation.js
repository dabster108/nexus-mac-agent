"use client";

import { useEffect, useRef } from "react";

/**
 * The conversation.
 *
 * NEXUS's answers are shown as plain text with line breaks preserved — the
 * "continue where I left off" reply is several short lines, and collapsing
 * them into a paragraph is what makes an operating environment read like a
 * chatbot.
 */

const SUGGESTIONS = [
  "Continue where I left off.",
  "What am I working on?",
  "What changed recently?",
  "What do you remember?",
];

function Bubble({ message }) {
  const mine = message.role === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={
          mine
            ? "max-w-[80%] rounded-[var(--radius)] bg-[var(--accent-soft)] px-3.5 py-2.5 text-[14px] leading-6 text-[var(--accent)]"
            : "max-w-[85%] whitespace-pre-wrap text-[14px] leading-6 text-[var(--ink)]"
        }
      >
        {message.text}
      </div>
    </div>
  );
}

export function Conversation({ messages, busy, onSend }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-start justify-center gap-5 px-6">
        <div>
          <h2 className="text-[19px] font-medium tracking-tight">
            Good to see you.
          </h2>
          <p className="mt-1 max-w-md text-[14px] leading-6 text-[var(--ink-2)]">
            I can see your workspace, what&rsquo;s running, and what I&rsquo;ve
            been told to remember. Ask me where you left off.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => onSend(suggestion)}
              className="chip hover:border-[var(--ink-3)] hover:text-[var(--ink)]"
            >
              {suggestion}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="scroll flex-1 space-y-5 px-6 py-5">
      {messages.map((message, index) => (
        <Bubble key={`${message.role}-${index}`} message={message} />
      ))}
      {busy ? (
        <div className="pulse flex items-center gap-2 text-[13px] text-[var(--ink-3)]">
          <span className="dot dot-idle" />
          Working
        </div>
      ) : null}
      <div ref={endRef} />
    </div>
  );
}
