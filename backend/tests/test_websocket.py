"""WebSocket event stream."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agent import events as ev
from app.agent.tasks import get_task_store
from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_connect_and_ping(client: TestClient) -> None:
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json() == {"type": "connected", "task_id": None}

        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_a_late_client_gets_the_events_it_missed(client: TestClient) -> None:
    store = get_task_store()
    record = store.create("what is my battery percentage?")
    store.publish(
        record,
        [
            ev.task_started(record.task_id, record.request),
            ev.tool_started(record.task_id, "battery_status"),
        ],
    )

    with client.websocket_connect(f"/api/ws?task_id={record.task_id}") as ws:
        assert ws.receive_json()["type"] == "connected"

        first = ws.receive_json()
        second = ws.receive_json()

    assert first["type"] == "task_started"
    assert second["type"] == "tool_started"
    assert second["tool"] == "battery_status"
    assert second["task_id"] == record.task_id


def test_a_permission_request_is_streamed_with_its_request_id(
    client: TestClient,
) -> None:
    store = get_task_store()
    record = store.create("open vs code")

    with client.websocket_connect(f"/api/ws?task_id={record.task_id}") as ws:
        assert ws.receive_json()["type"] == "connected"

        store.publish(
            record,
            [
                ev.permission_required(
                    record.task_id,
                    "open_application",
                    "CONFIRM",
                    "'open_application' needs your approval before it can run.",
                    "perm_abc123",
                )
            ],
        )
        event = ws.receive_json()

    assert event["type"] == "permission_required"
    assert event["tool"] == "open_application"
    assert event["permission"] == "CONFIRM"
    # Without this the client could not answer the request.
    assert event["request_id"] == "perm_abc123"


def test_cancellation_is_streamed(client: TestClient) -> None:
    store = get_task_store()
    record = store.create("something slow")

    with client.websocket_connect(f"/api/ws?task_id={record.task_id}") as ws:
        assert ws.receive_json()["type"] == "connected"

        store.publish(record, [ev.task_cancelled(record.task_id)])
        event = ws.receive_json()

    assert event["type"] == "task_cancelled"


def test_no_event_carries_hidden_reasoning(client: TestClient) -> None:
    store = get_task_store()
    record = store.create("what is my battery?")
    store.publish(
        record,
        [
            ev.task_started(record.task_id, record.request),
            ev.tool_started(record.task_id, "battery_status"),
            ev.tool_completed(record.task_id, "battery_status", True),
        ],
    )

    payloads = [event.to_dict() for event in record.events]

    for payload in payloads:
        assert set(payload) <= {
            "type",
            "task_id",
            "timestamp",
            "message",
            "tool",
            "success",
            "permission",
            "request_id",
            "code",
        }


def test_mission_events_stream_over_the_same_websocket(client: TestClient) -> None:
    """No second streaming system: mission events ride the existing path."""
    store = get_task_store()
    record = store.create("Prepare my project for development.")

    with client.websocket_connect(f"/api/ws?task_id={record.task_id}") as ws:
        assert ws.receive_json()["type"] == "connected"

        store.publish(
            record,
            [
                ev.mission_started(record.task_id, "mission_1", record.request),
                ev.mission_plan_created(
                    record.task_id, "mission_1",
                    [{"id": "step_1", "description": "Inspect", "tool": "detect_workspace"}],
                ),
                ev.mission_step_started(record.task_id, "mission_1", "step_1", "Inspect"),
                ev.mission_waiting_approval(
                    record.task_id, "mission_1", "step_1", "perm_1", "Approval needed."
                ),
                ev.mission_step_completed(record.task_id, "mission_1", "step_1", "Done."),
                ev.mission_completed(record.task_id, "mission_1", {"steps_completed": 1}),
            ],
        )

        received = [ws.receive_json() for _ in range(6)]

    assert [event["type"] for event in received] == [
        "mission_started",
        "mission_plan_created",
        "mission_step_started",
        "mission_waiting_approval",
        "mission_step_completed",
        "mission_completed",
    ]
    assert all(event["mission_id"] == "mission_1" for event in received)
    assert received[2]["step_id"] == "step_1"
    assert received[3]["request_id"] == "perm_1"  # the client answers with this
    assert received[5]["summary"] == {"steps_completed": 1}


def test_mission_events_carry_no_hidden_reasoning(client: TestClient) -> None:
    store = get_task_store()
    record = store.create("Prepare my project for development.")
    store.publish(
        record,
        [
            ev.mission_started(record.task_id, "mission_1", "objective"),
            ev.mission_step_started(record.task_id, "mission_1", "step_1", "Inspect"),
            ev.mission_step_completed(record.task_id, "mission_1", "step_1", "Done."),
            ev.mission_failed(record.task_id, "mission_1", "reason", {"steps_total": 1}),
        ],
    )

    for event in record.events:
        payload = event.to_dict()
        assert set(payload) <= {
            "type", "task_id", "timestamp", "message", "tool",
            "mission_id", "step_id", "request_id", "steps", "summary",
        }


def test_events_for_other_tasks_are_filtered_out(client: TestClient) -> None:
    store = get_task_store()
    mine = store.create("mine")
    theirs = store.create("theirs")

    with client.websocket_connect(f"/api/ws?task_id={mine.task_id}") as ws:
        assert ws.receive_json()["type"] == "connected"

        store.publish(theirs, [ev.agent_message(theirs.task_id, "not for you")])
        store.publish(mine, [ev.agent_message(mine.task_id, "for you")])

        event = ws.receive_json()

    assert event["message"] == "for you"
    assert event["task_id"] == mine.task_id
