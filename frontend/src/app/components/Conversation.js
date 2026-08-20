"use client";

import { useEffect, useRef } from "react";
import { clockTime } from "@/lib/format";
import { MissionProgress } from "./MissionProgress";
import { OutcomeCard } from "./OutcomeCard";
import { TracePanel } from "./TracePanel";

/**
 * The conversation. This is the product.
 *
 * Assistant turns are unbubbled — they are the page's content, not quoted
 * speech — and carry a small blue mark so the eye finds where an answer
 * begins. The user's turns are contained in navy. That asymmetry does more for
 * legibility than styling both of them would.
 *
 * A container appears only when there is a real object to contain: a mission's
 * progress, a verified outcome, an explanation. An ordinary answer is just
 * text, because wrapping every reply in a card is what makes a product feel
 * like a dashboard.
 */

const OPENERS = [
  { label: "Continue where I left off", hint: "picks up your last session" },
  { label: "What am I working on?", hint: "workspace, branch, processes" },
  { label: "What changed recently?", hint: "reads your git history" },
  { label: "What happened?", hint: "anything NEXUS noticed" },
];

/** The assistant's mark: small, blue, and the same every time. */
function Mark() {
  return (
    <span
      aria-hidden
      className="mt-[3px] grid h-[22px] w-[22px] flex-none place-items-center rounded-[7px] border border-[var(--accent-line)] bg-[var(--accent-bg)]"
    >
      <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
        <path
          d="M8 2.2l1.5 3.9 3.9 1.5-3.9 1.5L8 13l-1.5-3.9L2.6 7.6l3.9-1.5L8 2.2z"
          fill="var(--accent)"
        />
      </svg>
    </span>
  );
}

/** Minimal inline markdown: bold, code, and nothing else. */
function RichText({ text }) {
  const parts = String(text ?? "").split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={index} className="font-semibold text-[var(--ink)]">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={index}
          className="mono rounded-[5px] border border-[var(--line)] bg-[var(--surface-2)] px-1.5 py-[1px] text-[0.86em] text-[var(--ink)]"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

/** Preserves the short-line shape of a "continue where I left off" answer. */
function Answer({ text }) {
  const blocks = String(text ?? "").split(/\n{2,}/);
  return blocks.map((block, index) => {
    const lines = block.split("\n");
    const bulleted = lines.every((l) => /^\s*[-*•]\s+/.test(l)) && lines.length > 1;
    if (bulleted) {
      return (
        <ul key={index} className="my-2.5 space-y-1.5">
          {lines.map((line, i) => (
            <li key={i} className="flex gap-2.5">
              <span
                aria-hidden
                className="mt-[10px] h-[3px] w-[3px] flex-none rounded-full bg-[var(--line-3)]"
              />
              <span>
                <RichText text={line.replace(/^\s*[-*•]\s+/, "")} />
              </span>
            </li>
          ))}
        </ul>
      );
    }
    return (
      <p key={index} className={index ? "mt-3.5" : undefined}>
        <RichText text={block} />
      </p>
    );
  });
}

function Turn({ message, outcomes, mission, onSend, index }) {
  const stagger = { "--i": Math.min(index, 5) };
  const time = clockTime(message.at);

  if (message.role === "user") {
    return (
      <div className="enter flex flex-col items-end gap-1" style={stagger}>
        <div className="max-w-[80%] rounded-[14px] rounded-br-[4px] bg-[var(--ink)] px-4 py-2.5 text-[15px] leading-[1.6] text-white">
          {message.text}
        </div>
        {time ? (
          <span className="mono px-1 text-[11.5px] text-[var(--ink-3)]">{time}</span>
        ) : null}
      </div>
    );
  }

  const forThisTurn = outcomes[message.taskId] ?? [];
  const missionHere = mission?.taskId === message.taskId ? mission : null;

  return (
    <div className="enter flex gap-3" style={stagger}>
      <Mark />

      <div className="min-w-0 flex-1">
        <div className="max-w-[68ch] text-[15px] leading-[1.72] text-[var(--ink)]">
          <Answer text={message.text} />
        </div>

        {missionHere ? (
          <div className="mt-4 max-w-[68ch]">
            <MissionProgress mission={missionHere} />
          </div>
        ) : null}

        {forThisTurn.length ? (
          <div className="mt-3.5 max-w-[68ch] space-y-2">
            {forThisTurn.map((verification, i) => (
              <OutcomeCard key={i} verification={verification} onSend={onSend} />
            ))}
          </div>
        ) : null}

        <div className="mt-2.5 max-w-[68ch]">
          {message.taskId ? (
            <TracePanel taskId={message.taskId} time={time} />
          ) : time ? (
            <span className="mono text-[11.5px] text-[var(--ink-3)]">{time}</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Working({ label }) {
  return (
    <div className="enter-fade flex gap-3" role="status">
      <Mark />
      <div className="flex items-center gap-2.5 pt-[3px]">
        <span aria-hidden className="flex gap-1">
          <span className="thinking-dot dot dot-accent" />
          <span className="thinking-dot dot dot-accent" />
          <span className="thinking-dot dot dot-accent" />
        </span>
        <span className="text-[13px] text-[var(--ink-2)]">{label}</span>
      </div>
    </div>
  );
}

function Welcome({ onSend }) {
  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col justify-center px-6 py-10">
      <span
        aria-hidden
        className="enter grid h-11 w-11 place-items-center rounded-[13px] border border-[var(--accent-line)] bg-[var(--accent-bg)]"
        style={{ "--i": 0 }}
      >
        <svg width="20" height="20" viewBox="0 0 16 16" fill="none">
          <path
            d="M8 2.2l1.5 3.9 3.9 1.5-3.9 1.5L8 13l-1.5-3.9L2.6 7.6l3.9-1.5L8 2.2z"
            fill="var(--accent)"
          />
        </svg>
      </span>

      <h1 className="enter t-h1 mt-6" style={{ "--i": 1 }}>
        What can I help you with?
      </h1>
      <p
        className="enter t-body mt-3 max-w-lg"
        style={{ "--i": 2 }}
      >
        I can see your workspace, what&rsquo;s running, and what I&rsquo;ve been
        told to remember. Ask me anything about this Mac — I&rsquo;ll check
        before I answer, and ask before I change anything.
      </p>

      <div className="mt-9 grid w-full gap-2 sm:grid-cols-2">
        {OPENERS.map((item, index) => (
          <button
            key={item.label}
            type="button"
            onClick={() => onSend(item.label)}
            style={{ "--i": index + 3 }}
            className="enter lift rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface)] px-4 py-3.5 text-left"
          >
            <span className="block text-[14px] font-medium leading-5">
              {item.label}
            </span>
            <span className="mt-1 block text-[12.5px] leading-4 text-[var(--ink-3)]">
              {item.hint}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function Conversation({
  messages,
  busy,
  outcomes = {},
  mission = null,
  workingLabel = "Thinking",
  onSend,
}) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 overflow-hidden">
        <Welcome onSend={onSend} />
      </div>
    );
  }

  return (
    <div className="scroll flex-1">
      <div className="mx-auto max-w-3xl space-y-7 px-6 py-8">
        {messages.map((message, index) => (
          <Turn
            key={`${message.role}-${index}`}
            message={message}
            index={index}
            outcomes={outcomes}
            mission={mission}
            onSend={onSend}
          />
        ))}
        {busy ? <Working label={workingLabel} /> : null}
        <div ref={endRef} />
      </div>
    </div>
  );
}
