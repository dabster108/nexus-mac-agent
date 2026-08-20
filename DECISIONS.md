# NEXUS — Architecture Decisions

This document describes NEXUS as it is actually built. Every mechanism, limit
and file path below was read out of the source, not designed on paper. Where
something is not implemented, it appears in §15 rather than being described in
the present tense.

Three projects, all in this repository:

| Project | What it is | Language |
|---|---|---|
| `backend/` | FastAPI service + LangGraph agent runtime | Python (uv) |
| `nexus-mac-mcp/` | A standalone MCP server exposing this Mac | Python (uv) |
| `frontend/` | The interface | Next.js 16 / React 19, JavaScript |

---

## 1. What NEXUS is

NEXUS is a local AI operating layer for one macOS machine. You talk to it in
ordinary language; it can look at your workspace, your git state, your running
processes and local services, remember things you tell it, notice when
something changes, and — with your explicit approval each time — start and stop
development processes, run an approved command, or open an application.

Three properties define it, and most of the architecture exists to hold them:

**It is local.** The model API is the only network call NEXUS makes on its own
behalf. Memory is a SQLite file at `~/.nexus/nexus.db`. Tasks, observations and
suggestions live in the backend process and are gone when it restarts. There is
no account, no cloud sync and no telemetry.

**It cannot act without you.** Every tool that changes anything is classified
CONFIRM and blocks on a human decision. There is no "autopilot", no setting
that pre-approves a class of actions for the future, and no code path that
executes a tool without either a SAFE classification or an approval that a
person granted for that specific call.

**It does not claim more than it knows.** A tool returning successfully is not
treated as the goal being achieved. Where a tool declares what success looks
like, NEXUS checks independently and reports SUCCESS, PARTIAL_SUCCESS, FAILED
or UNKNOWN, with the evidence it used and marked for whether it observed that
evidence or inferred it.

What NEXUS is *not*: it does not control your mouse or keyboard, does not drive
a browser, does not use AppleScript, does not read your email or calendar, and
does not run arbitrary shell commands. Those are not missing features awaiting
a later phase — refusing them is what makes the approval model meaningful.

---

## 2. The complete architecture flow

```
                 ┌───────────────────────────────────────┐
  Browser        │  Next.js frontend  (localhost:3000)   │
                 └───────┬───────────────────────┬───────┘
                POST /api/chat            ws /api/ws
                 REST reads                (events)
                         │                       │
                 ┌───────▼───────────────────────▼───────┐
                 │  FastAPI backend   (127.0.0.1:8000)   │
                 │                                       │
                 │  AgentRunner ──► LangGraph StateGraph │
                 │       │            agent ⇄ tools      │
                 │       │                               │
                 │       ├── ContextCollector            │
                 │       ├── MissionEngine               │
                 │       ├── ApprovalBroker              │
                 │       ├── Verifier                    │
                 │       ├── ObservationScheduler        │
                 │       └── SuggestionEngine            │
                 └───────────────┬───────────────────────┘
                        MCP over stdio (JSON-RPC)
                 ┌───────────────▼───────────────────────┐
                 │  nexus-mac-mcp  (child process)       │
                 │  24 tools · macOS · ~/.nexus/nexus.db │
                 └───────────────────────────────────────┘
                                 │
                         Model API (Groq / Mistral)
```

### The path of one message

1. `POST /api/chat` (`app/api/routers/chat.py`) validates the message and
   returns a `task_id` immediately. The work runs as a background task; the
   HTTP response never waits for the model.
2. `AgentRunner.run` (`app/agent/runner.py`) creates a `TaskRecord` in the
   in-memory `TaskStore` and emits `task_started`.
3. `looks_like_mission()` (`app/mission/detection.py`) decides — with a
   deterministic regex heuristic, not a model call — whether this is a
   multi-step objective. If yes, control goes to the `MissionEngine` (§7);
   otherwise it continues as a single turn.
4. The `ContextCollector` (`app/context/collector.py`) classifies intent, then
   gathers only what that intent needs: relevant memories, workspace and git
   state, running processes, recent tasks, recent observations. It emits
   `memory_retrieved` and `context_collected`.
5. An MCP session opens (`app/mcp/registry.py`) and the tool registry is built
   from the server's advertised tools.
6. The LangGraph graph is compiled and run: `agent` → (tools needed?) →
   `tools` → `agent` → … → END.
7. In the tool node, each call is classified. SAFE runs immediately. CONFIRM
   parks in the `ApprovalBroker` and the node *blocks* until a person answers
   through `POST /api/permissions/{id}/approve|deny`.
8. After a tool that declares a verification contract succeeds, the `Verifier`
   independently re-checks the world using SAFE tools only and emits
   `verification_completed` with an outcome and evidence.
9. The final message is emitted as `agent_message`; `TaskStore.finish` records
   the response and emits `task_completed`.
10. Every step of that emitted an `ExecutionEvent` onto one WebSocket, and
    appended it to the `TaskRecord`. `GET /api/tasks/{id}/trace` later projects
    those same recorded events into an explanation (§12).

### Why events are emitted, not returned

LangGraph only surfaces a node's state update when the node *returns*. A tool
node blocked on an approval has not returned — so if events only travelled in
state, the browser would never see the request it is being asked to answer.
Nodes therefore call an `EventSink` as they go *and* return the events in
state. This is documented at `app/agent/events.py:99`.

---

## 3. MCP: what it is here and how it is used

The Model Context Protocol is the boundary between "the agent" and "this Mac".
NEXUS uses it as a real process boundary, not a library convention.

- **Transport**: stdio. The backend spawns `python -m nexus_mac_mcp` as a child
  process (`MCP_SERVER_COMMAND` / `MCP_SERVER_ARGS`, defaulting to the same
  interpreter) and speaks JSON-RPC over its pipes. Nothing is listening on a
  port; nothing else on the machine can reach the tools.
- **Lifetime**: one session per request, opened through an `AsyncExitStack` in
  `AgentRunner._open_registry` and closed when the request ends.
- **Discovery**: the backend calls `list_tools` and builds its registry from
  whatever the server advertises. The backend has no hardcoded list of tool
  names.

### The `nexus` metadata namespace

An MCP server declares NEXUS-specific facts under `_meta["nexus"]`
(`META_NAMESPACE` in `app/mcp/registry.py`). A tool declares:

| Key | Meaning |
|---|---|
| `permission` | `SAFE`, `CONFIRM` or `RESTRICTED` |
| `prompt` | Template for the approval question, e.g. `"Run {command} in {working_directory}"` |
| `purpose` | One line, shown in the trace |
| `verification` | The contract describing what success looks like (§11) |

Three deliberate limits on how far a server is trusted:

- An **unclassified tool is not treated as safe.** `classify()` in
  `app/tools/permissions.py` decides the level, and the declaration is an input
  to that decision, not the final word. `DEFAULT_PERMISSION_LEVEL` is
  `RESTRICTED`: classification is opt-in and never inferred, so a tool that
  says nothing about itself is the most restricted thing in the system, not the
  least.
- **Prompt templates are bounded** — `MAX_PROMPT_TEMPLATE = 200` characters.
- **Verification contracts are allowlisted.** `KNOWN_VERIFICATION_TYPES` is
  `{process, process_stopped, local_service, exit_code, application}`. A
  contract naming anything else is dropped rather than trusted: a server cannot
  invent a new kind of verification by asserting one.

`app/mcp/registry.py` is the only module that knows MCP exists. Everything
above it speaks `ToolDefinition` / `ToolResult`.

---

## 4. Tool architecture

Twenty-four tools, all in `nexus-mac-mcp`. Eighteen SAFE, six CONFIRM.

**SAFE — read-only, run without asking:**

| Area | Tools |
|---|---|
| System | `system_info`, `battery_status` |
| Workspace | `detect_workspace`, `list_directory`, `read_file`, `search_files` |
| Git | `git_status`, `git_branch`, `git_log`, `git_diff` |
| Processes | `list_processes`, `running_processes`, `process_status`, `process_logs` |
| Network | `check_local_service` |
| Memory | `get_memory`, `list_memories`, `verify_memory` |

**CONFIRM — changes something, always asks:**

`run_command`, `start_process`, `stop_process`, `open_application`,
`save_memory`, `delete_memory`

Two things are worth noting about that split. `verify_memory` is SAFE because
confirming a memory is still true only reads the world. And both memory writes
are CONFIRM: NEXUS asks before changing what it believes about you, for the
same reason it asks before touching a process.

### Structure inside the MCP server

`server.py` declares tools and their metadata; `tools/*.py` are thin adapters;
`core/*.py` holds the enforcement — and enforcement lives in `core`, below the
tool layer, so a new tool cannot accidentally route around it:

- `core/filesystem.py` — path resolution, allowed roots, denied home
  subdirectories, secret-file patterns, a 100 KB read cap.
- `core/commands.py` — the command allowlist, expressed as **profiles and
  forms**, not a string blocklist. `pytest`, `uv`, `npm`, `node`, `python`,
  `uvicorn`, `git` each declare the exact argument shapes permitted: which
  prefixes, which flags, which options and what may trail. `npm run build` is
  allowed; `npm run anything-else` is not a recognised form and is refused.
  There is no shell — no pipes, no redirection, no `&&`.
- `core/process_manager.py` / `core/process_policy.py` — which processes NEXUS
  may start, and tracking the ones it did.
- `core/memory_store.py`, `core/memory_types.py`, `core/memory_secrets.py` —
  the SQLite memory store and its secret screening.

---

## 5. The approval system

One broker, one decision point, one moment of human responsibility.

`PermissionPolicy` (`app/tools/permissions.py`) answers "may this call run
now?". `ApprovalBroker` (`app/agent/approvals.py`) owns the pending requests.

The flow:

1. The tool node classifies the call. SAFE → run.
2. CONFIRM → the broker registers a request, `permission_required` is emitted
   with a `request_id`, the tool, the description and the arguments, and the
   node **awaits** `broker.wait()`.
3. The browser sees the event, and also finds the request at
   `GET /api/permissions/pending` (which is what a reconnecting client reads).
4. `POST /api/permissions/{request_id}/approve` or `/deny` resolves it.
5. On approve, the tool runs. On deny, the tool never starts: the model
   receives `"The user denied permission to run 'X'."` and must explain that to
   you. If it asks again for the same tool, the refusal is repeated with
   `"Do not ask again; tell the user instead."`
6. If nobody answers within `PERMISSION_TIMEOUT_SECONDS` (default 300), the
   request expires and is treated as a refusal.

Consequences worth stating plainly:

- **Approval is per call, and expires with the request.** `approved_tools` on
  `POST /api/chat` pre-approves tools for *that one request*; it does not
  persist, and there is no UI that sets it.
- **Denial is not a dedicated event.** It surfaces as `tool_completed` with
  `success: false` and a message naming the refusal. There is exactly one
  vocabulary for "the tool did not run".
- **The frontend has no execute endpoint.** Nothing in `frontend/src/lib/api.js`
  can invoke a tool. Every action the UI offers — including "Forget this
  memory" and every suggestion — is composed as an ordinary chat message and
  goes through the same agent and the same approval prompt as anything you
  typed. `app/api/routers/memory.py` says so in its module docstring, and there
  is deliberately no `DELETE /api/memory/{id}`.

---

## 6. Agent execution

`app/agent/graph.py` compiles a LangGraph `StateGraph` with two nodes:

```
START → agent → should_continue? ──no──→ END
                      │
                     yes
                      ↓
                    tools → after_tools → agent
```

`agent_node` calls the model with the system prompt, the context block and the
conversation so far. `tool_node` executes what the model asked for, subject to
permission. Dependencies — provider, registry, policy, broker, sink — are bound
in with `functools.partial` so the graph itself carries no vendor specifics.

### The bounds, and why each exists

| Bound | Value | Reason |
|---|---|---|
| `AGENT_MAX_ITERATIONS` | 6 | Caps agent↔tool round trips. |
| `MAX_TOOL_CALLS_PER_TURN` | 4 | Caps calls *within* one turn. An earlier version counted only turns, and a model once emitted 250 tool calls in a single turn. `_bounded_tool_calls()` also de-duplicates identical calls. |
| `MAX_TOOL_RESULT_CHARS` | 32,000 | A 2 MB tool result would otherwise become roughly half a million tokens. Truncation is marked in the text the model sees. |
| `REQUEST_TIMEOUT_SECONDS` | 60 | Per model call. |
| `MAX_TASKS` | 200 | The `TaskStore` ring; oldest tasks are evicted. |

### Task state

`TaskStore` (`app/agent/tasks.py`) is an in-memory `OrderedDict` of
`TaskRecord`s. `publish()` appends events to the record *and* broadcasts them
to every WebSocket subscriber, which is why the record and the stream can never
disagree. `GET /api/tasks/{id}` returns the record — that is the endpoint a
client uses to recover an answer it missed while disconnected.

Cancellation: `POST /api/tasks/{id}/cancel` cancels the asyncio task, frees any
pending approval, and emits `task_cancelled`.

### Model providers

`app/models/router.py` selects between Groq and Mistral, configured by
`DEFAULT_MODEL_PROVIDER`, `GROQ_MODEL`, `MISTRAL_MODEL`. Model identifiers are
deliberately **not** defaulted in `config.py` — the operator names a model their
account actually has. When a provider does not offer the configured model, the
task fails with `"Groq does not offer the configured model."` rather than
silently substituting another.

---

## 7. Missions: multi-step objectives

A mission is what happens when one message implies several ordered actions.

**Detection is deterministic** (`app/mission/detection.py`). Either the message
matches a trigger pattern (`prepare`, `set up`, `development environment`,
`mission`, or a "why isn't X working" shape), or it contains two or more
clauses each beginning with an action verb (`start`, `stop`, `restart`, `check`,
`run`, `inspect`, `read`, `list`, `detect`, `test`, `build`, `open`, `verify`,
`find`, `show`, `diagnose`), split on "and" / "then" / commas.

This is a heuristic and it is wrong in both directions — "Check the battery and
check disk space" is a mission; "Do these two things: first tell me the
battery, then tell me the disk" is not, because neither clause begins with an
action verb. That inaccuracy is a documented limitation (§15), not something
papered over with a classifier call on every message. The cost of the choice is
that an ordinary question pays nothing extra: if it does not look like a
mission, it takes exactly the code path it always did.

**Planning** (`app/mission/planner.py`) makes one model call that returns steps,
each with a description, a tool, suggested arguments, `depends_on`, and
`run_if` (`always` / `on_success` / `on_failure`).

**Execution reuses the same agent graph.** This is the central decision. Each
step runs through `_SingleToolSource`, a registry view exposing only that
step's tool, and is executed by the ordinary agent runtime. There is no second
agent, no second permission path and no second event system — a mission step
that needs approval raises the identical `permission_required` and blocks on
the identical broker.

The plan's suggested arguments are a hint from an earlier model call, not
truth. `_instruction_for` quotes the user's objective first and labels it as
authoritative for any path it names.

**Events**: `mission_started`, `mission_plan_created` (carries the full step
list), `mission_step_started/completed/failed/skipped` (each carries `step_id`),
`mission_waiting_approval`, and one of `mission_completed` / `mission_failed` /
`mission_cancelled`. All ride the same WebSocket as everything else. Because
each step is also a task in its own right, a step's own events are mirrored
onto the mission's stream — so a client watching only the mission's `task_id`
sees everything without knowing step task ids in advance.

**Verification failures fail steps.** `_apply_verification` means a step whose
tool returned successfully but whose *outcome* was FAILED does not count as
done, and steps depending on it are skipped rather than run against a broken
precondition.

**Limits**: `MISSION_MAX_STEPS` 30, `MISSION_MAX_RETRIES_PER_STEP` 2,
`MISSION_MAX_TOOL_CALLS` 50, `MISSION_MAX_RUNTIME_SECONDS` 600.

---

## 8. Contextual intelligence

Before planning, NEXUS assembles what it knows. Two decisions shape this.

**Intent classification is deterministic** (`app/context/intent.py`). Regexes,
not a model call, sort a message into `CONTINUE`, `WHAT_CHANGED`, `ORIENT`,
`RECALL`, `INVESTIGATE`, `RECENT` or `GENERAL`, producing a `ContextPlan` that
says which sources to gather. "What am I working on?" needs workspace and
processes; "What did I ask you yesterday?" needs recent tasks and nothing else.

**Relevance scoring is deterministic too** (`app/context/relevance.py`) —
keyword and recency scoring over the candidate set. There are no embeddings, no
vector database and no similarity search anywhere in NEXUS.

The collector reads the candidate set once and scores locally, rather than
letting a display limit decide what the planner sees. A specific bug drove
this: `detect_workspace` reports `is_git_repository: false` for a subdirectory
of a repository, and the collector used to skip `git_status` on that basis —
so the model, with no git facts, invented "main branch, no uncommitted
changes". The collector now always asks Git.

`PlanningContext.to_prompt_block()` is the single place context becomes a
string. Everything is bounded by `CONTEXT_MAX_MEMORIES` (10),
`CONTEXT_MAX_WORKSPACE_FACTS` (20) and `CONTEXT_MAX_CHARS` (4000), and the
`context_collected` event reports what was gathered and whether it was
truncated.

---

## 9. Memory

SQLite at `~/.nexus/nexus.db`, owned by the MCP server, reached only through
tools.

**Seven types**: `USER_PREFERENCE`, `PROJECT`, `WORKSPACE`, `WORKFLOW`,
`DECISION`, `TASK_CONTEXT`, `FACT`.
**Sources**: `USER`, `SYSTEM`, `MISSION`.
**Status**: `PROPOSED`, `ACTIVE`, `STALE`, `DELETED`.
**Confidence**: `HIGH`, `MEDIUM`, `LOW`, alongside `last_verified_at`.

Decisions that matter:

- **Writing is CONFIRM.** `save_memory` and `delete_memory` both ask.
- **Deletion is soft.** Rows move to `DELETED`; a unique index on `(type, key)`
  excludes them so a key can be reused.
- **Confidence decays with age, and can be restored.** `verify_memory` is SAFE
  because re-checking a fact only reads the world.
- **Secrets are screened on the way in** (`core/memory_secrets.py`).
- **"Forget everything" means everything.** Deletion used to reuse `list()`,
  whose `MAX_LIST_LIMIT = 50` is a *display* limit — so a "forget everything"
  over 60 memories left 10 behind. `_match_all()` exists specifically so
  deletion never inherits a display bound.
- **Storage errors do not leak.** Raw `sqlite3`/`OSError` is translated at
  `_connect()` into one unavailable message; the store lookup itself sits
  inside each tool's `try`, so a failure to open the database is reported as
  the same clean error as a failure to read from it.

---

## 10. Proactive intelligence

NEXUS notices things without being asked. What it does with them is tightly
constrained.

### Observations (`app/observations/`)

A scheduler runs deterministic sensors every 10 seconds (`MIN_INTERVAL_SECONDS`
5). No model is involved. Rules cover processes, local services, workspace, git,
memory, missions, tasks, approvals and system state, producing observations of
category `PROCESS`, `SERVICE`, `WORKSPACE`, `GIT`, `MEMORY`, `MISSION`, `TASK`,
`APPROVAL` or `SYSTEM`, at severity `INFO`, `NOTICE`, `WARNING` or `ERROR`.

The store bounds the noise: `MAX_OBSERVATIONS` 200, a dedupe key per
observation, and a 60-second cooldown. Text is redacted and length-capped
before storage. Observations are broadcast as `observation_created` and are
readable at `GET /api/observations`.

An observation states a fact. It never triggers an action.

### Suggestions (`app/suggestions/`)

Rules turn certain observations into an offer: a stopped process, a dead
service, a repeatedly-flapping process, ten or more uncommitted files, a
memory that looks outdated, a failed task, a process running over six hours.

**The critical design decision is what a suggestion may contain.**
`SuggestedAction` holds an intent label, some identifiers, and a natural
language `prompt`. It holds **no tool name and no arguments** — the model in
`app/suggestions/models.py:66` says so, and `to_public_dict()` emits only
`intent` and `prompt`.

Accepting a suggestion sends its prompt to `POST /api/chat` exactly as if you
had typed it. The agent then decides what to do, and a CONFIRM tool still
raises the ordinary approval prompt. There is deliberately no
`POST /api/suggestions/{id}/execute`. `accept` records that you took the offer;
it does not run anything.

Diagnostic suggestions carry `READ_ONLY = "Do not change anything — just tell
me what you find."` in the prompt itself.

Bounds: `MAX_SUGGESTIONS` 50, `DEFAULT_TTL_SECONDS` 3600, and a 30-minute
cooldown after dismissal so the same offer cannot immediately return.

One bug shaped this code: a single process failure once produced two
suggestions, because `outcomes.record()` offered one directly *and* recorded an
observation the engine also converted. The direct offer was removed — there is
one path from noticing to offering.

---

## 11. Verification and outcomes

`tool_completed` has only ever meant "the tool returned". Verification answers
the different question: did it achieve what was asked?

**Contracts come from the tool**, declared in MCP metadata and allowlisted by
the backend (§3). Four tools declare one:

| Tool | Contract | What is checked |
|---|---|---|
| `start_process` | `process` | Is the process still alive, and if it returned a URL, is anything answering there? |
| `stop_process` | `process_stopped` | Is it actually gone? |
| `run_command` | `exit_code` | The result already proves the outcome — re-running a test suite to confirm a test suite would be wasteful and, with side effects, wrong. |
| `open_application` | `application` | Is the application running? |

Read-only tools have no contract and are not "verified" for show. Asking for
your battery level produces no `verification_completed` event, because there is
nothing independent to check.

**The verifier can only use SAFE tools.** `Verifier._call_safe`
(`app/verification/verifier.py`) refuses anything else. Verification cannot
change the world, and cannot retry a failed action.

**Outcomes**: `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`, `UNKNOWN`.

**Evidence is marked by how it was obtained.** `OBSERVED` evidence — NEXUS
looked and saw — may be `HIGH` confidence. `INFERRED` evidence is capped at
`MEDIUM` and rendered with an "(inferred)" marker. The distinction is in the
data model, not in prose.

`SETTLE_SECONDS = 1.5` with `MAX_SETTLE_RETRIES = 1` exists for a real bug:
every process start reported PARTIAL_SUCCESS because the port was checked about
three milliseconds after launch, before any dev server had bound it. One short
re-check — and only while the process is alive — turns that into an honest
SUCCESS without ever waiting on something genuinely dead.

Nothing here remediates. A FAILED outcome is diagnosed and reported; the
frontend's only affordance is "Investigate", which composes a read-only chat
message.

---

## 12. Explainability and the execution trace

`GET /api/tasks/{task_id}/trace` explains what NEXUS did and why.

**The trace is a pure projection of `TaskRecord.events`.** `app/trace/builder.py`
reads events that were already recorded and groups them into steps of kind
`CONTEXT`, `ACTION`, `APPROVAL`, `VERIFICATION`, `OUTCOME` or `MISSION`, each
with a status (`ok`, `failed`, `waiting`, `denied`, `info`, `skipped`). It adds
no new source of truth, and — by construction — cannot show anything that was
not already on the WebSocket.

**No field can hold model reasoning.** The trace answers "which context was
provided, which tool ran, who approved it, what was checked, what came of it".
It does not answer "what was the model thinking", because that is not recorded
anywhere. `app/agent/events.py` opens by saying events carry "never hidden
chain-of-thought, never tool argument values".

One bug is worth recording: `summary` and `outcome_reason` were composed from
text that bypassed `clean()`, so a secret could reach the trace. Both the
composition site and the serialisation site now sanitise.

In the interface, a trace is not a page. It is an expandable panel beneath the
answer it explains, closed by default.

---

## 13. Security architecture

Security here is structural — the safe path is the only path — rather than a
list of checks.

### Boundaries

- **Process boundary.** Tools run in a separate MCP child process over stdio.
  Nothing listens on a port.
- **Network boundary.** The backend binds `127.0.0.1` by default. CORS origins
  are an explicit list, and `_cors_origins()` filters out `*` unconditionally —
  a wildcard cannot be configured, because the agent can act on this Mac.
- **No authentication, and therefore single-user.** Anyone who can reach
  `127.0.0.1:8000` is the user. This is a real constraint on deployment (§15),
  not an oversight.

### Filesystem

`core/filesystem.py` enforces allowed roots (`NEXUS_MAC_ALLOWED_ROOTS`), a
100 KB read cap, and two denial lists that came out of a real audit finding —
`~/.zsh_history`, `~/.git-credentials` and similar were readable:

- `SECRET_FILE_PATTERNS`: `*credentials`, `credentials.*`, `.*history`,
  `rclone.conf`, `*.keychain*`, `*.token` among others.
- `DENIED_HOME_SUBPATHS`: `Library`, `.config/gh` — directories too generic to
  express as a filename pattern.

### Commands

No shell. `core/commands.py` validates against **profiles and forms**: an
allowlist of executables, each declaring the exact argument shapes permitted.
Text is matched against `^[A-Za-z0-9 ._/=+:@-]+$`, which excludes pipes,
redirection and command chaining by construction.

### Secrets

Configuration is the only module allowed to read environment variables.
`Settings` is documented as never serialisable into an API response. Memory
writes are screened for secrets. Observation and trace text passes through
`redact()` / `clean()`. Logging uses `safe_keys()` so argument *names* can be
logged without their values.

### Bounds as a safety property

Every unbounded loop is a denial-of-service on your own machine. Iterations,
tool calls per turn, tool result size, mission steps, mission runtime,
verification steps, task count, observation count, suggestion count, event
buffer — all capped, with the values listed in §6, §7, §10 and §11.

### What is refused outright

Browser automation, AppleScript, GUI/keyboard/mouse control, email, calendar,
arbitrary shell execution, autonomous remediation, and any second path to
executing a tool. These are not on a roadmap.

---

## 14. Five complete request examples

### Example 1 — "What am I working on?"

```
POST /api/chat → task_id
task_started
memory_retrieved       0 relevant memories
context_collected      intent=ORIENT · workspace + processes + git
tool_requested         detect_workspace (SAFE)
tool_started           detect_workspace
tool_completed         success
tool_requested         git_status (SAFE)
tool_completed         success
agent_message          the workspace, the branch, the changed-file count and
                       what is running — read from the tools, not guessed
task_completed
```

No approval, because nothing changed. No verification, because nothing was
supposed to change. The rail's "Understands" section updates from
`GET /api/context`.

### Example 2 — "Run `npm --version` in the frontend"

```
task_started
context_collected      intent=GENERAL
tool_requested         run_command (CONFIRM)
permission_required    request_id=… · "Run npm --version in /Users/…/frontend"
                       ── the tool node blocks here ──
                       ── the composer is replaced by the approval ──
POST /api/permissions/{id}/approve
tool_started           run_command
tool_completed         success
verification_started   run_command
verification_completed SUCCESS · one OBSERVED evidence statement drawn from
                       the exit code
agent_message          the version npm reported
task_completed
```

The outcome card attaches beneath that answer, not to a global list.

### Example 3 — "Run `npm run build` in the frontend" → denied

```
task_started
tool_requested         run_command (CONFIRM)
permission_required    request_id=…
POST /api/permissions/{id}/deny
tool_completed         success=false · "The user denied permission to run
                       'run_command'."
agent_message          "I wasn't able to run `npm run build` because
                       permission to execute that command was denied."
task_completed
```

`tool_started` never fires. Nothing ran. If the model asks a second time, the
refusal comes back with "Do not ask again; tell the user instead."

### Example 4 — "Check the battery level and check how much free disk space I have"

Two clauses beginning with `check`, so the deterministic detector routes this
as a mission.

```
task_started
mission_started        "Check the battery level and check how much free…"
mission_plan_created   steps=[step_1 "Retrieve the current battery charge
                       percentage", step_2 "Report free disk space"]
mission_step_started   step_1
  (the ordinary agent graph, with a registry exposing only battery_status)
  tool_started / tool_completed
mission_step_completed step_1
mission_step_started   step_2
  tool_started / tool_completed
mission_step_completed step_2
mission_completed
agent_message          the wrap-up
task_completed
```

The mission panel renders under the answer, showing `2/2` and each step's real
engine state. Had step 1 failed, step 2 would be `skipped`, and the panel would
say so in words as well as colour.

### Example 5 — A dev server dies, unprompted

No request is involved. The scheduler notices on its next 10-second pass:

```
observation_created    PROCESS · ERROR · "Backend stopped unexpectedly"
suggestion_created     PROCESS · suggested_action = {
                         intent: "investigate_process",
                         prompt: "Do not change anything — just tell me what
                                  you find. The backend process stopped…"
                       }
```

The rail's "Suggested" section shows it. Clicking the action sends that prompt
to `POST /api/chat` — an ordinary message. NEXUS investigates with SAFE tools
and reports. If it then wants to restart the process, that is `start_process`,
which is CONFIRM, which raises an approval prompt exactly like Example 2.

From "something broke" to "something was fixed" there is no step that does not
pass through a human.

---

## 15. Limitations and what NEXUS deliberately does not do

### Known inaccuracies

- **Mission detection is a heuristic** and is wrong in both directions. It is
  documented as such in `app/mission/detection.py` rather than masked by a
  classifier call on every message.
- **Intent classification and relevance scoring are keyword-based.** No
  embeddings, no vector search. A question phrased unusually may not pull the
  context that would have helped.
- **Verification covers four tools.** Everything else reports only that the
  tool returned. That is honest, but it is not complete coverage.
- **The planner's suggested arguments come from a separate model call** and are
  treated as hints, not truth.

### Structural constraints

- **Single machine, single user, no authentication.** Anyone who can reach the
  backend port is the user. Do not expose it beyond localhost.
- **Task state is in memory.** Restarting the backend loses tasks,
  observations, suggestions and pending approvals. Only memory survives, in
  SQLite.
- **`MAX_TASKS = 200`** — older tasks and their traces are evicted.
- **One conversation.** There are no threads, no history across reloads. The
  transcript is a view of the session, not a stored object.
- **Model identifiers are not defaulted.** If your provider retires the model
  named in `.env`, every task fails with a clear message until you change it.

### Capabilities that are refused, not pending

Browser automation · AppleScript · GUI, keyboard or mouse control · email ·
calendar · vector databases or RAG · PostgreSQL, Redis or any server database ·
cloud memory · authentication or multi-user support · arbitrary shell
execution · autonomous remediation · a second approval system · a frontend
execute endpoint.

Each of these would either break the approval model or move NEXUS off the
machine it is meant to be part of.

### The one thing worth restating

NEXUS never acts on its own. It observes on its own, offers on its own, and
explains on its own — but between noticing a problem and changing anything
about your machine there is always a person, and that person is you.
