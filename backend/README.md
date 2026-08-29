# NEXUS Backend

Agent runtime for NEXUS, an AI operating system for macOS. FastAPI + LangGraph,
talking to models through a provider abstraction (Groq, Mistral) and to tools
through MCP.

See [BACKEND_SPEC.md](BACKEND_SPEC.md) for the full architecture. This is v0.1:
the foundation and one working tool, not the whole Mac automation layer.

## Setup

All commands run from `backend/`.

```bash
uv sync                 # install dependencies (including dev)
cp .env.example .env    # then fill in the values below
```

Required in `.env` before the agent can run:

| Variable | Notes |
| --- | --- |
| `GROQ_API_KEY` | From <https://console.groq.com> |
| `GROQ_MODEL` | A tool-calling capable model your account can use |
| `DEFAULT_MODEL_PROVIDER` | `groq` (default) or `mistral` |

Model identifiers are deliberately not defaulted — pick one your account has
access to. Mistral works the same way via `MISTRAL_API_KEY` / `MISTRAL_MODEL`.

`.env` is git-ignored and its values never leave the backend.

## Run

```bash
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Health: <http://127.0.0.1:8000/health>
- Docs: <http://127.0.0.1:8000/docs>

The server binds to the loopback address on purpose: the agent can act on your
Mac and must not be reachable from the local network.

## Test

```bash
uv run pytest
```

Tests never call a model API — the provider is stubbed. Everything below it
(graph, registry, permissions, MCP) runs for real, including spawning the
bundled MCP server over stdio.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness |
| POST | `/api/chat` | Accept a message; runs the agent in the background |
| WS | `/api/ws` | Live execution events (`?task_id=` to filter) |
| GET | `/api/tasks` | Recent tasks, newest first |
| GET | `/api/tasks/{task_id}` | One task with its full event history |
| POST | `/api/tasks/{task_id}/cancel` | Stop a running task |
| GET | `/api/tools` | Discoverable tools and their permission level |
| GET | `/api/tools/{tool_name}` | One tool. Information only — never executes |
| GET | `/api/permissions/pending` | Tool calls waiting on the user |
| POST | `/api/permissions/{request_id}/approve` | Let a waiting tool call run |
| POST | `/api/permissions/{request_id}/deny` | Refuse it |
| GET | `/api/mcp/servers` | MCP server status (probed live) |
| GET | `/api/models` | Configured providers and the default |

Mac capabilities are never endpoints. There is no `/api/battery` — battery
status is a tool behind MCP, reached only through the agent.

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "What is my battery percentage?"}'
# -> 201 {"task_id": "task_...", "status": "started"}
```

`POST /api/chat` returns as soon as the task exists. Follow it on `WS /api/ws`
or poll `GET /api/tasks/{task_id}`. Connecting the WebSocket with `?task_id=`
replays the events already emitted, so a client that connects after submitting
still sees the whole run.

Requests that fail *before* a task exists (an empty message, an unknown id)
return an HTTP error with a `{"error": {"code", "message"}}` body. Once a task
exists, its outcome — including failure — lives in the task record.

## Layout

```text
app/
├── main.py          FastAPI app factory (initialisation only)
├── api/
│   ├── routers/     one module per API group — thin, no agent logic
│   ├── deps.py      shared FastAPI dependencies
│   ├── schemas.py   Pydantic request/response contracts
│   └── websocket.py live event stream
├── agent/           state, nodes, graph, runner, tasks, approvals, events
├── models/          ModelProvider interface + Groq/Mistral + router
├── tools/           tool registry and permission classification
├── mcp/             MCP client/session, source adapter, bundled servers
└── core/            config, logging, error types
```

The layering is strict: API → runner → LangGraph → tool registry → MCP. Routes
never call a model, an MCP server, or a tool directly.

## Permissions

Every tool resolves to `SAFE`, `CONFIRM` or `RESTRICTED`. Unclassified tools are
`RESTRICTED` — classification is opt-in, never inferred. `RESTRICTED` tools are
not even offered to the model.

A `CONFIRM` tool parks the run and waits:

1. The agent registers an approval request and blocks.
2. A `permission_required` event goes out over the WebSocket, carrying
   `request_id`. The task reports status `permission_required`.
3. The client calls `POST /api/permissions/{request_id}/approve` (or `/deny`).
4. The agent wakes up and either runs the tool or tells the model the user
   declined, so it can explain rather than fail.

Unanswered requests expire after `PERMISSION_TIMEOUT_SECONDS`; the agent is
told the request timed out rather than hanging forever.

A client that already knows it wants a tool can pre-approve it and skip the
round trip:

```json
{"message": "Open VS Code", "approved_tools": ["open_application"]}
```

A tool can declare its own level through MCP metadata
(`{"nexus": {"permission": "SAFE"}}`), which takes precedence over the baseline
table in `app/tools/permissions.py`.

## MCP

macOS capabilities live in a separate project, [`../nexus-mac-mcp`](../nexus-mac-mcp),
installed here as an editable dependency. The backend launches it over stdio as
a child process during application startup and keeps the MCP session pool open
until shutdown.

It exposes twenty-five tools — system state, read-only filesystem access,
workspace detection and repository overview, read-only Git, managed-process
views and a loopback health check (all SAFE), plus `open_application`,
`run_command`, `start_process`, `stop_process`, `save_memory` and
`delete_memory` (CONFIRM). The backend discovers them through MCP; no tool is
hard-coded into the API, and there are deliberately no `/api/files`,
`/api/git`, `/api/workspace` or `/api/processes` endpoints.

Filesystem access is confined to a configured workspace (`$HOME` by default,
set with `NEXUS_MAC_ALLOWED_ROOTS`) and refuses secret files. There is no
terminal tool: commands must match an explicit profile, and development servers
may only bind to loopback.

Point at a different server with `MCP_SERVER_COMMAND` / `MCP_SERVER_ARGS`, or
run this one standalone with:

```bash
uv run python -m nexus_mac_mcp
```
