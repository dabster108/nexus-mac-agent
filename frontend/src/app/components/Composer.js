"use client";

import { useEffect, useRef, useState } from "react";

/**
 * The input.
 *
 * Enter sends, Shift+Enter breaks a line, and the box grows with the message.
 * While a task is running the send button becomes Stop — cancellation already
 * exists in the backend and is exactly what someone reaches for when a run is
 * taking longer than they expected.
 */

const MAX_HEIGHT = 160;

export function Composer({ busy, onSend, onStop }) {
  const [text, setText] = useState("");
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
    <div className="border-t border-[var(--line)] px-4 py-3">
      <div className="flex items-end gap-2 rounded-[var(--radius)] border border-[var(--line-strong)] bg-[var(--panel)] px-3 py-2 focus-within:border-[var(--ink-3)]">
        <textarea
          ref={area}
          rows={1}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder="Ask NEXUS…"
          aria-label="Message NEXUS"
          className="max-h-40 flex-1 resize-none bg-transparent text-[14px] leading-6 outline-none placeholder:text-[var(--ink-3)]"
        />
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="rounded-[7px] border border-[var(--line-strong)] px-3 py-1.5 text-[13px] text-[var(--ink-2)] hover:border-[var(--danger)] hover:text-[var(--danger)]"
          >
            Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!text.trim()}
            className="rounded-[7px] bg-[var(--ink)] px-3 py-1.5 text-[13px] text-[var(--bg)] disabled:opacity-30"
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}
