# NEXUS

A local AI operating system for macOS.

NEXUS is not a chatbot with a few plugins. It is a three-process system: a
control UI, an agent runtime, and a Mac-side MCP server. The model never talks
to macOS directly. Every capability is a named tool, classified as `SAFE`,
`CONFIRM` or `RESTRICTED`, and reached only through the graph.

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

This is **v0.1**. The agent runs, the UI shows what it can see, and Mac tools
are real — it is not a full desktop automation layer. The backend binds to
`127.0.0.1` on purpose. The MCP server has no socket and must never be given
one.

Suggested GitHub name: **`nexus-os`**. The current `distributed-systems-lab`
name is leftover from the study log this started as. Rename in GitHub →
Settings → Repository name.

---

## Why three packages

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
enforces permissions — it *declares* a level; the backend's policy and
approval broker decide whether the call runs. That split is load-bearing: a
second permission system in the child process would drift from the one the
UI talks to.

---

## Backend

Agent runtime. FastAPI + LangGraph + a provider-agnostic model layer.

See [`backend/README.md`](backend/README.md) and
[`backend/BACKEND_SPEC.md`](backend/BACKEND_SPEC.md) for the full contract.
This is the map of what lives where.

```text
backend/app/
├── main.py          app factory only — lifespan, CORS, error envelopes
├── api/             routers, schemas, websocket — thin, no agent logic
├── agent/           graph, nodes, runner, tasks, approvals, events
├── models/          ModelProvider + Groq + Mistral + router
├── tools/           registry and permission classification
├── mcp/             stdio client and process pool
├── context/         intent, collectors, relevance, extraction
├── mission/         multi-step planning (used by the runner)
└── core/            config, logging, error types
```

### Models

The graph talks to `ModelProvider` only. Groq (`ChatGroq`) is the default;
Mistral speaks to the official SDK and is translated at the boundary. Set
`DEFAULT_MODEL_PROVIDER=groq|mistral`, or override per request:

```json
{ "message": "What is my battery percentage?", "provider": "mistral" }
```

Configured models need tool calling. The documented defaults are
`llama-3.1-8b-instant` (Groq) and `mistral-small-latest`. Identifiers are not
hard-coded in Python — they come from `.env` so an account that cannot use a
model does not get a surprise default.

Tests never call a vendor API. The provider is stubbed; everything below it
(graph, registry, permissions, MCP spawn) runs for real.

### A request

`POST /api/chat` returns as soon as a task exists (`201 { task_id, status }`).
The agent then runs in the background:

1. **Intent.** A deterministic regex, not a model call, classifies the
   message: `CONTINUE`, `WHAT_CHANGED`, `ORIENT`, `RECALL`, or `GENERAL`.
   Wrong is cheap (extra SAFE gathering). A second LLM round-trip to decide
   whether to gather context is latency nobody asked for.
2. **Context.** Collectors matching the plan run through SAFE tools only.
   `"what's my battery?"` (`GENERAL`) does not scan the workspace. `"continue
   where I left off"` does. Failure here degrades to the ordinary system
   prompt; it never fails the request.
3. **Graph.** The model chooses tools. Each call is classified. `SAFE` runs.
   `CONFIRM` parks the task and emits `permission_required` over the
   WebSocket. `RESTRICTED` is not offered at all.
4. **Finish.** The last assistant text is the answer. Tool results are
   capped (`32_000` chars) so one oversized MCP payload cannot exhaust every
   later turn. Truncation is marked in the transcript — silent cuts teach
   the model to answer from half a file.

Connect `WS /api/ws?task_id=` even after submit: already-emitted events are
replayed, so a late client still sees the whole run.

### Permissions

Every tool is `SAFE`, `CONFIRM`, or `RESTRICTED`. Unclassified is
`RESTRICTED` — classification is opt-in, never inferred. MCP metadata
(`{"nexus": {"permission": "SAFE"}}`) wins over the backend baseline table.

A `CONFIRM` call:

1. The broker records a request and the graph blocks.
2. The task status becomes `permission_required`; the UI shows Approve / Deny.
3. `POST /api/permissions/{request_id}/approve` (or `/deny`) wakes the agent.
4. Deny is told to the model as a user decision, not as a crash.

Unanswered requests expire after `PERMISSION_TIMEOUT_SECONDS` (default 300).
A client that already intends a tool can skip the round-trip:

```json
{ "message": "Open VS Code", "approved_tools": ["open_application"] }
```

Pre-approval cannot make a `RESTRICTED` tool runnable. Prompt text from a
file, a command, or a memory cannot either: permission is evaluated in
`tool_node` against the registry and the broker. Tests in
`tests/test_prompt_injection.py` feed hostile tool results and assert on
what the *runtime* did, never on what the stub model said.

Logs record argument **names**, never values (`tests/test_secret_redaction.py`).

### API

Mac capabilities are never HTTP endpoints. There is no `/api/battery`.
Battery status is a tool, reached only through the agent.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness |
| POST | `/api/chat` | Accept a message; run the agent in the background |
| WS | `/api/ws` | Live execution events (`?task_id=` to filter / replay) |
| GET | `/api/tasks` | Recent tasks, newest first |
| GET | `/api/tasks/{task_id}` | One task and its event history |
| POST | `/api/tasks/{task_id}/cancel` | Stop a running task |
| GET | `/api/tools` | Discoverable tools and their level. Information only |
| GET | `/api/permissions/pending` | Calls waiting on the user |
| POST | `/api/permissions/{id}/approve` | Let a waiting call run |
| POST | `/api/permissions/{id}/deny` | Refuse it |
| GET | `/api/context` | What NEXUS can see right now (SAFE snapshot, briefly cached) |
| GET | `/api/context/{task_id}` | The snapshot that informed one answer |
| GET | `/api/memory` | Remembered facts. Read-only |
| GET | `/api/mcp/servers` | MCP server status |
| GET | `/api/models` | Configured providers and the default |

`GET /api/memory` has no DELETE. Forgetting is a `CONFIRM` tool. A REST
delete would be a second path to the same effect with none of the same
checks; the UI's Forget action sends a chat message and goes through the
ordinary approval bar.

Errors before a task exists are HTTP errors:
`{"error": {"code", "message"}}`. Once a task exists, failure lives on the
task record so the UI always has something to render.

### Config

Copied from `backend/.env.example`. Never commit `.env`.

| Variable | Role |
| --- | --- |
| `GROQ_API_KEY` / `MISTRAL_API_KEY` | Vendor credentials |
| `GROQ_MODEL` / `MISTRAL_MODEL` | Tool-calling model ids |
| `DEFAULT_MODEL_PROVIDER` | `groq` (default) or `mistral` |
| `BACKEND_HOST` / `BACKEND_PORT` | `127.0.0.1:8000` |
| `CORS_ORIGINS` | Explicit list — never a wildcard |
| `AGENT_MAX_ITERATIONS` | Graph step budget |
| `PERMISSION_TIMEOUT_SECONDS` | How long a CONFIRM call waits |
| `CONTEXT_MAX_MEMORIES` / `_WORKSPACE_FACTS` / `_CHARS` | Prompt budget |
| `MCP_SERVER_COMMAND` / `_ARGS` | Override which local MCP process to spawn |

---

## Mac MCP

Local capability server. Started by the backend as a child over **stdio**.
It is a library of tools plus the policy that keeps them from becoming a
shell.

See [`nexus-mac-mcp/README.md`](nexus-mac-mcp/README.md) for the command
profiles and security notes. Summary of what the child actually does:

```text
src/nexus_mac_mcp/
├── server.py              registers tools + permission metadata
├── tools/
│   ├── system.py          battery, system_info, running_processes
│   ├── files.py           list, search, read
│   ├── workspace.py       detect_workspace (inspection, no commands)
│   ├── git.py             four fixed read-only Git invocations
│   ├── applications.py    name → bundle lookup, then open
│   ├── commands.py        run_command
│   ├── processes.py       start / list / status / logs / stop
│   ├── network.py         check_local_service (loopback only)
│   └── memory.py          list / get / save / delete
└── core/
    ├── filesystem.py      the only place path safety is decided
    ├── commands.py        allowlist + profiles
    ├── process_policy.py  which commands may run in the background
    ├── process_manager.py groups, ring buffers, teardown
    ├── environment.py     what a subprocess is allowed to inherit
    ├── memory_store.py    SQLite under ~/.nexus/nexus.db
    └── memory_secrets.py  refused before a row is written
```

### Tools

| Tool | Level | What it does |
| --- | --- | --- |
| `battery_status` | SAFE | Charge %, charging state, time remaining |
| `system_info` | SAFE | macOS version, architecture, hostname, CPU count |
| `running_processes` | SAFE | Busiest processes by CPU. Names only, never full command lines |
| `list_directory` | SAFE | One directory. Does not recurse |
| `search_files` | SAFE | Find files by name under a directory |
| `read_file` | SAFE | Text files. Refuses secrets, binaries, oversized files |
| `detect_workspace` | SAFE | What kind of project a directory holds |
| `git_status` / `git_branch` / `git_log` / `git_diff` | SAFE | Fixed read-only Git. `git_diff` is `--stat`, never the patch |
| `list_processes` / `process_status` / `process_logs` | SAFE | Only processes *this* server started |
| `check_local_service` | SAFE | Probe a loopback URL. No redirects, no bodies, no credentials in the URL |
| `list_memories` / `get_memory` | SAFE | Recall. Staleness is reported, never hidden |
| `open_application` | CONFIRM | Open an installed app by name |
| `run_command` | CONFIRM | An approved developer command, not a shell |
| `start_process` / `stop_process` | CONFIRM | Supervise / kill a NEXUS-started dev server |
| `save_memory` / `delete_memory` | CONFIRM | Write or forget. Secrets in the value are refused |

There is no terminal tool and no arbitrary `git`. An executable being allowed
does not make every invocation of it allowed.

| Executable | Allowed forms |
| --- | --- |
| `pytest` | `pytest [paths]` with a short flag set |
| `uv` | `uv run pytest`, `uv run python -m <approved>`, `uv run python <script>`, `--version` |
| `npm` | `run build|test|lint`, `test`, `--version`. `run dev` / `start` are refused here and pointed at `start_process` |
| `node` / `python` | a script, `-m <approved module>`, `--version` |
| `uvicorn` | `module:app` on loopback only |
| `git` | `status`, `branch`, `log`, `diff --stat`, `--version` |

Deliberately absent: `npx`, installers (`pip install`, `uv add`, `npm install`),
inline code (`python -c`, `node -e`), and anything that writes a repository
(`commit`, `push`, `reset`, `checkout`, `clean`).

### How it stays on the machine, not in the network

**Paths.** Every path is resolved — `~`, `..`, and symlinks — *then* checked
against `NEXUS_MAC_ALLOWED_ROOTS` (`$HOME` by default). A symlink into `/etc`
is `/etc` and is rejected. Searches do not follow links. `.ssh`, `.aws`,
`.gnupg`, `Library`, `.config/gh`, and similar are denied independently of
the allowlist.

**Secrets.** Name policy covers `.env`, `*.pem`, `*.key`, `id_rsa`,
`*credentials`, `.*history`, `.netrc`, and kin. Listings can *show* the name
(flagged `protected`). Reads cannot. Memory values go through the same
detector before SQLite.

**No shell.** Commands are argv lists against an absolute path from a fixed
`PATH`. No `shell=True`, no `/bin/sh -c`. The command *text* must match a
safe character class, so `pytest && rm -rf /` dies before tokenisation. The
child does not inherit the MCP process environment: `GROQ_API_KEY` is not
handed to `pytest`.

**Processes.** `start_process` uses the same command policy, then asks one
more question: may this run forever? Only `npm run dev` / `start` and
`uvicorn`. Each process gets its own group and a 200KB ring buffer per
stream. `stop_process` takes a *NEXUS process id*, never a pid, so it cannot
signal something it did not start. When the MCP process exits, everything it
started is torn down. A port already in use is reported, never cleared.

**Output.** Directory entries, search hits, file size, git log, command
bytes, and memory values (`8_192` bytes) are all bounded so a tool cannot
flood the model.

**Loopback only.** `--host 0.0.0.0` is refused. `check_local_service` can
reach `127.0.0.1` / `localhost` / `::1` and nothing else.

### Memory store

SQLite at `~/.nexus/nexus.db` (override `NEXUS_MAC_DB_PATH` in tests). A
memory is a typed fact, not a diary entry: `USER_PREFERENCE`, `PROJECT`,
`WORKSPACE`, `WORKFLOW`, `DECISION`, `TASK_CONTEXT`, `FACT`. Source is
`USER` / `SYSTEM` / `MISSION`, which sets default confidence. Status is
`ACTIVE`, `STALE`, or `DELETED` (soft). `last_verified_at` decays unread
HIGH facts toward MEDIUM after fourteen days, so live evidence wins without
a fight.

A rewrite of the same `(type, key)` updates in place and resets
verification. Contradicted rows are marked `STALE` and kept — the user
decides whether to forget. `delete_memory` with `wipe_all` matches *every*
row, not the list cap of 50; borrowing that cap used to leave the 51st
memory behind while reporting success.

Database failures become one fixed message (“memory is unavailable…”) with
no path and no host filesystem detail in text the model will see.

The server exits immediately on anything other than macOS.

---

## Frontend

Next.js control centre. The point of the UI is not a chat transcript; it is
that an assistant claiming to understand the environment can *show* that
environment next to its answers.

```text
frontend/src/
├── app/
│   ├── page.js                 two-column shell
│   └── components/
│       ├── Conversation.js     messages
│       ├── Composer.js         input + stop
│       ├── ApprovalBar.js      pending CONFIRM calls
│       ├── ContextPanel.js     workspace, git, processes, machine
│       ├── MemoryPanel.js      facts + Forget (via chat)
│       └── Timeline.js         live execution events
└── lib/
    ├── api.js                  the only place that knows HTTP/WS paths
    ├── useNexus.js             health, panels, websocket, send/decide/stop
    └── format.js               paths, relative time
```

Left: **Workspace** (project, branch, dirty files, running NEXUS processes,
machine), **Memory**, **Timeline**. Right: conversation, error strip,
approval bar, composer.

`useNexus` splits two clocks. The WebSocket is source of truth for *now* —
tool calls, tokens, permission requests, completion. Panels poll
`/api/context` and `/api/memory` on a few-second interval because workspace
state changes on human timescales and the backend already caches that view
(`CONTEXT_CACHE_SECONDS = 5`). Context served to the sidebar is the same
`to_public_dict()` the agent used; the two cannot drift into different
schemas.

Unknown is rendered as unknown. A status panel that invents a branch is
worse than one that says it cannot see.

The UI does not delete memory over REST. Forget sends a message so
`delete_memory` hits the approval broker like any other CONFIRM tool.

Backend URL defaults to `http://127.0.0.1:8000`. Override with
`NEXT_PUBLIC_NEXUS_API` if needed. CORS on the backend is an explicit origin
list (`FRONTEND_ORIGIN` / `CORS_ORIGINS`); credentials are not used.

---

## Context and recall

Gathering is **opt-in per intent**. Flags default off so a new intent cannot
inherit an expensive scan.

| Intent | Typical phrasing | What is gathered |
| --- | --- | --- |
| `CONTINUE` | “continue where I left off” | workspace, git, processes, memories, recent task summaries |
| `WHAT_CHANGED` | “what did I change?” | workspace + git. Not memory — Git is the evidence |
| `ORIENT` | “what am I working on?” | workspace, processes, memories |
| `RECALL` | “what do you remember?” | memories only. No filesystem |
| `GENERAL` | everything else | ordinary cheap context; the agent can still call SAFE tools itself |

Relevance scoring for memories is explicit (key hit, typed overlap, path in
the question) rather than embeddings. Every point a memory scores can be
named, which is what makes the memory panel honest.

Extraction is conservative and suggestion-only. Present-tense durable facts
(“the API runs on port 8123”) may be proposed. Status (“the tests are
failing”), conditionals, and anything the secret detector would reject are
not. A proposal still has to go through `save_memory` (`CONFIRM`). A missed
memory costs one sentence next time; a wrong one outlives the conversation.

---

## Run it

Python 3.14+, [uv](https://docs.astral.sh/uv/), Node.js, a Groq or Mistral
key. Two terminals. macOS (the MCP child will refuse anything else).

```bash
# backend
cd backend
uv sync
cp .env.example .env          # set GROQ_API_KEY (and GROQ_MODEL if you diverge)
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# UI
cd frontend
npm install
npm run dev                   # http://localhost:3000
```

The backend opens the MCP pool at startup so a process started in one turn
is still there in the next. You do not start `nexus-mac-mcp` yourself.
Standalone, for debugging only:

```bash
cd nexus-mac-mcp
uv run python -m nexus_mac_mcp
```

- Health: <http://127.0.0.1:8000/health>
- OpenAPI: <http://127.0.0.1:8000/docs>

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "What is my battery percentage?"}'
# 201 {"task_id": "task_...", "status": "started"}
```

Follow on `WS /api/ws?task_id=` or `GET /api/tasks/{task_id}`.

### Tests

```bash
cd backend && uv run pytest
cd nexus-mac-mcp && uv run pytest                  # no windows
cd nexus-mac-mcp && uv run pytest -m integration   # opens TextEdit
```

MCP integration tests are excluded by default so `pytest` never launches
apps on your machine.

---

## What this is not

- Not a remote agent. Binding the backend off loopback would expose a
  process that can act on this Mac.
- Not a shell. `run_command` is a profile matcher.
- Not a vector store. Memory is a small structured SQLite table, scored
  with named signals.
- Not done. Missions, richer UI, tighter workspace roots, and more tools
  come after this runtime is trustworthy.

Secrets live in `backend/.env` (gitignored). Only `.env.example` files are
committed.
