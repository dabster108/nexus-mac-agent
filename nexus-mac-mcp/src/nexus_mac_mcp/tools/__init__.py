"""Tool implementations, grouped by capability area.

The functions here are plain Python and know nothing about MCP;
:mod:`nexus_mac_mcp.server` is what registers them as tools.
"""

from nexus_mac_mcp.tools.applications import (
    installed_applications,
    open_application,
    resolve_application,
)
from nexus_mac_mcp.tools.commands import run_command
from nexus_mac_mcp.tools.files import list_directory, read_file, search_files
from nexus_mac_mcp.tools.git import git_branch, git_diff, git_log, git_status
from nexus_mac_mcp.tools.network import check_local_service
from nexus_mac_mcp.tools.processes import (
    list_processes,
    process_logs,
    process_status,
    start_process,
    stop_process,
)
from nexus_mac_mcp.tools.system import battery_status, running_processes, system_info
from nexus_mac_mcp.tools.workspace import detect_workspace, repo_overview

__all__ = [
    "battery_status",
    "check_local_service",
    "detect_workspace",
    "git_branch",
    "git_diff",
    "git_log",
    "git_status",
    "installed_applications",
    "list_directory",
    "list_processes",
    "open_application",
    "process_logs",
    "process_status",
    "read_file",
    "repo_overview",
    "resolve_application",
    "run_command",
    "running_processes",
    "start_process",
    "stop_process",
    "search_files",
    "system_info",
]
