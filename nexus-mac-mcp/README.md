# NEXUS Mac MCP

A local MCP server giving NEXUS controlled access to macOS.

It is started by the NEXUS backend as a child process and spoken to over stdio.
There is no network listener, and it must never be given one.

```text
NEXUS backend
     │  spawns
     ▼
NEXUS Mac MCP  ── stdio ──  MCP protocol
     │
     ▼
   macOS
```

## Tools

| Tool | Permission | What it does |
| --- | --- | --- |
| `battery_status` | SAFE | Charge percentage, charging state, time remaining |
| `system_info` | SAFE | macOS version, architecture, hostname, CPU count |
| `running_processes` | SAFE | Busiest processes by CPU. Cannot signal anything |
| `list_directory` | SAFE | One directory's contents. Does not recurse |
| `search_files` | SAFE | Find files by name under a directory |
| `read_file` | SAFE | Read a text file. Refuses secrets, binaries, large files |
| `detect_workspace` | SAFE | What kind of project a directory holds |
| `repo_overview` | SAFE | Bounded project structure, languages, manifests and entry points |
| `git_status` | SAFE | Branch, tracking position, changed files |
| `git_branch` | SAFE | Local branches and the current one |
| `git_log` | SAFE | Recent commits |
| `git_diff` | SAFE | Change summary (`--stat`), never the patch |
| `list_processes` | SAFE | Development processes NEXUS is managing |
| `process_status` | SAFE | Status, runtime and exit code of one process |
| `process_logs` | SAFE | Recent output from a managed process |
| `check_local_service` | SAFE | Whether a loopback service is responding |
| `open_application` | CONFIRM | Opens an installed application by name |
| `run_command` | CONFIRM | Runs an approved developer command |
| `start_process` | CONFIRM | Starts a supervised development server |
| `stop_process` | CONFIRM | Stops one NEXUS started |

There is no terminal tool and no arbitrary shell. `run_command` accepts only
commands that match an explicit profile — see below. The Git tools are four
fixed, read-only commands, not a way to run `git`.

## Command policy

`run_command` is not `execute(command)`. An executable being allowed does not
make every invocation of it allowed; each one has explicit forms:

| Executable | Allowed forms |
| --- | --- |
| `pytest` | `pytest`, `pytest <paths>`, with `-q -v -vv -x --no-header --tb=short` |
| `uv` | `uv run pytest [paths]`, `uv run python -m <approved module>`, `uv run python <script>`, `uv --version` |
| `npm` | `npm run dev`*, `npm run start`*, `npm run build`, `npm run test`, `npm run lint`, `npm test`, `npm --version` |
| `node` | `node <script>`, `node --version` |
| `python` / `python3` | `python -m <approved module>`, `python <script>`, `python --version` |
| `git` | `git status`, `git branch`, `git log`, `git diff --stat`, `git --version` |

\* these never exit, so `run_command` refuses them and points at
`start_process`, which supervises them instead.

| `uvicorn` | `uvicorn <module:app> [--reload] [--host <loopback>] [--port 1024-65535]` |

Approved `-m` modules: `pytest`, `unittest`, `compileall`, `json.tool`.

## Processes

`start_process` runs a command through the *same* policy as `run_command`, then
asks one further question: may this be left running? Only development servers
(`npm run dev`, `npm start`, `uvicorn ...`) may. `pytest` is allowed to run but
not to run forever.

Each process gets its own process group, a bounded 200KB ring buffer per stream
(a server logging for a week cannot grow without limit), and a `process_id`.
That id is the security boundary for stopping things: `stop_process` takes an id
this server issued, never a pid, so there is no way to signal something NEXUS
did not start. Stopping sends SIGTERM to the group, then SIGKILL. When the MCP
server exits — including when the backend kills it — everything it started is
terminated, so no orphaned dev servers are left behind.

A port already in use is reported, never cleared: killing whatever holds it is
not a decision this layer gets to make.

Deliberately absent: `npx` (fetches and runs arbitrary packages), every
installer (`pip install`, `uv add`, `uv sync`, `npm install`), inline code
(`python -c`, `node -e`), and anything that writes to a repository
(`git push/commit/reset/clean/checkout`).

Each tool declares its level in MCP metadata:

```json
{"nexus": {"permission": "CONFIRM"}}
```

This server **does not enforce permissions**. It says what each tool is; the
NEXUS backend's policy and approval broker decide whether a call runs. There is
deliberately no second permission system here.

## Security

**Filesystem confinement.** Every path is resolved first — `~`, relative
segments, `..` and symlinks all collapse to a real location — and only then
checked against the allowed roots (`$HOME` by default, set with
`NEXUS_MAC_ALLOWED_ROOTS`). A symlink pointing at `/etc` resolves to `/etc` and
is rejected like any other outside path. Searches never descend through links.
System directories and credential directories (`.ssh`, `.aws`, `.gnupg`,
`.kube`, ...) are denied outright, independently of the allowlist.

**Secrets.** A conservative name-based policy covers `.env`, `.env.*`, `*.pem`,
`*.key`, `id_rsa`/`id_ed25519`, `credentials.json`, `.netrc`, `.npmrc` and
similar. The rule is consistent: such files can be *seen* — a listing shows the
name, flagged `protected` — but never *read*.

**Output limits.** Directory entries, search matches, file size, search depth,
Git log entries, diff lines, process counts and command output are all bounded,
so no tool can flood the model's context.

**Command execution.** No shell is involved at any point — no `shell=True`, no
`os.system`, no `/bin/sh -c`. Commands run as an argv list, so the model's
tokens can only ever be arguments, never syntax. Shell metacharacters are not
escaped, they are refused: the command text must match `[A-Za-z0-9 ._/=+:@-]+`,
so `pytest && rm -rf /` dies before tokenisation. The executable is resolved on
a fixed PATH rather than the caller's. Each command runs in its own process
group with a timeout (SIGTERM, then SIGKILL) so children cannot outlive it.

**Network.** A development server may only bind to a loopback address; the
policy refuses `--host 0.0.0.0` and any real address, so NEXUS cannot expose one
to the network. `check_local_service` is the mirror of that on the client side:
only `127.0.0.1`, `localhost` and `::1` can be reached, redirects are never
followed (a local service could otherwise use it as a proxy to anywhere), URLs
carrying credentials are refused, and the response body is never returned.

**Command environment.** A command never inherits this process's environment —
that would hand it `GROQ_API_KEY` and everything else the operator exported. It
is built instead: `HOME`, `USER`, `LOGNAME`, `LANG`, `LC_ALL`, `LC_CTYPE`,
`TMPDIR` and `TZ` by name, plus a fixed set (`TERM=dumb`, `NO_COLOR`, `CI`,
`PYTHONUNBUFFERED`, `PYTHONDONTWRITEBYTECODE`, `GIT_TERMINAL_PROMPT=0`, npm
quiet flags) and the controlled `PATH`. Everything else is dropped.

- No shell. Every command is a fixed argv list against an absolute path.
- Caller input never becomes a command. For `open_application` the name is only
  used to *look up* a bundle among those found by scanning the standard
  application directories; what gets launched is the path this server resolved
  itself. An unknown name is an error, never a guess.
- `running_processes` reports executable names, not full command lines, which
  routinely carry paths and tokens.
- `system_info` withholds serial numbers, user accounts and network addresses.
- No arbitrary execution, no filesystem writes, no deletion, no settings
  changes, no input control. See `tools/files.py` for why filesystem access is
  not here yet.

## Run

Normally the backend starts it. To run it standalone:

```bash
uv run python -m nexus_mac_mcp     # or: uv run nexus-mac-mcp
```

It exits immediately with `NEXUS Mac MCP requires macOS.` on any other
platform.

## Test

```bash
uv run pytest                  # unit tests, nothing touches your apps
uv run pytest -m integration   # opt-in: really opens TextEdit
```

Integration tests are excluded by default so a normal run never opens windows
on your machine.

## Layout

```text
src/nexus_mac_mcp/
├── __main__.py       entry point: platform guard, then stdio
├── server.py         registers the tools and their permission metadata
├── tools/
│   ├── system.py     battery_status, system_info, running_processes
│   ├── applications.py  open_application and safe name resolution
│   ├── files.py      list_directory, search_files, read_file
│   ├── workspace.py  workspace detection and repo overview (no commands)
│   ├── git.py        four fixed read-only Git commands
│   ├── commands.py   run_command: execution, limits, timeout, cleanup
│   ├── processes.py  start/list/status/logs/stop
│   └── network.py    check_local_service (loopback only)
└── core/
    ├── filesystem.py   the single place path safety is decided
    ├── commands.py     the command policy: allowlist and profiles
    ├── process_policy.py  which commands may run in the background
    ├── process_manager.py lifecycle, process groups, ring buffers
    ├── environment.py  what a command is allowed to see
    ├── permissions.py  permission metadata (declaration only)
    └── platform.py     macOS guard and shell-free subprocess helper
```
