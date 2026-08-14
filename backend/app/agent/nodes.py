"""LangGraph nodes.

Two nodes for v1: ``agent`` (ask the model what to do) and ``tools`` (execute
what it asked for, subject to permission). Neither knows which model provider
or tool backend is in play — both arrive as dependencies from
:mod:`app.agent.graph`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from app.agent import events as ev
from app.agent.approvals import ApprovalBroker, ApprovalStatus, describe
from app.agent.state import AgentState, ToolCallRecord, ToolResultRecord
from app.core.errors import NexusError, TimeoutError_
from app.core.logging import get_logger, safe_keys
from app.models.base import ModelProvider, content_to_text
from app.tools.permissions import PermissionDecision, PermissionLevel, PermissionPolicy
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are NEXUS, an assistant running locally on the user's Mac.

Use the provided tools whenever a question is about the state of this machine
instead of guessing. Call one tool at a time, read its result, then answer.

If the user refers to "my project", "my X project", or a saved workspace by
name, without giving its path, call list_memories or get_memory first rather
than guessing a path — a guessed path will simply not exist. A tool's current
result always outranks what a memory says, so if you already have a path from
this conversation, use that instead of searching memory again.

If the user asks you to forget, delete, remove, or clear something you
remember — including "forget everything", "forget everything about X", or
"wipe your memory" — call delete_memory. Do not just say you will start
fresh or treat it as a conversational reset; forgetting means calling the
tool, and the user will be asked to confirm before anything is deleted.

Never invent an identifier. A process id, memory key or path you did not
read from a tool result or from the user's own words does not exist, and a
placeholder like "the_id_from_the_list" is not an id. If you need one, look
it up in its own turn first — list_processes for a running process,
list_memories for something you remember — wait for that result, and only
then make the call that uses it.

Report only what the tool result actually says. If it reports failure, say
the action did not happen and why; never claim something was started,
stopped, saved or deleted unless the result confirms it.

Once a tool call has completed the action the user asked for, stop and
report the outcome in plain language. Do not call further tools to double
check or explore further — only call another tool if the user's request
genuinely needs more than one step to answer.

When you have the answer, reply in one or two short, plain sentences. Do not
describe your reasoning or narrate which tools you plan to use. Never tell
the user to call a tool themselves — the tools are yours to call, so look
the value up and finish the job. If a tool refuses on policy grounds, or
says something does not exist, say so plainly and stop; do not retry the
same call with guessed arguments. Never describe a *successful* result as
unavailable or refused.
"""

#: How many tools may be run for a single assistant turn. The step budget
#: bounds how many *turns* a task takes, which is no protection at all against
#: one malformed turn: a model has been observed emitting hundreds of copies of
#: the same call in a single response, every one of which would otherwise be
#: executed. Real work here needs one or two calls at a time.
MAX_TOOL_CALLS_PER_TURN = 4


def _record(
    events: list[ev.ExecutionEvent], emit: ev.EventSink, event: ev.ExecutionEvent
) -> None:
    """Keep the event in state *and* deliver it live."""
    events.append(event)
    emit(event)


def _error_update(
    state: AgentState, exc: NexusError, emit: ev.EventSink = ev.no_sink
) -> dict[str, Any]:
    task_id = state["task_id"]
    logger.error(
        "Task failed: %s (%s)", exc.message, exc.detail or "no detail",
        extra={"task_id": task_id},
    )
    events: list[ev.ExecutionEvent] = []
    _record(events, emit, ev.task_error(task_id, str(exc.code), exc.message))
    return {
        "error": {"code": str(exc.code), "message": exc.message},
        "completed": True,
        "execution_events": events,
    }


def _bounded_tool_calls(calls: list[Any], task_id: str) -> list[Any]:
    """Drop repeats and cap how much one turn may run.

    Running an identical call twice cannot tell the model anything new, and
    every extra result is transcript the next request has to carry — which is
    how a repetitive turn turns into a rate-limit failure.
    """
    unique: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for call in calls:
        key = (call["name"], json.dumps(call.get("args") or {}, sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        unique.append(call)

    if len(unique) < len(calls):
        logger.warning(
            "Collapsing %d duplicate tool call(s) in one turn",
            len(calls) - len(unique),
            extra={"task_id": task_id},
        )
    if len(unique) > MAX_TOOL_CALLS_PER_TURN:
        logger.warning(
            "Dropping %d of %d tool call(s): more than %d in one turn",
            len(unique) - MAX_TOOL_CALLS_PER_TURN, len(unique), MAX_TOOL_CALLS_PER_TURN,
            extra={"task_id": task_id},
        )
    return unique[:MAX_TOOL_CALLS_PER_TURN]


def _result_to_text(content: str, structured: Any) -> str:
    if content:
        return content
    if structured is not None:
        return json.dumps(structured, default=str)
    return "(the tool returned no output)"


async def agent_node(
    state: AgentState,
    *,
    provider: ModelProvider,
    registry: ToolRegistry,
    max_iterations: int,
    timeout: float,
    emit: ev.EventSink = ev.no_sink,
    system_prompt: str = SYSTEM_PROMPT,
) -> dict[str, Any]:
    """Ask the model for the next step."""
    task_id = state["task_id"]
    iterations = state["iterations"]

    # Once the step budget is spent, stop offering tools so the model is forced
    # to answer with what it already has instead of looping.
    budget_spent = iterations >= max_iterations
    specs = [] if budget_spent else registry.model_specs()
    if budget_spent:
        # A model with no tools left will sometimes still try to write one out
        # as literal text. Tell it plainly that this turn is answer-only.
        system_prompt = (
            f"{system_prompt}\n\nYou have used all the tool calls available for "
            "this task. Do not attempt to call a tool or describe one — answer "
            "now, in one or two plain sentences, using what you already know "
            "from the tool results above."
        )

    logger.info(
        "Model request via %s (%s), %d tool(s) offered",
        provider.name, provider.model, len(specs),
        extra={"task_id": task_id},
    )

    try:
        async with asyncio.timeout(timeout):
            response = await provider.ainvoke(
                [SystemMessage(content=system_prompt), *state["messages"]], specs
            )
    except TimeoutError:
        return _error_update(
            state, TimeoutError_("The model took too long to respond."), emit
        )
    except NexusError as exc:
        return _error_update(state, exc, emit)
    except Exception as exc:  # noqa: BLE001 - never fail silently
        return _error_update(
            state,
            NexusError(
                "The agent hit an unexpected problem.",
                detail=f"{type(exc).__name__}: {exc}",
            ),
            emit,
        )

    requested = _bounded_tool_calls(list(response.tool_calls or []), task_id)
    if requested != list(response.tool_calls or []):
        # Trim the message itself, not just our record of it: the tool node
        # reads the calls back off this message when it decides what to run.
        response.tool_calls = requested

    text = content_to_text(response.content).strip()
    execution_events: list[ev.ExecutionEvent] = []
    if text:
        _record(execution_events, emit, ev.agent_message(task_id, text))

    tool_calls: list[ToolCallRecord] = []
    # Tool calls made after the budget is spent are ignored: the model was told
    # it had no tools, so acting on them would restart the loop.
    for call in requested if not budget_spent else []:
        definition = registry.get(call["name"])
        level = definition.permission if definition else PermissionLevel.RESTRICTED
        tool_calls.append(
            ToolCallRecord(
                id=str(call.get("id") or ""),
                name=call["name"],
                arguments=dict(call.get("args") or {}),
                permission=str(level),
            )
        )
        _record(execution_events, emit, ev.tool_requested(task_id, call["name"], str(level)))

    if budget_spent and response.tool_calls:
        logger.warning(
            "Ignoring %d tool call(s): the step budget of %d is spent",
            len(response.tool_calls), max_iterations,
            extra={"task_id": task_id},
        )

    update: dict[str, Any] = {
        "messages": [response],
        "execution_events": execution_events,
        "iterations": iterations + 1,
    }
    if tool_calls:
        update["tool_calls"] = tool_calls
    else:
        update["completed"] = True
    return update


def _refusal_message(tool: str, outcome: ApprovalStatus, *, repeated: bool = False) -> str:
    """What the model is told when an approval does not come through."""
    base = {
        ApprovalStatus.DENIED: f"The user denied permission to run '{tool}'.",
        ApprovalStatus.EXPIRED: f"The permission request for '{tool}' timed out.",
        ApprovalStatus.CANCELLED: f"The permission request for '{tool}' was cancelled.",
    }.get(outcome, f"'{tool}' was not permitted to run.")
    if repeated:
        return f"{base} Do not ask again; tell the user instead."
    return base


async def tool_node(
    state: AgentState,
    *,
    registry: ToolRegistry,
    policy: PermissionPolicy,
    timeout: float,
    broker: ApprovalBroker | None = None,
    permission_timeout: float = 300.0,
    emit: ev.EventSink = ev.no_sink,
) -> dict[str, Any]:
    """Execute the tools the model asked for, subject to permission.

    With a ``broker``, a CONFIRM tool parks as an approval request and this node
    waits for the user's answer. Without one there is no approval channel, so
    the run halts and hands the decision back to the caller instead.
    """
    task_id = state["task_id"]
    last = state["messages"][-1]
    calls = list(getattr(last, "tool_calls", None) or []) if isinstance(last, AIMessage) else []

    messages: list[ToolMessage] = []
    execution_events: list[ev.ExecutionEvent] = []
    results: list[ToolResultRecord] = []
    permission_request = None

    for call in calls:
        name = call["name"]
        call_id = str(call.get("id") or "")
        arguments = dict(call.get("args") or {})

        definition = registry.get(name)
        if definition is None:
            message = f"'{name}' is not an available tool."
            _record(execution_events, emit, ev.tool_completed(task_id, name, False, message))
            messages.append(ToolMessage(content=message, tool_call_id=call_id, name=name))
            results.append(
                ToolResultRecord(id=call_id, name=name, success=False, content=message)
            )
            continue

        decision = policy.evaluate(name, definition.permission)

        if not decision.allowed and decision.requires_confirmation and broker is not None:
            # A decision sticks for the whole task: never re-prompt for a tool
            # the user has already refused.
            prior = broker.previous_refusal(task_id, name)
            if prior is not None:
                reason = _refusal_message(name, prior, repeated=True)
                logger.info(
                    "Not re-asking for '%s': already %s", name, prior,
                    extra={"task_id": task_id},
                )
                _record(
                    execution_events, emit, ev.tool_completed(task_id, name, False, reason)
                )
                messages.append(
                    ToolMessage(content=reason, tool_call_id=call_id, name=name)
                )
                results.append(
                    ToolResultRecord(id=call_id, name=name, success=False, content=reason)
                )
                continue

            # Ask the user and wait. The API layer resolves the request.
            request = broker.create(
                task_id=task_id,
                tool=name,
                permission=decision.level,
                description=describe(
                    name,
                    definition.description,
                    arguments,
                    definition.prompt_template,
                ),
                arguments=arguments,
            )
            _record(
                execution_events,
                emit,
                ev.permission_required(
                    task_id, name, str(decision.level), decision.reason, request.request_id
                ),
            )
            if permission_request is None:
                permission_request = {
                    "tool": name,
                    "permission": str(decision.level),
                    "reason": decision.reason,
                    "arguments": arguments,
                }
            outcome = await broker.wait(request, permission_timeout)
            if outcome is ApprovalStatus.APPROVED:
                decision = PermissionDecision(
                    allowed=True, level=decision.level, reason="Approved by the user."
                )
                permission_request = None
            else:
                reason = _refusal_message(name, outcome)
                _record(execution_events, emit, ev.tool_completed(task_id, name, False, reason))
                messages.append(
                    ToolMessage(content=reason, tool_call_id=call_id, name=name)
                )
                results.append(
                    ToolResultRecord(
                        id=call_id, name=name, success=False, content=reason
                    )
                )
                permission_request = None
                continue

        if not decision.allowed:
            logger.info(
                "Denied '%s' (%s): %s", name, definition.permission, decision.reason,
                extra={"task_id": task_id},
            )
            if decision.requires_confirmation:
                # No approval channel available: halt and let the caller decide.
                _record(
                    execution_events,
                    emit,
                    ev.permission_required(
                        task_id, name, str(decision.level), decision.reason
                    ),
                )
                if permission_request is None:
                    permission_request = {
                        "tool": name,
                        "permission": str(decision.level),
                        "reason": decision.reason,
                        "arguments": arguments,
                    }
            else:
                _record(
                    execution_events,
                    emit,
                    ev.tool_completed(task_id, name, False, decision.reason),
                )
            messages.append(
                ToolMessage(content=decision.reason, tool_call_id=call_id, name=name)
            )
            results.append(
                ToolResultRecord(
                    id=call_id, name=name, success=False, content=decision.reason
                )
            )
            continue

        logger.info(
            "Tool request '%s' (args: %s)", name, safe_keys(arguments),
            extra={"task_id": task_id},
        )
        _record(execution_events, emit, ev.tool_started(task_id, name))
        try:
            async with asyncio.timeout(timeout):
                result = await registry.call(name, arguments)
        except TimeoutError:
            error = TimeoutError_(f"'{name}' took too long and was stopped.")
            _record(execution_events, emit, ev.tool_completed(task_id, name, False, error.message))
            messages.append(
                ToolMessage(content=error.message, tool_call_id=call_id, name=name)
            )
            results.append(
                ToolResultRecord(
                    id=call_id, name=name, success=False, content=error.message
                )
            )
            continue
        except NexusError as exc:
            logger.error(
                "Tool '%s' failed: %s (%s)", name, exc.message, exc.detail or "no detail",
                extra={"task_id": task_id},
            )
            _record(execution_events, emit, ev.tool_completed(task_id, name, False, exc.message))
            messages.append(
                ToolMessage(content=exc.message, tool_call_id=call_id, name=name)
            )
            results.append(
                ToolResultRecord(
                    id=call_id, name=name, success=False, content=exc.message
                )
            )
            continue

        text = _result_to_text(result.content, result.structured)
        success = not result.is_error
        logger.info(
            "Tool '%s' completed (success=%s)", name, success, extra={"task_id": task_id}
        )
        _record(execution_events, emit, ev.tool_completed(task_id, name, success))
        messages.append(ToolMessage(content=text, tool_call_id=call_id, name=name))
        results.append(
            ToolResultRecord(
                id=call_id,
                name=name,
                success=success,
                content=text,
                structured=result.structured,
            )
        )

    update: dict[str, Any] = {
        "messages": messages,
        "execution_events": execution_events,
        "tool_results": results,
    }
    if permission_request is not None:
        # Stop here and hand the decision back to the user; the runner emits
        # the terminal event.
        update["requires_permission"] = True
        update["permission_request"] = permission_request
        update["completed"] = True
    return update


def should_continue(state: AgentState, *, max_iterations: int) -> Literal["tools", "end"]:
    """Route after the agent node: run the requested tools, or finish."""
    if state.get("error") or state.get("completed"):
        return "end"
    if state["iterations"] > max_iterations:
        # Hard stop. `agent_node` already stopped offering tools a turn ago; a
        # model that keeps asking for them anyway must not loop forever.
        logger.warning(
            "Stopping after %d agent turns (AGENT_MAX_ITERATIONS=%d)",
            state["iterations"], max_iterations,
            extra={"task_id": state["task_id"]},
        )
        return "end"
    last = state["messages"][-1] if state["messages"] else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "end"


def after_tools(state: AgentState) -> Literal["agent", "end"]:
    """Route after the tool node: normally back to the agent.

    The exception is a run halted waiting for permission — there is nothing
    for the model to add until the user decides.
    """
    if state.get("error") or state.get("completed"):
        return "end"
    return "agent"


__all__ = [
    "SYSTEM_PROMPT",
    "after_tools",
    "agent_node",
    "should_continue",
    "tool_node",
]
