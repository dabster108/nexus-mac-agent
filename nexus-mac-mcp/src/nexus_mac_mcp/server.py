"""The NEXUS Mac MCP server.

Registers the macOS capabilities as MCP tools and serves them over stdio. Each
tool declares its permission level in metadata; the NEXUS backend reads that at
discovery time and enforces it. This server never decides whether a call is
allowed — it only says what kind of thing each tool is.

stdout is the MCP transport. Never print to it.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from nexus_mac_mcp.core import permissions, process_manager
from nexus_mac_mcp.core.memory_types import MemorySource, MemoryType
from nexus_mac_mcp.core.permissions import CONFIRM, SAFE
from nexus_mac_mcp.tools import (
    applications,
    commands,
    files,
    git,
    memory,
    network,
    processes,
    system,
    workspace,
)

SERVER_NAME = "nexus-mac"
VERSION = "0.1.0"

# Module level: `from __future__ import annotations` defers annotation
# evaluation to introspection time, which resolves names against the module's
# globals, not a function's locals — these must live here, not inside
# create_server(), or MCP's schema generation fails with a NameError.
#: The model naturally writes "project", not "PROJECT" — the enum lists both
#: cases so the vendor's own schema validation (which runs before any of our
#: code, and rejects a call outright rather than passing it through) accepts
#: either. `_parse_type`/parsing in tools/memory.py is already case-insensitive
#: for calls that bypass schema validation entirely (direct/test calls).
_MEMORY_TYPES = [t.value for t in MemoryType] + [t.value.lower() for t in MemoryType]
_MEMORY_SOURCES = [s.value for s in MemorySource] + [s.value.lower() for s in MemorySource]

INSTRUCTIONS = """Controlled access to the local Mac.

Read-only tools report on the machine, its files and its Git repositories.
Tools that change something are marked CONFIRM and are gated by NEXUS before
they run. Filesystem access is confined to a configured workspace.
"""


def create_server() -> MCPServer:
    """Build the server with every tool registered."""
    server = MCPServer(name=SERVER_NAME, instructions=INSTRUCTIONS, version=VERSION)

    @server.tool(
        name="battery_status",
        description=(
            "Get this Mac's battery status: charge percentage, whether it is "
            "charging, and the estimated time remaining."
        ),
        meta=SAFE,
    )
    def battery_status() -> dict[str, Any]:
        return system.battery_status()

    @server.tool(
        name="system_info",
        description=(
            "Get basic information about this Mac: macOS version, architecture, "
            "hostname and CPU count."
        ),
        meta=SAFE,
    )
    def system_info() -> dict[str, Any]:
        return system.system_info()

    @server.tool(
        name="running_processes",
        description=(
            "List the busiest processes running on this Mac, with their CPU and "
            "memory use. Read-only: this cannot stop or signal a process."
        ),
        meta=SAFE,
    )
    def running_processes(
        limit: Annotated[
            int,
            Field(
                default=system.DEFAULT_PROCESSES,
                ge=1,
                le=system.MAX_PROCESSES,
                description="How many processes to return, busiest first.",
            ),
        ] = system.DEFAULT_PROCESSES,
    ) -> dict[str, Any]:
        return system.running_processes(limit)

    @server.tool(
        name="open_application",
        # The first sentence becomes the user's approval prompt, so it is kept
        # short and free of examples.
        description=(
            "Open an installed macOS application by name. "
            "Examples: 'Visual Studio Code', 'Safari', 'Finder'."
        ),
        # Only the application's *presence* can be checked from here. Whether a
        # window actually appeared would need the GUI automation this project
        # deliberately does not have, so the backend reports that as UNKNOWN.
        meta=permissions.meta(
            permissions.Permission.CONFIRM,
            verification={"type": "application", "name_from": "arguments"},
            purpose="Open an installed macOS application.",
        ),
    )
    def open_application(
        application: Annotated[
            str, Field(description="The application's name, as shown in Finder.")
        ],
    ) -> dict[str, Any]:
        return applications.open_application(application)

    # --- filesystem (SAFE, read-only) --------------------------------
    @server.tool(
        name="list_directory",
        description=(
            "List the contents of a directory on this Mac, for example "
            "'~/Projects'. Does not recurse."
        ),
        meta=SAFE,
    )
    def list_directory(
        path: Annotated[str, Field(description="Directory to list. '~' is expanded.")],
    ) -> dict[str, Any]:
        return files.list_directory(path)

    @server.tool(
        name="search_files",
        description=(
            "Find files and folders whose name contains the query, searching "
            "under a directory. Use this to locate a project or a document."
        ),
        meta=SAFE,
    )
    def search_files(
        query: Annotated[str, Field(description="Text to look for in file names.")],
        path: Annotated[
            str | None,
            Field(default=None, description="Directory to search under. Defaults to home."),
        ] = None,
    ) -> dict[str, Any]:
        return files.search_files(query, path)

    @server.tool(
        name="read_file",
        description=(
            "Read the contents of a text file. Large files, binary files and "
            "files that may hold credentials are refused."
        ),
        meta=SAFE,
    )
    def read_file(
        path: Annotated[str, Field(description="File to read. '~' is expanded.")],
    ) -> dict[str, Any]:
        return files.read_file(path)

    # --- workspace (SAFE) --------------------------------------------
    @server.tool(
        name="detect_workspace",
        description=(
            "Work out what kind of developer project a directory holds — its "
            "languages, frameworks, and whether it is a Git repository."
        ),
        meta=SAFE,
    )
    def detect_workspace(
        path: Annotated[str, Field(description="Project directory to inspect.")],
    ) -> dict[str, Any]:
        return workspace.detect_workspace(path)

    @server.tool(
        name="repo_overview",
        description=(
            "Create a bounded map of a repository or project: its structure, "
            "languages, manifests, entry points, and project type. Read-only; "
            "does not read source contents or run commands."
        ),
        meta=SAFE,
    )
    def repo_overview(
        path: Annotated[str, Field(description="Project directory to inspect.")],
        depth: Annotated[
            int,
            Field(
                default=workspace.DEFAULT_OVERVIEW_DEPTH,
                ge=1,
                le=workspace.MAX_OVERVIEW_DEPTH,
                description="How many directory levels to include.",
            ),
        ] = workspace.DEFAULT_OVERVIEW_DEPTH,
    ) -> dict[str, Any]:
        return workspace.repo_overview(path, depth)

    # --- git (SAFE, read-only) ---------------------------------------
    @server.tool(
        name="git_status",
        description=(
            "Get the Git status of a project: current branch, how far ahead or "
            "behind it is, and which files have changed."
        ),
        meta=SAFE,
    )
    def git_status(
        path: Annotated[str, Field(description="A directory inside a Git repository.")],
    ) -> dict[str, Any]:
        return git.git_status(path)

    @server.tool(
        name="git_branch",
        description="List the local Git branches of a project and which one is checked out.",
        meta=SAFE,
    )
    def git_branch(
        path: Annotated[str, Field(description="A directory inside a Git repository.")],
    ) -> dict[str, Any]:
        return git.git_branch(path)

    @server.tool(
        name="git_log",
        description="List recent Git commits for a project, newest first.",
        meta=SAFE,
    )
    def git_log(
        path: Annotated[str, Field(description="A directory inside a Git repository.")],
        limit: Annotated[
            int,
            Field(
                default=git.DEFAULT_LOG_LIMIT,
                ge=1,
                le=git.MAX_LOG_LIMIT,
                description="How many commits to return.",
            ),
        ] = git.DEFAULT_LOG_LIMIT,
    ) -> dict[str, Any]:
        return git.git_log(path, limit)

    @server.tool(
        name="git_diff",
        description=(
            "Summarise uncommitted Git changes in a project: which files "
            "changed and by how many lines. Does not return the patch itself."
        ),
        meta=SAFE,
    )
    def git_diff(
        path: Annotated[str, Field(description="A directory inside a Git repository.")],
        staged: Annotated[
            bool,
            Field(default=False, description="Summarise staged changes instead."),
        ] = False,
    ) -> dict[str, Any]:
        return git.git_diff(path, staged)

    # --- commands (CONFIRM) ------------------------------------------
    @server.tool(
        name="run_command",
        description=(
            "Run an approved developer command in a project directory, such as "
            "'pytest', 'uv run pytest' or 'npm run build'. Only a fixed set of "
            "commands and argument shapes is permitted; anything else is refused."
        ),
        meta=permissions.meta(
            permissions.Permission.CONFIRM,
            prompt="Run {command} in {working_directory}",
            # The result already proves the outcome. Re-running a test suite to
            # confirm a test suite would be both wasteful and, for anything
            # with side effects, wrong.
            verification={"type": "exit_code"},
            purpose="Run one approved developer command in a project directory.",
        ),
    )
    def run_command(
        command: Annotated[
            str,
            Field(description="The command, e.g. 'pytest tests' or 'npm run build'."),
        ],
        working_directory: Annotated[
            str, Field(description="The project directory to run it in.")
        ],
    ) -> dict[str, Any]:
        return commands.run_command(command, working_directory)

    # --- processes ---------------------------------------------------
    @server.tool(
        name="start_process",
        description=(
            "Start a long-running development server and leave it running, for "
            "example 'npm run dev' or 'uvicorn app.main:app --reload'. Returns a "
            "process_id for checking on it later."
        ),
        meta=permissions.meta(
            permissions.Permission.CONFIRM,
            prompt="Start {command} in {working_directory}",
            # Launching is not the goal — staying up is. The backend re-reads
            # the process and, when the result carries a URL, asks whether
            # anything is answering on it.
            verification={
                "type": "process",
                "process_id_from": "result",
                "url_from": "result",
            },
            purpose="Start an approved local development process.",
        ),
    )
    def start_process(
        command: Annotated[
            str, Field(description="The server command, e.g. 'npm run dev'.")
        ],
        working_directory: Annotated[
            str, Field(description="The project directory to run it in.")
        ],
    ) -> dict[str, Any]:
        return processes.start_process(command, working_directory)

    @server.tool(
        name="list_processes",
        description=(
            "List the development processes NEXUS is managing, with their status "
            "and URLs. Does not list other processes on this Mac."
        ),
        meta=SAFE,
    )
    def list_processes() -> dict[str, Any]:
        return processes.list_processes()

    @server.tool(
        name="process_status",
        description=(
            "Get the status, runtime and exit code of a managed process. "
            "Call list_processes first to find the process_id."
        ),
        meta=SAFE,
    )
    def process_status(
        process_id: Annotated[str, Field(description="Id from start_process.")],
    ) -> dict[str, Any]:
        return processes.process_status(process_id)

    @server.tool(
        name="process_logs",
        description=(
            "Read recent output from a managed process. Useful for checking "
            "whether a development server started cleanly. Call list_processes "
            "first to find the process_id — do not guess one."
        ),
        meta=SAFE,
    )
    def process_logs(
        process_id: Annotated[str, Field(description="Id from start_process.")],
        lines: Annotated[
            int,
            Field(
                default=process_manager.DEFAULT_LOG_LINES,
                ge=1,
                le=process_manager.MAX_LOG_LINES,
                description="How many recent lines of each stream to return.",
            ),
        ] = process_manager.DEFAULT_LOG_LINES,
    ) -> dict[str, Any]:
        return processes.process_logs(process_id, lines)

    @server.tool(
        name="stop_process",
        description=(
            "Stop a development process NEXUS started, together with anything it "
            "spawned. Call list_processes first to find the process_id."
        ),
        meta=permissions.meta(
            permissions.Permission.CONFIRM,
            prompt="Stop the managed process {process_id}",
            verification={"type": "process_stopped", "process_id_from": "arguments"},
            purpose="Stop a development process NEXUS started.",
        ),
    )
    def stop_process(
        process_id: Annotated[str, Field(description="Id from start_process.")],
    ) -> dict[str, Any]:
        return processes.stop_process(process_id)

    # --- local services (SAFE) ---------------------------------------
    @server.tool(
        name="check_local_service",
        description=(
            "Check whether a service on this machine is responding, e.g. "
            "'http://127.0.0.1:8000/health'. Only local addresses can be checked."
        ),
        meta=SAFE,
    )
    def check_local_service(
        url: Annotated[
            str, Field(description="A URL on 127.0.0.1, localhost or ::1.")
        ],
    ) -> dict[str, Any]:
        return network.check_local_service(url)

    # --- memory --------------------------------------------------------

    @server.tool(
        name="list_memories",
        description=(
            "List or search remembered facts (projects, workspaces, decisions, "
            "preferences, workflows, and what the user was last working on). "
            "Call this when the user refers to a project, path or setting "
            "without giving it, or asks what you remember. Each result carries "
            "a confidence_level (HIGH/MEDIUM/LOW) and a stale flag; a stale or "
            "low-confidence memory is a hint about where to look, never an "
            "answer on its own — confirm it with a live tool before relying on it."
        ),
        meta=SAFE,
    )
    def list_memories(
        query: Annotated[
            str | None, Field(default=None, description="Keyword to search for.")
        ] = None,
        type: Annotated[
            str | None,
            Field(default=None, description="Restrict to one memory type.", json_schema_extra={"enum": _MEMORY_TYPES}),
        ] = None,
        limit: Annotated[
            int, Field(default=20, ge=1, le=50, description="Maximum results.")
        ] = 20,
    ) -> dict[str, Any]:
        return memory.list_memories(query, type, limit)

    @server.tool(
        name="get_memory",
        description="Fetch one remembered fact by id, or by its type and key.",
        meta=SAFE,
    )
    def get_memory(
        memory_id: Annotated[
            str | None, Field(default=None, description="A memory id from list_memories.")
        ] = None,
        key: Annotated[str | None, Field(default=None, description="The memory's key.")] = None,
        type: Annotated[
            str | None, Field(default=None, description="Narrows a key lookup.", json_schema_extra={"enum": _MEMORY_TYPES})
        ] = None,
    ) -> dict[str, Any]:
        return memory.get_memory(memory_id, key, type)

    @server.tool(
        name="save_memory",
        description=(
            "Remember one stable fact that will still be useful in a later "
            "session: where a project lives, what a workspace is built with, a "
            "decision the user made and why, a preference, or what they were "
            "working on. Do not save transient state ('the build is broken', "
            "'the server is starting'), raw command output, file contents, or "
            "anything you were not asked to keep and would not need again. "
            "Refused outright if the content looks like a credential."
        ),
        meta=permissions.meta(
            permissions.Permission.CONFIRM,
            prompt="Remember this {type}: {key} = {value}",
        ),
    )
    def save_memory(
        type: Annotated[
            str, Field(description="The kind of fact.", json_schema_extra={"enum": _MEMORY_TYPES})
        ],
        key: Annotated[str, Field(description="A short, stable identifier, e.g. 'nexus_project'.")],
        value: Annotated[dict[str, Any], Field(description="The fact itself, as an object.")],
        source: Annotated[
            str,
            Field(default="USER", description="Who this came from.", json_schema_extra={"enum": _MEMORY_SOURCES}),
        ] = "USER",
    ) -> dict[str, Any]:
        return memory.save_memory(type, key, value, source)

    @server.tool(
        name="delete_memory",
        description=(
            "Forget a remembered fact. Exactly one of memory_id, key, "
            "type/key_contains, or wipe_all is required — there is no default "
            "that deletes anything unfiltered."
        ),
        # No custom prompt template: the arguments actually supplied vary a lot
        # by mode (a single id vs. a bulk filter vs. wipe_all), and the generic
        # "description + supplied arguments" rendering already reads cleanly
        # for all of them without risking "None" showing up in the dialog.
        meta=CONFIRM,
    )
    def delete_memory(
        memory_id: Annotated[str | None, Field(default=None, description="A specific memory id.")] = None,
        key: Annotated[str | None, Field(default=None, description="A specific memory key.")] = None,
        type: Annotated[
            str | None, Field(default=None, description="Delete all of this type.", json_schema_extra={"enum": _MEMORY_TYPES})
        ] = None,
        key_contains: Annotated[
            str | None, Field(default=None, description="Delete all keys containing this text.")
        ] = None,
        wipe_all: Annotated[
            bool, Field(default=False, description="Delete every remembered fact.")
        ] = False,
    ) -> dict[str, Any]:
        return memory.delete_memory(memory_id, key, type, key_contains, wipe_all)

    @server.tool(
        name="verify_memory",
        description=(
            "Record what you just observed about a remembered fact. Use "
            "'confirmed' when a live tool result agreed with it, and 'stale' "
            "when a live result contradicted it. This never changes what is "
            "remembered and never deletes anything — it only adjusts how much "
            "the memory should be trusted from now on. To change a value, use "
            "save_memory; to remove one, use delete_memory."
        ),
        meta=SAFE,
    )
    def verify_memory(
        memory_id: Annotated[str, Field(description="A memory id from list_memories.")],
        outcome: Annotated[
            str,
            Field(
                description="'confirmed' if live evidence agreed, 'stale' if it disagreed.",
                json_schema_extra={"enum": ["confirmed", "stale"]},
            ),
        ],
    ) -> dict[str, Any]:
        return memory.verify_memory(memory_id, outcome)

    return server


server = create_server()
