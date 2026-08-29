/**
 * Friendly labels for MCP tools the backend discovers at /api/tools.
 * Descriptions come from the server; these group and shorten names for the UI.
 */

export const TOOL_CATEGORIES = [
  { id: "system", label: "System", tools: ["battery_status", "system_info", "running_processes"] },
  { id: "workspace", label: "Workspace & Git", tools: [
    "detect_workspace", "repo_overview", "git_status", "git_branch", "git_log", "git_diff",
  ]},
  { id: "files", label: "Files", tools: ["list_directory", "search_files", "read_file"] },
  { id: "processes", label: "Processes", tools: [
    "start_process", "list_processes", "process_status", "process_logs", "stop_process",
  ]},
  { id: "commands", label: "Commands", tools: ["run_command"] },
  { id: "network", label: "Network", tools: ["check_local_service"] },
  { id: "memory", label: "Memory", tools: [
    "list_memories", "get_memory", "save_memory", "delete_memory", "verify_memory",
  ]},
  { id: "apps", label: "Applications", tools: ["open_application"] },
];

/** Short human label for a tool name. */
export function toolLabel(name) {
  return (
    {
      battery_status: "Battery",
      system_info: "System info",
      running_processes: "Running apps",
      detect_workspace: "Find workspace",
      repo_overview: "Project overview",
      git_status: "Git status",
      git_branch: "Current branch",
      git_log: "Recent commits",
      git_diff: "Uncommitted changes",
      list_directory: "List folder",
      search_files: "Search files",
      read_file: "Read file",
      run_command: "Run command",
      start_process: "Start server",
      list_processes: "Managed processes",
      process_status: "Process status",
      process_logs: "Process logs",
      stop_process: "Stop process",
      check_local_service: "Check URL",
      list_memories: "List memories",
      get_memory: "Recall memory",
      save_memory: "Remember fact",
      delete_memory: "Forget fact",
      verify_memory: "Verify memory",
      open_application: "Open app",
    }[name] ?? name.replaceAll("_", " ")
  );
}

/** Example prompts tied to real tools — shown on an empty conversation. */
export const TOOL_EXAMPLES = [
  { label: "What's my battery at?", hint: "reads battery_status" },
  { label: "Continue where I left off", hint: "workspace, git, processes" },
  { label: "What changed in git?", hint: "git_status and git_log" },
  { label: "What can you do on my Mac?", hint: "lists connected tools" },
];

export function groupTools(tools) {
  const byName = new Map(tools.map((tool) => [tool.name, tool]));
  const used = new Set();

  const groups = TOOL_CATEGORIES.map((category) => {
    const items = category.tools
      .map((name) => byName.get(name))
      .filter(Boolean);
    items.forEach((tool) => used.add(tool.name));
    return { ...category, items };
  }).filter((group) => group.items.length > 0);

  const other = tools.filter((tool) => !used.has(tool.name));
  if (other.length) {
    groups.push({ id: "other", label: "Other", items: other });
  }

  return groups;
}

export function permissionHint(permission) {
  if (permission === "CONFIRM") return "asks before running";
  if (permission === "RESTRICTED") return "never runs";
  return "read-only";
}
