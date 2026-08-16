import Link from "next/link";
import { AuroraCanvas } from "./components/landing/AuroraCanvas";
import { ProductPreview } from "./components/landing/ProductPreview";
import { Reveal } from "./components/landing/Reveal";

/**
 * The landing page.
 *
 * NEXUS is a local, single-user tool, so this page makes the argument a local
 * tool actually has — it runs on your machine, it can see your work, and it
 * never acts without asking — rather than borrowing the seats-and-billing
 * shape of a hosted product it isn't.
 *
 * A server component: the only client code on the page is the shader, the
 * preview's tilt and the scroll reveals.
 */

export const metadata = {
  title: "NEXUS — a local AI operating layer for macOS",
  description:
    "NEXUS understands your development environment, remembers what matters, and notices when something changes — without ever acting on your Mac unless you approve it.",
};

const CAPABILITIES = [
  {
    title: "It knows where you are",
    body: "Your active workspace, its branch, what's uncommitted, and which servers you started — gathered from your machine, never guessed.",
  },
  {
    title: "It remembers across sessions",
    body: "Durable facts about your projects survive restarts, carry a confidence level, and are marked stale the moment live evidence disagrees.",
  },
  {
    title: "It notices on its own",
    body: "A crashed process, a service gone quiet, a branch switch. Deterministic sensors, no model in the loop, no notification spam.",
  },
  {
    title: "It suggests, you decide",
    body: "Every suggestion becomes an ordinary request you can read before it runs. Nothing that changes your Mac happens without approval.",
  },
];

const GUARANTEES = [
  ["Local only", "Bound to loopback. Your code and context never leave the machine."],
  ["Approval-gated", "Anything that changes your Mac stops for a decision, every time."],
  ["Confined", "Filesystem and command policies refuse traversal, secrets and shells."],
  ["Bounded", "Context, memory and output are capped so a runaway can't spiral."],
];

function Logo() {
  return (
    <span className="flex items-center gap-2.5">
      <span className="grid h-7 w-7 place-items-center rounded-[8px] bg-gradient-to-b from-[var(--accent-2)] to-[var(--accent)] text-[12px] font-bold text-white shadow-[var(--shadow-sm)]">
        N
      </span>
      <span className="text-[14px] font-semibold tracking-[0.16em]">NEXUS</span>
    </span>
  );
}

function ArrowIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M3.5 8h9M9 4.5L12.5 8 9 11.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function Landing() {
  return (
    <div className="relative min-h-full overflow-x-hidden">
      {/* --- header --------------------------------------------------------- */}
      <header className="glass sticky top-0 z-50 border-b border-[var(--line)]">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-5 sm:px-8">
          <Logo />
          <nav className="flex items-center gap-1.5">
            <a
              href="#capabilities"
              className="btn btn-ghost !border-transparent hidden sm:inline-flex"
            >
              Capabilities
            </a>
            <a
              href="#trust"
              className="btn btn-ghost !border-transparent hidden sm:inline-flex"
            >
              Safety
            </a>
            <Link href="/dashboard" className="btn btn-primary">
              Open dashboard
              <ArrowIcon />
            </Link>
          </nav>
        </div>
      </header>

      {/* --- hero ----------------------------------------------------------- */}
      <section className="relative">
        <div className="absolute inset-0 -z-10 h-[130%] max-h-[1100px]">
          {/* the static gradient is the fallback the shader fades over */}
          <div className="aurora absolute inset-0" />
          <AuroraCanvas className="absolute inset-0 opacity-70 mix-blend-screen" />
          <div className="absolute inset-x-0 bottom-0 h-64 bg-gradient-to-b from-transparent to-[var(--bg)]" />
        </div>

        <div className="mx-auto max-w-6xl px-5 pb-16 pt-20 sm:px-8 sm:pb-24 sm:pt-28">
          <div className="mx-auto max-w-3xl text-center">
            <span
              className="enter chip chip-accent mx-auto"
              style={{ "--i": 0 }}
            >
              <span className="dot dot-accent" />
              Runs entirely on your Mac
            </span>

            <h1
              className="enter t-display t-gradient mt-6 text-balance"
              style={{ "--i": 1 }}
            >
              An AI layer that understands
              <br className="hidden sm:block" /> your machine.
            </h1>

            <p
              className="enter t-body mx-auto mt-5 max-w-xl text-pretty sm:text-[1.0625rem]"
              style={{ "--i": 2 }}
            >
              NEXUS reads your workspace, remembers what matters across
              sessions, and tells you when something changes — then waits for
              your approval before touching anything.
            </p>

            <div
              className="enter mt-8 flex flex-col items-center justify-center gap-2.5 sm:flex-row"
              style={{ "--i": 3 }}
            >
              <Link
                href="/dashboard"
                className="btn btn-primary btn-lg w-full sm:w-auto"
              >
                Open dashboard
                <ArrowIcon />
              </Link>
              <a
                href="#capabilities"
                className="btn btn-ghost btn-lg w-full sm:w-auto"
              >
                See what it does
              </a>
            </div>

            <p
              className="enter mono mt-5 text-[11px] text-[var(--ink-3)]"
              style={{ "--i": 4 }}
            >
              localhost · no account · no telemetry
            </p>
          </div>

          <div className="enter mt-16 sm:mt-20" style={{ "--i": 5 }}>
            <ProductPreview />
            <p className="mt-3 text-center text-[11px] text-[var(--ink-4)]">
              Illustrative view of the NEXUS dashboard.
            </p>
          </div>
        </div>
      </section>

      {/* --- capabilities --------------------------------------------------- */}
      <section
        id="capabilities"
        className="mx-auto max-w-6xl scroll-mt-20 px-5 py-20 sm:px-8 sm:py-28"
      >
        <Reveal className="max-w-2xl">
          <p className="t-label">What it does</p>
          <h2 className="t-h1 mt-3 text-balance">
            Context is the product. Everything else follows from it.
          </h2>
          <p className="t-body mt-4 max-w-xl">
            Most assistants start every conversation from nothing. NEXUS starts
            from your machine — and tells you what it looked at.
          </p>
        </Reveal>

        <div className="mt-12 grid gap-3 sm:grid-cols-2">
          {CAPABILITIES.map((item, index) => (
            <Reveal key={item.title} delay={index % 2}>
              <article className="card card-hover h-full p-6">
                <span className="mono text-[11px] text-[var(--accent)]">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <h3 className="t-h2 mt-3">{item.title}</h3>
                <p className="t-body mt-2 text-[0.875rem]">{item.body}</p>
              </article>
            </Reveal>
          ))}
        </div>
      </section>

      {/* --- safety --------------------------------------------------------- */}
      <section
        id="trust"
        className="relative scroll-mt-20 border-y border-[var(--line)] bg-[var(--bg-1)]"
      >
        <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-24">
          <Reveal className="max-w-2xl">
            <p className="t-label">Safety</p>
            <h2 className="t-h1 mt-3 text-balance">
              It can see a lot. It can change almost nothing.
            </h2>
            <p className="t-body mt-4 max-w-xl">
              Reading is free; acting is not. Every tool that touches your Mac
              is classified, and the ones that change anything stop for you —
              every time, with the arguments shown.
            </p>
          </Reveal>

          <div className="mt-12 grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
            {GUARANTEES.map(([title, body], index) => (
              <Reveal key={title} delay={index}>
                <div className="border-t border-[var(--line-2)] pt-4">
                  <h3 className="text-[0.9375rem] font-medium">{title}</h3>
                  <p className="t-body mt-1.5 text-[0.8125rem]">{body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* --- close ---------------------------------------------------------- */}
      <section className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-28">
        <Reveal>
          <div className="card relative overflow-hidden px-6 py-14 text-center sm:px-16 sm:py-20">
            <div className="aurora absolute inset-0 opacity-50" />
            <div className="relative">
              <h2 className="t-h1 text-balance">Open it and ask where you left off.</h2>
              <p className="t-body mx-auto mt-4 max-w-md">
                The dashboard reads your current workspace the moment it loads.
              </p>
              <Link
                href="/dashboard"
                className="btn btn-primary btn-lg mx-auto mt-8"
              >
                Open dashboard
                <ArrowIcon />
              </Link>
            </div>
          </div>
        </Reveal>
      </section>

      <footer className="border-t border-[var(--line)]">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-5 py-7 sm:flex-row sm:px-8">
          <Logo />
          <p className="text-[11px] text-[var(--ink-4)]">
            A local AI operating layer for macOS.
          </p>
        </div>
      </footer>
    </div>
  );
}
