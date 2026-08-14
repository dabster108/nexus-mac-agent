"""WebSocket event stream.

Read-only for v1: a client connects and receives execution events as the agent
produces them. Requests are still submitted over ``POST /api/chat``, which keeps
this layer small enough to extend later (bidirectional chat, cancellation).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.agent.tasks import replay
from app.api.deps import TaskStoreDep
from app.core.logging import get_logger

logger = get_logger(__name__)

ws_router = APIRouter(prefix="/api", tags=["agent"])


async def _drain_client(websocket: WebSocket) -> None:
    """Consume inbound frames so a disconnect is noticed promptly."""
    while True:
        message = await websocket.receive_json()
        if isinstance(message, dict) and message.get("type") == "ping":
            await websocket.send_json({"type": "pong"})


async def _forward_events(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, Any]],
    task_id: str | None,
) -> None:
    while True:
        event = await queue.get()
        if task_id and event.get("task_id") != task_id:
            continue
        await websocket.send_json(event)


@ws_router.websocket("/ws")
async def agent_events(
    websocket: WebSocket,
    store: TaskStoreDep,
    task_id: Annotated[
        str | None, Query(description="Only forward events for this task.")
    ] = None,
) -> None:
    await websocket.accept()
    logger.info("WebSocket client connected (task filter: %s)", task_id or "none")

    async with store.subscribe() as queue:
        try:
            await websocket.send_json({"type": "connected", "task_id": task_id})
            # Let a late subscriber catch up on a task that is already running.
            if task_id:
                record = store.get(task_id)
                if record is not None:
                    for event in replay(record):
                        await websocket.send_json(event)

            forwarder = asyncio.create_task(_forward_events(websocket, queue, task_id))
            receiver = asyncio.create_task(_drain_client(websocket))
            done, pending = await asyncio.wait(
                {forwarder, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            logger.info("WebSocket client disconnected")
