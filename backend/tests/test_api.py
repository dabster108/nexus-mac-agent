"""HTTP surface: health, chat, tasks, tools, mcp and models."""

from __future__ import annotations

import pytest
from conftest import StubProvider, tool_definition
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent.runner import AgentRunner, get_agent_runner
from app.agent.tasks import TaskStatus, get_task_store
from app.api.schemas import ChatRequest
from app.core.config import Settings, get_settings
from app.main import create_app
from app.mcp.registry import MCPServerRegistry, get_mcp_registry
from app.models.router import ModelRouter, get_model_router
from app.tools.permissions import PermissionLevel


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(settings)
    return TestClient(app)


# --- health ----------------------------------------------------------------


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nexus-agent"}


def test_health_never_leaks_secrets(client: TestClient) -> None:
    body = client.get("/health").text
    assert "test-groq-key" not in body
    assert "api_key" not in body.lower()


# --- chat ------------------------------------------------------------------


def test_chat_accepts_the_request_and_returns_a_task_id(
    client: TestClient, settings: Settings
) -> None:
    provider = StubProvider([AIMessage(content="Hello.")])
    runner = AgentRunner(
        settings=settings,
        router=ModelRouter(settings, {"groq": lambda _s: provider}),
        server_registry=MCPServerRegistry([]),
    )
    client.app.dependency_overrides[get_agent_runner] = lambda: runner

    response = client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "started"
    assert body["task_id"].startswith("task_")


def test_chat_rejects_an_empty_message(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "   "})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_chat_rejects_a_malformed_body(client: TestClient) -> None:
    response = client.post("/api/chat", json={"nope": 1})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- tasks -----------------------------------------------------------------


def test_task_list_is_newest_first(client: TestClient) -> None:
    store = get_task_store()
    store.create("first")
    second = store.create("second")

    body = client.get("/api/tasks").json()

    assert [task["request"] for task in body["tasks"]] == ["second", "first"]
    assert body["tasks"][0]["task_id"] == second.task_id


def test_task_list_honours_limit(client: TestClient) -> None:
    store = get_task_store()
    for index in range(5):
        store.create(f"task {index}")

    body = client.get("/api/tasks?limit=2").json()

    assert len(body["tasks"]) == 2


def test_unknown_task_is_404(client: TestClient) -> None:
    response = client.get("/api/tasks/task_missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "task_missing" in response.json()["error"]["message"]


def test_task_lookup_returns_the_record(client: TestClient) -> None:
    store = get_task_store()
    record = store.create("what is my battery percentage?")
    store.finish(record, status=TaskStatus.COMPLETED, response="87 percent.")

    body = client.get(f"/api/tasks/{record.task_id}").json()

    assert body["task_id"] == record.task_id
    assert body["status"] == "completed"
    assert body["response"] == "87 percent."
    assert body["message"] == "87 percent."
    assert body["completed_at"] is not None


# --- cancel ----------------------------------------------------------------


def test_cancelling_an_unknown_task_is_404(client: TestClient) -> None:
    response = client.post("/api/tasks/task_missing/cancel")

    assert response.status_code == 404


def test_cancelling_a_finished_task_reports_its_real_status(
    client: TestClient,
) -> None:
    store = get_task_store()
    record = store.create("already done")
    store.finish(record, status=TaskStatus.COMPLETED, response="done")

    response = client.post(f"/api/tasks/{record.task_id}/cancel")

    assert response.status_code == 200
    # Not "cancelled" — the task really did complete.
    assert response.json() == {"task_id": record.task_id, "status": "completed"}


def test_cancelling_a_pending_task_marks_it_cancelled(client: TestClient) -> None:
    store = get_task_store()
    record = store.create("still going")

    response = client.post(f"/api/tasks/{record.task_id}/cancel")

    assert response.json() == {"task_id": record.task_id, "status": "cancelled"}
    assert record.completed_at is not None
    assert [str(event.type) for event in record.events] == ["task_cancelled"]


# --- tools -----------------------------------------------------------------


class _StubRunner:
    """Stands in for the runner so tool routes need no MCP server."""

    def __init__(self, definitions: list) -> None:
        self._definitions = definitions

    async def list_tools(self) -> list:
        return self._definitions


def test_tool_list(client: TestClient) -> None:
    client.app.dependency_overrides[get_agent_runner] = lambda: _StubRunner(
        [
            tool_definition("battery_status", PermissionLevel.SAFE, source="nexus-mac"),
            tool_definition("open_application", PermissionLevel.CONFIRM, source="nexus-mac"),
        ]
    )

    body = client.get("/api/tools").json()

    assert [tool["name"] for tool in body["tools"]] == [
        "battery_status",
        "open_application",
    ]
    assert body["tools"][1]["permission"] == "CONFIRM"
    assert body["tools"][0]["source"] == "nexus-mac"


def test_tool_detail(client: TestClient) -> None:
    client.app.dependency_overrides[get_agent_runner] = lambda: _StubRunner(
        [tool_definition("battery_status", PermissionLevel.SAFE)]
    )

    body = client.get("/api/tools/battery_status").json()

    assert body["name"] == "battery_status"
    assert body["permission"] == "SAFE"


def test_unknown_tool_is_404(client: TestClient) -> None:
    client.app.dependency_overrides[get_agent_runner] = lambda: _StubRunner([])

    response = client.get("/api/tools/make_coffee")

    assert response.status_code == 404
    assert "make_coffee" in response.json()["error"]["message"]


def test_the_tool_endpoint_cannot_execute_anything(client: TestClient) -> None:
    client.app.dependency_overrides[get_agent_runner] = lambda: _StubRunner(
        [tool_definition("battery_status")]
    )

    # Information only: there is no POST route for running a tool.
    assert client.post("/api/tools/battery_status").status_code == 405


# --- mcp -------------------------------------------------------------------


def test_mcp_servers_reports_the_mac_server(client: TestClient) -> None:
    body = client.get("/api/mcp/servers").json()

    assert len(body["servers"]) == 1
    server = body["servers"][0]
    assert server["name"] == "nexus-mac"
    assert server["status"] == "connected"
    assert server["tools"] == 24


def test_mcp_servers_reports_a_disconnected_server(
    client: TestClient, settings: Settings
) -> None:
    from app.mcp.client import MCPServerConfig

    broken = MCPServerRegistry(
        [MCPServerConfig(name="ghost", command="definitely-not-a-real-binary")]
    )
    client.app.dependency_overrides[get_mcp_registry] = lambda: broken

    body = client.get("/api/mcp/servers").json()

    assert body["servers"][0]["status"] == "disconnected"
    assert body["servers"][0]["tools"] == 0
    assert body["servers"][0]["reason"]


def test_no_mcp_servers_returns_an_empty_list(client: TestClient) -> None:
    client.app.dependency_overrides[get_mcp_registry] = lambda: MCPServerRegistry([])

    assert client.get("/api/mcp/servers").json() == {"servers": []}


# --- models ----------------------------------------------------------------


def test_models_reports_availability_and_default(client: TestClient) -> None:
    body = client.get("/api/models").json()

    assert body["default"] == "groq"
    providers = {provider["name"]: provider for provider in body["providers"]}
    assert providers["groq"]["available"] is True
    assert providers["mistral"]["available"] is True
    assert providers["groq"]["model"] == "test-groq-model"


def test_models_marks_an_unconfigured_provider_unavailable(
    client: TestClient, settings: Settings
) -> None:
    import dataclasses

    without_mistral = dataclasses.replace(settings, mistral_api_key=None)
    client.app.dependency_overrides[get_settings] = lambda: without_mistral
    client.app.dependency_overrides[get_model_router] = lambda: ModelRouter(
        without_mistral
    )

    providers = {
        provider["name"]: provider
        for provider in client.get("/api/models").json()["providers"]
    }

    assert providers["groq"]["available"] is True
    assert providers["mistral"]["available"] is False


def test_models_never_returns_a_key(client: TestClient) -> None:
    body = client.get("/api/models").text

    assert "test-groq-key" not in body
    assert "test-mistral-key" not in body


# --- docs ------------------------------------------------------------------


def test_openapi_documents_every_endpoint(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()

    assert set(spec["paths"]) == {
        "/health",
        "/api/chat",
        "/api/tasks",
        "/api/tasks/{task_id}",
        "/api/tasks/{task_id}/cancel",
        "/api/tools",
        "/api/tools/{tool_name}",
        "/api/permissions/pending",
        "/api/permissions/{request_id}/approve",
        "/api/permissions/{request_id}/deny",
        "/api/mcp/servers",
        "/api/models",
        "/api/context",
        "/api/context/{task_id}",
        "/api/memory",
    }
    assert {tag["name"] for tag in spec["tags"]} == {
        "health",
        "agent",
        "tasks",
        "tools",
        "permissions",
        "mcp",
        "models",
        "context",
        "memory",
    }


def test_no_endpoint_exists_for_individual_mac_capabilities(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    for forbidden in ("/api/battery", "/api/open-vscode", "/api/read-file"):
        assert forbidden not in paths


def test_the_openapi_schema_contains_no_secrets(client: TestClient) -> None:
    body = client.get("/openapi.json").text

    for leak in ("GROQ_API_KEY", "api_key", "test-groq-key"):
        assert leak not in body


# --- request validation (Phase 9) -----------------------------------------
#
# Rejections are checked through the endpoint (they never start a task).
# Acceptance is checked against the schema, so these stay fast and never
# reach a real provider.


def test_an_unknown_provider_is_rejected_at_the_request(client: TestClient) -> None:
    """Phase 9: an unknown provider was accepted with 201 and then failed
    asynchronously. Provider validity is knowable when the request arrives."""
    response = client.post("/api/chat", json={"message": "hi", "provider": "evilprovider"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_an_absurd_approved_tools_list_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/chat", json={"message": "hi", "approved_tools": ["x"] * 1000}
    )

    assert response.status_code == 400


@pytest.mark.parametrize("provider", ["groq", "mistral", None])
def test_the_supported_providers_remain_valid(provider: str | None) -> None:
    assert ChatRequest(message="hi", provider=provider).provider == provider


def test_an_ordinary_approved_tools_list_remains_valid() -> None:
    request = ChatRequest(message="hi", approved_tools=["open_application"])

    assert request.approved_tools == ["open_application"]
