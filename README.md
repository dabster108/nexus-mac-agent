<div align="center">

# NEXUS

### A local AI operating layer for macOS

Understand your workspace. Act with approval. Verify the result.

NEXUS gives an AI agent a bounded, explainable view of your Mac — your
workspace, Git state, processes, local services, and durable project memory —
without turning your computer into an unattended automation target.

<p>
  <a href="#quick-start">Quick start</a> ·
  <a href="#what-nexus-does">Capabilities</a> ·
  <a href="#trust-model">Trust model</a> ·
  <a href="DECISIONS.md">Architecture decisions</a>
</p>

</div>

---

## Why NEXUS

Most AI developer tools begin with a blank chat. NEXUS begins with the
environment you are already working in. It gathers relevant context, lets
LangGraph choose from discovered MCP tools, pauses before anything changes
your Mac, and reports the evidence behind the result.

It is deliberately local, single-user, and approval-gated. The model chooses
what to ask for; the backend decides what may run; the Mac MCP server performs
the capability behind a real process boundary.

```text
┌─────────────┐   HTTP / WebSocket    ┌──────────────────────────┐
│  frontend   │ ───────────────────►  │  backend (FastAPI)       │
│  Next.js    │                       │  LangGraph agent         │
│  :3000      │                       │  Groq / Mistral          │
└─────────────┘                       │  context + permissions   │
                                      └────────────┬─────────────┘
                                                   │ stdio (MCP)
                                                   ▼
                                      ┌──────────────────────────┐
                                      │  nexus-mac-mcp           │
                                      │  no network listener     │
                                      │  tools → macOS           │
                                      └──────────────────────────┘
```

The backend binds to `127.0.0.1` on purpose. The MCP server has no socket and
must never be given one.

For the full architecture decision record — every mechanism, limit and
rationale, read out of the source — see **[DECISIONS.md](DECISIONS.md)**.

---

## What NEXUS does

### Context-aware assistance

- Detects the active workspace, Git branch, changed files, and running
  development processes
- Retrieves relevant durable memories from SQLite across sessions
- Uses deterministic intent and context rules before asking the model to act

### Controlled execution

- Discovers 25 capabilities from the bundled `nexus-mac-mcp` server
- Keeps read-only tools `SAFE`, machine-changing tools `CONFIRM`, and unknown
  tools `RESTRICTED`
- Routes every action through LangGraph, the tool registry, and the approval
  broker

### Closed-loop results

- Verifies declared actions with independent SAFE-only checks
- Distinguishes `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`, and `UNKNOWN`
- Shows evidence and a read-only execution trace instead of invented certainty

### Proactive, never autonomous

- Notices process failures, service changes, Git changes, and memory conflicts
- Offers suggestions as ordinary questions, never as hidden tool calls
- Keeps the user in control of every operation that changes the machine

---

## Core architecture

### The request path

```text
USER
 → FastAPI               POST /api/chat returns a task_id immediately
 → Intent                deterministic regex classification, no model call
 → Context               memories, workspace, git, processes, recent tasks
 → LangGraph / Agent     agent ⇄ tools, bounded
 → Tool Registry         neutral ToolDefinition / ToolResult vocabulary
 → Permission Policy     SAFE runs · CONFIRM stops · RESTRICTED never runs
 → Approval Broker       blocks the tool node until a human answers
 → MCP                   JSON-RPC over stdio to a child process
 → macOS
```

### What happens to a result

```text
Tool Result
 → Verification          SAFE-only re-check, against the tool's own contract
 → Outcome               SUCCESS · PARTIAL_SUCCESS · FAILED · UNKNOWN
 → Observations          deterministic sensors record what changed
 → Suggestions           an offer, phrased as a question — never a call
```

### How an explanation is built

```text
Task Events + Context + Registry Metadata
 → Trace                 a pure projection of what was already recorded
```

The trace adds no new source of truth. It can only show what already went out
on the WebSocket.

---

## Product model

These words mean specific, non-interchangeable things.

### Permission levels

| Level | Meaning |
| --- | --- |
| **SAFE** | Read-only. Runs immediately, no approval. 19 of the 25 tools. |
| **CONFIRM** | Changes something. Always stops for a human decision. 6 tools. |
| **RESTRICTED** | Never executed. Also the default for any tool nobody classified. |

### Units of work

| Term | Meaning |
| --- | --- |
| **Task** | One request, one `task_id`, one row in the in-memory `TaskStore`. |
| **Mission** | One request that implies several ordered steps. Each step runs through the *same* agent graph, with the same permission path. Not a second runtime. |

### What NEXUS knows

| Term | Meaning |
| --- | --- |
| **Context** | What was gathered *before* planning — memories, workspace, git, processes, recent tasks. Assembled fresh per request and bounded. |
| **Memory** | A durable fact in SQLite at `~/.nexus/nexus.db`. Typed, confidence-scored, soft-deleted. Survives restarts. |

### What NEXUS notices

| Term | Meaning |
| --- | --- |
| **Observation** | Something a deterministic sensor saw, unprompted. No model involved. States a fact; never triggers anything. |
| **Suggestion** | An offer derived from an observation. Holds an intent label and a natural-language **prompt** — no tool name, no arguments. |

### What NEXUS concludes

| Term | Meaning |
| --- | --- |
| **Verification** | An independent re-check, using SAFE tools only, against the contract the tool declared. |
| **Outcome** | The verdict — `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`, `UNKNOWN` — with evidence marked `OBSERVED` (seen) or `INFERRED` (capped at MEDIUM confidence). |
| **Trace** | The recorded decisions and evidence for one task, grouped into phases. |

---

## Trust model

**Proactive does not mean autonomous.** NEXUS observes on its own, offers on
its own, and explains on its own. Between noticing a problem and changing
anything on your machine there is always a person.

**Suggestions cannot execute tools.** `SuggestedAction` has no `tool` field and
no `arguments` field — not empty ones, none at all. Accepting a suggestion
sends its prompt to `POST /api/chat` exactly as if you had typed it. There is
deliberately no `POST /api/suggestions/{id}/execute`, and the frontend has no
endpoint that can invoke a tool.

**CONFIRM always goes through the approval broker.** Every one of them, every
time. Approval is per call and does not persist. A denial means the tool never
starts — the model is told it was refused and must say so.

**SUCCESS requires evidence, not a successful tool return.** `tool_completed`
only ever meant "the tool returned". Where a tool declares what success looks
like, NEXUS goes and checks, and reports what it actually found.

**Traces expose recorded decisions and evidence, never hidden
chain-of-thought.** There is no field anywhere in the trace that can hold model
reasoning, because reasoning is not recorded anywhere.

---

## Quick start

NEXUS currently runs on macOS and requires:

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- Node.js and npm
- A tool-calling model from Groq or Mistral

The backend and MCP server are local. The model provider is the only external
service NEXUS contacts.

### 1. Configure and start the backend

```bash
cd backend
uv sync
cp .env.example .env
#   Set GROQ_API_KEY and GROQ_MODEL to a model your account can use.
#   Or configure MISTRAL_API_KEY, MISTRAL_MODEL and
#   DEFAULT_MODEL_PROVIDER=mistral.
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The backend automatically starts the bundled MCP server over stdio. Verify both
the API and the MCP connection:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/models
curl http://127.0.0.1:8000/api/mcp/servers
```

### 2. Start the frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000
```

Open <http://localhost:3000/dashboard>. The frontend talks to
`http://127.0.0.1:8000` by default. To point it elsewhere, set
`NEXT_PUBLIC_NEXUS_API` before starting Next.js.

### 3. MCP lifecycle

You do not start the MCP server yourself during normal use. The backend spawns
it as a child process over stdio and keeps the session pool open, so a process
started in one turn remains available in the next. Run it standalone only for
protocol debugging:

```bash
cd nexus-mac-mcp
uv run python -m nexus_mac_mcp
```

### Try it without the UI

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "What is my battery percentage?"}'
# {"task_id": "task_...", "status": "started"}

curl http://127.0.0.1:8000/api/tasks/task_...
curl http://127.0.0.1:8000/api/tasks/task_.../trace
```

Follow live on `WS /api/ws` (all events) or `WS /api/ws?task_id=...` (one task).
Interactive API docs: <http://127.0.0.1:8000/docs>.

### Tests

```bash
cd backend        && uv run pytest
cd nexus-mac-mcp  && uv run pytest                  # no windows opened
cd nexus-mac-mcp  && uv run pytest -m integration   # opt-in macOS checks
cd frontend       && npm run lint && npm run build
```

MCP integration tests are opt-in so a plain `pytest` never launches apps on
your machine.

---

## Repository map

| Path | Process | Job |
| --- | --- | --- |
| [`frontend/`](frontend/) | Browser | Show the same facts the model was given, stream the run, collect approvals |
| [`backend/`](backend/) | Python, loopback | Orchestrate the agent. Own permissions. Never execute Mac code itself |
| [`nexus-mac-mcp/`](nexus-mac-mcp/) | Child of the backend | Touch the machine. Declare permission metadata. Enforce filesystem and command policy |

The layering is strict and one-way:

```text
API → runner → LangGraph → tool registry → MCP → macOS
```

Routes never call a model, an MCP server, or a tool. The MCP server never
enforces permissions — it *declares* a level; the backend's policy and approval
broker decide whether the call runs. That split is load-bearing: a second
permission system in the child process would drift from the one the UI talks to.

```text
backend/app/
├── main.py            app factory — lifespan, CORS, error envelopes
├── api/               routers, schemas, websocket — thin, no agent logic
├── agent/             runner, graph, nodes, events, tasks, approvals
├── mission/           detection, planner, engine, state
├── context/           intent, collector, relevance, extraction
├── memory events      context/memory_events.py
├── observations/      rules, detector, scheduler, store
├── suggestions/       rules, engine, store
├── verification/      planner, verifier, outcomes
├── trace/             builder, explain, models
├── tools/             registry, permission classification
├── mcp/               the only place MCP concepts exist
├── models/            groq, mistral, router
└── core/              config, errors, logging

nexus-mac-mcp/src/nexus_mac_mcp/
├── server.py          tool declarations + permission metadata
├── tools/             thin adapters
└── core/              enforcement: filesystem, commands, processes, memory

frontend/src/
├── lib/useNexus.js    the entire client connection (REST + WebSocket)
├── lib/api.js         the one place the frontend knows the backend's shape
└── app/               landing page, dashboard, components
```

### Frontend state rule

```text
REST      = authoritative state (on load, and again on every reconnect)
WebSocket = incremental updates while connected
Backend   = the source of truth, always
```

Only `/api/context` is polled, because it is the one thing with no event of its
own. Everything else arrives on the socket.

---

## What this is not

- **Not a remote agent.** Binding the backend off loopback would expose a
  process that can act on this Mac. There is no authentication; anyone who can
  reach the port is the user.
- **Not a shell.** `run_command` is a profile matcher over an allowlist of
  executables and argument shapes. No pipes, no redirection, no chaining.
- **Not a vector store.** Memory is a small structured SQLite table scored with
  named, deterministic signals. No embeddings, no RAG.
- **Not persistent beyond memory.** Tasks, observations, suggestions and
  pending approvals live in the backend process and are gone when it restarts.

Deliberately absent, and not on a roadmap: browser automation, AppleScript,
GUI/keyboard/mouse control, email, calendar, cloud memory, multi-user support,
arbitrary shell execution, autonomous remediation, and any second path to
executing a tool.

Secrets live in `backend/.env` (gitignored). Only `.env.example` files are
committed.
