"use client";

import { useEffect, useRef, useState } from "react";

/**
 * The input.
 *
 * Enter sends, Shift+Enter breaks a line, and the box grows to a ceiling and
 * then scrolls. While a task runs the send button becomes Stop — cancellation
 * already exists in the backend and is exactly what someone reaches for when a
 * run takes longer than they expected.
 */

const MAX_HEIGHT = 168;

function SendIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M8 13V3M8 3L3.5 7.5M8 3l4.5 4.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="4.5" y="4.5" width="7" height="7" rx="1.5" fill="currentColor" />
    </svg>
  );
}

export function Composer({ busy, onSend, onStop }) {
  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const area = useRef(null);

  useEffect(() => {
    const node = area.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

  const submit = () => {
    if (busy || !text.trim()) return;
    onSend(text);
    setText("");
  };

  return (
    <div className="composer-shell border-t border-[var(--line)] px-4 py-3 sm:px-6">
      <div
        className="composer-input mx-auto flex max-w-3xl items-end gap-2 rounded-[var(--r-xl)] border bg-[var(--surface)] px-3.5 py-2.5 transition-[border-color,box-shadow] duration-200"
        style={{
          borderColor: focused ? "var(--accent)" : "var(--line-2)",
          boxShadow: focused ? "var(--ring)" : "none",
        }}
      >
        <textarea
          ref={area}
          rows={1}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder="Ask NEXUS.ai…"
          aria-label="Message NEXUS.ai"
          className="scroll max-h-[168px] flex-1 resize-none bg-transparent text-[15px] leading-[1.6] outline-none placeholder:text-[var(--ink-3)] focus-visible:outline-none"
        />

        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="btn btn-ghost btn-danger enter-fade btn-sm"
          >
            <StopIcon />
            Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!text.trim()}
            aria-label="Send"
            className="btn btn-primary btn-sm"
          >
            <SendIcon />
            Send
          </button>
        )}
      </div>

      <p className="mx-auto mt-2 max-w-3xl px-1 text-[11.5px] text-[var(--ink-3)]">
        Enter to send · Shift + Enter for a new line
      </p>
    </div>
  );
}
