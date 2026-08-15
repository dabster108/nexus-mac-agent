"""ContextCollector: gathers memory/workspace/machine context via SAFE tools
called directly — never through the model, never above SAFE."""

from __future__ import annotations

from conftest import FakeToolSource, tool_definition

from app.agent.events import EventType, ExecutionEvent
from app.context.collector import ContextCollector
from app.context.intent import MISSION_PLAN
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolRegistry, ToolResult


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ExecutionEvent] = []

    def __call__(self, event: ExecutionEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: EventType) -> list[ExecutionEvent]:
        return [e for e in self.events if e.type is event_type]


async def build_registry(*sources: FakeToolSource) -> ToolRegistry:
    registry = ToolRegistry(list(sources))
    await registry.refresh()
    return registry


def memories_source(memories: list[dict]) -> FakeToolSource:
    return FakeToolSource(
        [tool_definition("list_memories", PermissionLevel.SAFE)],
        {"list_memories": ToolResult(
            content="", structured={"success": True, "count": len(memories), "memories": memories}
        )},
    )


def workspace_source(
    path: str, result: dict, git_result: dict | None = None
) -> FakeToolSource:
    results = {"detect_workspace": ToolResult(content="", structured=result)}
    if git_result is not None:
        results["git_status"] = ToolResult(content="", structured=git_result)
    definitions = [tool_definition("detect_workspace", PermissionLevel.SAFE)]
    if git_result is not None:
        definitions.append(tool_definition("git_status", PermissionLevel.SAFE))
    return FakeToolSource(definitions, results)


def machine_source(system: dict, battery: dict | None = None) -> FakeToolSource:
    results = {"system_info": ToolResult(content="", structured=system)}
    definitions = [tool_definition("system_info", PermissionLevel.SAFE)]
    if battery is not None:
        results["battery_status"] = ToolResult(content="", structured=battery)
        definitions.append(tool_definition("battery_status", PermissionLevel.SAFE))
    return FakeToolSource(definitions, results)


def processes_source(processes: list[dict]) -> FakeToolSource:
    return FakeToolSource(
        [tool_definition("list_processes", PermissionLevel.SAFE)],
        {"list_processes": ToolResult(
            content="", structured={"success": True, "processes": processes}
        )},
    )


# --- memory retrieval --------------------------------------------------


async def test_relevant_memories_are_retrieved() -> None:
    registry = await build_registry(
        memories_source(
            [{"id": "mem_1", "type": "PROJECT", "key": "nexus", "value": {"path": "/x"}, "confidence": 1.0}]
        )
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)
    emit = _Recorder()

    context = await collector.collect("Prepare the nexus project.", "task_1", emit, plan=MISSION_PLAN)

    assert len(context.memories) == 1
    assert context.memories[0].key == "nexus"
    assert emit.of_type(EventType.MEMORY_RETRIEVED)


async def test_unrelated_memories_are_not_included() -> None:
    """Context must not widen into "everything I've saved".

    Phase 10 moved the filtering from the query to :mod:`app.context.relevance`
    — the store is read once and scored locally — so this asserts the outcome
    (an unrelated memory stays out of the prompt) rather than the mechanism.
    """
    registry = await build_registry(
        memories_source(
            [
                {"id": "mem_1", "type": "PROJECT", "key": "nexus",
                 "value": {"path": "/x"}, "confidence": 1.0},
                {"id": "mem_2", "type": "FACT", "key": "dentist_appointment",
                 "value": {"when": "tuesday"}, "confidence": 1.0},
            ]
        )
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    context = await collector.collect(
        "Prepare the nexus project.", "task_1", _Recorder(), plan=MISSION_PLAN
    )

    assert [m.key for m in context.memories] == ["nexus"]


async def test_no_memory_tool_means_no_memories_and_no_crash() -> None:
    registry = await build_registry()  # empty registry
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    context = await collector.collect("anything", "task_1", _Recorder(), plan=MISSION_PLAN)

    assert context.memories == ()


async def test_memory_retrieval_respects_the_budget() -> None:
    many = [
        {"id": f"mem_{i}", "type": "FACT", "key": f"k{i}", "value": {}, "confidence": 1.0}
        for i in range(30)
    ]
    registry = await build_registry(memories_source(many))
    collector = ContextCollector(registry, max_memories=5, max_workspace_facts=20)

    context = await collector.collect("many facts here", "task_1", _Recorder(), plan=MISSION_PLAN)

    assert len(context.memories) <= 5


async def test_a_stale_memory_is_flagged_not_hidden() -> None:
    registry = await build_registry(
        memories_source(
            [{"id": "m", "type": "WORKSPACE", "key": "backend", "value": {"path": "/gone"},
              "confidence": 1.0, "stale": True}]
        )
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    context = await collector.collect("backend workspace", "task_1", _Recorder(), plan=MISSION_PLAN)

    assert context.memories[0].stale is True


# --- workspace detection -----------------------------------------------


async def test_an_explicit_path_in_the_objective_is_verified() -> None:
    registry = await build_registry(
        workspace_source(
            "/Users/x/nexus",
            {"success": True, "path": "/Users/x/nexus", "project_types": ["python"], "is_git_repository": False},
        )
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)
    emit = _Recorder()

    context = await collector.collect("Inspect /Users/x/nexus please.", "task_1", emit, plan=MISSION_PLAN)

    assert len(context.workspaces) == 1
    assert context.workspaces[0].verified is True
    assert context.workspaces[0].project_types == ("python",)
    assert emit.of_type(EventType.WORKSPACE_DETECTED)


async def test_an_explicit_path_wins_over_a_remembered_one() -> None:
    registry = await build_registry(
        memories_source(
            [{"id": "m", "type": "PROJECT", "key": "nexus", "value": {"path": "/remembered"}, "confidence": 1.0}]
        ),
        workspace_source("/explicit/path", {"success": True, "path": "/explicit/path", "project_types": [], "is_git_repository": False}),
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    context = await collector.collect("Inspect /explicit/path now.", "task_1", _Recorder(), plan=MISSION_PLAN)

    assert [w.path for w in context.workspaces] == ["/explicit/path"]


async def test_falls_back_to_a_remembered_path_when_none_is_named() -> None:
    registry = await build_registry(
        memories_source(
            [{"id": "m", "type": "PROJECT", "key": "nexus", "value": {"path": "/remembered/nexus"}, "confidence": 1.0}]
        ),
        workspace_source(
            "/remembered/nexus",
            {"success": True, "path": "/remembered/nexus", "project_types": ["python"], "is_git_repository": False},
        ),
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    context = await collector.collect("Prepare the nexus project for development.", "task_1", _Recorder(), plan=MISSION_PLAN)

    assert [w.path for w in context.workspaces] == ["/remembered/nexus"]


async def test_a_path_that_no_longer_exists_is_reported_unverified() -> None:
    registry = await build_registry(
        workspace_source("/gone", {"success": False, "error": "That path does not exist."})
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)
    emit = _Recorder()

    context = await collector.collect("Inspect /gone please.", "task_1", emit, plan=MISSION_PLAN)

    assert context.workspaces[0].verified is False
    event = emit.of_type(EventType.WORKSPACE_DETECTED)[0]
    assert event.data["verified"] is False


async def test_git_state_is_included_for_a_repository() -> None:
    registry = await build_registry(
        workspace_source(
            "/x/nexus",
            {"success": True, "path": "/x/nexus", "project_types": ["python"], "is_git_repository": True},
            git_result={"success": True, "branch": "main", "clean": False},
        )
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    context = await collector.collect("Inspect /x/nexus please.", "task_1", _Recorder(), plan=MISSION_PLAN)

    assert context.workspaces[0].git_branch == "main"
    assert context.workspaces[0].git_clean is False


# --- conflict detection: §20's exact example -------------------------------


async def test_a_matching_live_port_is_not_a_conflict() -> None:
    registry = await build_registry(
        memories_source(
            [{"id": "m", "type": "WORKSPACE", "key": "backend", "value": {"path": "/x/backend", "port": 8123}, "confidence": 1.0}]
        ),
        workspace_source("/x/backend", {"success": True, "path": "/x/backend", "project_types": ["python"], "is_git_repository": False}),
        processes_source([{"working_directory": "/x/backend", "port": 8123}]),
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)
    emit = _Recorder()

    await collector.collect("Inspect /x/backend please.", "task_1", emit, plan=MISSION_PLAN)

    assert emit.of_type(EventType.MEMORY_CONFLICT) == []


async def test_a_disagreeing_live_port_is_flagged_as_a_conflict() -> None:
    """The spec's exact example: memory says 8000, live process says 8123."""
    registry = await build_registry(
        memories_source(
            [{"id": "m", "type": "WORKSPACE", "key": "backend", "value": {"path": "/x/backend", "port": 8000}, "confidence": 1.0}]
        ),
        workspace_source("/x/backend", {"success": True, "path": "/x/backend", "project_types": ["python"], "is_git_repository": False}),
        processes_source([{"working_directory": "/x/backend", "port": 8123}]),
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)
    emit = _Recorder()

    await collector.collect("Inspect /x/backend please.", "task_1", emit, plan=MISSION_PLAN)

    conflicts = emit.of_type(EventType.MEMORY_CONFLICT)
    assert len(conflicts) == 1
    assert "8000" in conflicts[0].message
    assert "8123" in conflicts[0].message


async def test_no_live_process_means_no_conflict_just_untested() -> None:
    """Nothing live to contradict memory is not the same as a conflict."""
    registry = await build_registry(
        memories_source(
            [{"id": "m", "type": "WORKSPACE", "key": "backend", "value": {"path": "/x/backend", "port": 8000}, "confidence": 1.0}]
        ),
        workspace_source("/x/backend", {"success": True, "path": "/x/backend", "project_types": ["python"], "is_git_repository": False}),
        processes_source([]),
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)
    emit = _Recorder()

    await collector.collect("Inspect /x/backend please.", "task_1", emit, plan=MISSION_PLAN)

    assert emit.of_type(EventType.MEMORY_CONFLICT) == []


# --- machine context -----------------------------------------------------


async def test_machine_context_is_gathered() -> None:
    registry = await build_registry(
        machine_source(
            {"success": True, "platform": "macOS", "architecture": "arm64", "cpu_count": 8},
            {"success": True, "percentage": 71, "charging": False},
        )
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    context = await collector.collect("anything", "task_1", _Recorder(), plan=MISSION_PLAN)

    assert context.machine is not None
    assert context.machine.platform == "macOS"
    assert context.machine.battery_percentage == 71


async def test_machine_context_is_none_without_the_tool() -> None:
    registry = await build_registry()

    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)
    context = await collector.collect("anything", "task_1", _Recorder(), plan=MISSION_PLAN)

    assert context.machine is None


# --- the SAFE-only boundary -------------------------------------------------


async def test_the_collector_never_calls_a_confirm_tool() -> None:
    """Defense in depth: even if asked to, direct calls are refused for
    anything above SAFE — only the approval-gated agent path may call one."""
    registry = await build_registry(
        FakeToolSource(
            [tool_definition("start_process", PermissionLevel.CONFIRM)],
            {"start_process": ToolResult(content="", structured={"success": True})},
        )
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    result = await collector._call_safe("start_process", {})

    assert result is None  # refused, not executed


async def test_a_failing_tool_does_not_sink_context_collection() -> None:
    source = FakeToolSource([tool_definition("system_info", PermissionLevel.SAFE)])

    async def explode(name, arguments):
        raise RuntimeError("boom")

    source.call_tool = explode  # type: ignore[method-assign]
    registry = await build_registry(source)
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    context = await collector.collect("anything", "task_1", _Recorder(), plan=MISSION_PLAN)

    assert context.machine is None  # degraded gracefully, no exception


# --- budget and the context_collected event --------------------------------


async def test_context_collected_is_always_emitted_once() -> None:
    registry = await build_registry()
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)
    emit = _Recorder()

    await collector.collect("anything", "task_1", emit, plan=MISSION_PLAN)

    assert len(emit.of_type(EventType.CONTEXT_COLLECTED)) == 1


async def test_truncated_is_reported_when_the_memory_budget_is_hit() -> None:
    # Every memory here is relevant to the objective, so the budget — not
    # relevance — is what does the cutting.
    many = [
        {"id": f"mem_{i}", "type": "FACT", "key": f"nexus_fact_{i}", "value": {},
         "confidence": 1.0}
        for i in range(10)
    ]
    registry = await build_registry(memories_source(many))
    collector = ContextCollector(registry, max_memories=3, max_workspace_facts=20)

    context = await collector.collect("nexus", "task_1", _Recorder(), plan=MISSION_PLAN)

    assert len(context.memories) == 3
    assert context.truncated is True


async def test_git_state_is_gathered_for_a_subdirectory_of_a_repository() -> None:
    """Phase 10, found live: `detect_workspace` reports is_git_repository=false
    for a subdirectory of a repo, so the collector skipped git_status and the
    context said nothing about the branch — and the model filled the silence
    with an invented "main, clean"."""
    registry = await build_registry(
        workspace_source(
            "/repo/backend",
            # A subdirectory: a real project, but not the repository root.
            {
                "success": True,
                "path": "/repo/backend",
                "project_types": ["python"],
                "is_git_repository": False,
            },
            {"success": True, "branch": "dikshanta", "clean": False,
             "changes": ["a.py", "b.py"]},
        )
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    context = await collector.collect(
        "Inspect /repo/backend please.", "task_1", _Recorder(), plan=MISSION_PLAN
    )

    workspace = context.workspaces[0]
    assert workspace.git_branch == "dikshanta"
    assert workspace.changed_files == 2
    assert workspace.is_git_repository is True
    assert "dikshanta" in workspace.to_line()


async def test_a_directory_outside_any_repository_reports_no_git_state() -> None:
    registry = await build_registry(
        workspace_source(
            "/tmp/plain",
            {"success": True, "path": "/tmp/plain", "project_types": [],
             "is_git_repository": False},
            {"success": False, "error": "Not a git repository."},
        )
    )
    collector = ContextCollector(registry, max_memories=10, max_workspace_facts=20)

    context = await collector.collect(
        "Inspect /tmp/plain please.", "task_1", _Recorder(), plan=MISSION_PLAN
    )

    workspace = context.workspaces[0]
    assert workspace.is_git_repository is False
    assert workspace.git_branch is None
