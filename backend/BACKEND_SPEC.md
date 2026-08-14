# NEXUS Backend — Implementation Specification

## 1. Purpose

Build the backend for **NEXUS**, an AI Operating System for macOS.

The backend is responsible for:

* AI agent execution
* LangGraph workflow orchestration
* Groq and Mistral model integration
* MCP client communication
* local Mac tool execution
* permission handling
* agent state
* streaming events to the Next.js frontend
* future memory and task history

The backend must be designed as a modular system rather than a single large Python file.

---

# 2. Technology Stack

Use:

* Python 3.12+
* `uv` for dependency and environment management
* FastAPI
* Uvicorn
* LangGraph
* LangChain Core
* LangChain Groq integration
* Mistral Python SDK
* MCP Python SDK
* python-dotenv

Do **not** add unnecessary frameworks such as:

* CrewAI
* AutoGen
* multiple agent frameworks
* vector databases
* Redis
* Kafka
* PostgreSQL

Those may be introduced later if there is a concrete requirement.

---

# 3. Backend Structure

The backend should use this structure:

```text
backend/
│
├── BACKEND_SPEC.md
├── pyproject.toml
├── uv.lock
├── .env
├── .env.example
├── .gitignore
│
└── app/
    │
    ├── __init__.py
    ├── main.py
    │
    ├── agent/
    │   ├── __init__.py
    │   ├── graph.py
    │   ├── state.py
    │   ├── nodes.py
    │   └── runner.py
    │
    ├── models/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── groq.py
    │   ├── mistral.py
    │   └── router.py
    │
    ├── mcp/
    │   ├── __init__.py
    │   ├── client.py
    │   └── registry.py
    │
    ├── tools/
    │   ├── __init__.py
    │   └── registry.py
    │
    ├── api/
    │   ├── __init__.py
    │   ├── routes.py
    │   └── websocket.py
    │
    └── core/
        ├── __init__.py
        ├── config.py
        └── logging.py
```

Keep the architecture simple and extensible.

---

# 4. Dependency Setup

Initialize the backend using `uv`.

From the `backend/` directory:

```bash
uv init
```

Install:

```bash
uv add fastapi "uvicorn[standard]" langgraph langchain-core langchain-groq mcp python-dotenv mistralai
```

Run the server using:

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Do not require manual virtual-environment activation.

---

# 5. Environment Variables

Create:

```text
.env
.env.example
```

`.env.example` should contain:

```env
GROQ_API_KEY=
MISTRAL_API_KEY=

DEFAULT_MODEL_PROVIDER=groq

BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000
```

Never commit `.env`.

The configuration system should load environment variables through a centralized configuration module.

Do not scatter `os.getenv()` throughout the project.

---

# 6. FastAPI Application

`app/main.py` should be responsible only for application initialization.

The initial API should expose:

```text
GET /health
```

Response:

```json
{
  "status": "ok",
  "service": "nexus-agent"
}
```

Also enable FastAPI's development documentation.

The backend should run on:

```text
http://localhost:8000
```

API documentation:

```text
http://localhost:8000/docs
```

---

# 7. Agent Architecture

NEXUS should use **LangGraph** as the orchestration layer.

Do not build the application around a generic autonomous agent framework.

The initial graph should be:

```text
START
  ↓
AGENT
  ↓
TOOLS REQUIRED?
  ├── NO → END
  │
  └── YES
        ↓
      TOOL
        ↓
      AGENT
```

The agent should be able to:

1. receive a user request
2. inspect available tools
3. ask the model what action is required
4. execute a tool
5. receive the tool result
6. continue reasoning
7. stop when the task is complete

---

# 8. Agent State

Create a typed state object for LangGraph.

The state should eventually support:

```text
messages
user_request
tool_calls
tool_results
current_task
execution_events
requires_permission
permission_request
completed
error
```

Keep the state minimal for v1.

Do not build a complicated memory system yet.

---

# 9. Agent Nodes

Initially create:

```text
agent
tool_executor
```

Future nodes may include:

```text
planner
permission
memory
human_approval
retry
summarizer
```

Do not implement future nodes until required.

---

# 10. Model Provider Architecture

NEXUS must not hard-code Groq into the agent.

Create a model abstraction.

Conceptually:

```text
ModelProvider
│
├── GroqProvider
└── MistralProvider
```

The agent should communicate with a provider interface rather than directly calling the Groq SDK.

This makes changing models easy.

---

# 11. Groq

Groq should be the initial default provider.

Use it for:

* fast tool selection
* normal user requests
* simple reasoning
* summarization
* everyday computer tasks

The exact model name should be configurable through environment variables rather than hard-coded throughout the application.

Example:

```env
DEFAULT_MODEL_PROVIDER=groq
```

---

# 12. Mistral

Mistral should be implemented as a secondary provider.

It should be possible to switch providers without changing the LangGraph implementation.

Example:

```text
Agent
 ↓
Model Router
 ├── Groq
 └── Mistral
```

The model router should initially use:

```text
DEFAULT_MODEL_PROVIDER
```

Later it can intelligently select providers based on task complexity.

---

# 13. MCP Architecture

NEXUS should communicate with tools through MCP wherever appropriate.

The backend acts as an MCP client.

Conceptually:

```text
LangGraph
    ↓
Tool Registry
    ↓
MCP Client
    ↓
MCP Server
    ↓
Tool
```

The MCP layer should be isolated from the agent logic.

The agent should not know how an MCP server is implemented.

---

# 14. NEXUS Mac MCP

A custom local MCP server will eventually expose Mac capabilities.

Initial planned tools:

## Filesystem

```text
search_files
read_file
write_file
create_directory
move_file
```

Do not implement destructive file deletion in the first version unless protected by explicit confirmation.

## Applications

```text
list_applications
open_application
close_application
```

## System

```text
system_info
battery_status
process_list
```

## Clipboard

```text
read_clipboard
write_clipboard
```

## Terminal

```text
execute_command
process_status
```

Terminal execution must be protected by the permission system.

## Notifications

```text
send_notification
```

## Calendar

Later:

```text
list_events
create_event
update_event
delete_event
```

Native macOS Calendar should preferably be controlled locally through macOS capabilities such as AppleScript or supported native automation.

A Google Calendar API should not be required for controlling the native macOS Calendar application.

---

# 15. Tool Registry

Create a central tool registry.

The registry should make it possible to discover:

```text
available tools
tool description
tool schema
tool source
permission level
```

Example:

```text
Tool:
open_application

Source:
NEXUS Mac MCP

Permission:
SAFE
```

The agent should receive the tools available to it through this registry.

---

# 16. Permission System

Permission handling is a core backend responsibility.

Each tool should eventually declare a permission level.

Example:

```text
SAFE
CONFIRM
RESTRICTED
```

Examples:

### SAFE

```text
system_info
battery_status
list_applications
search_files
read_clipboard
```

### CONFIRM

```text
write_file
create_event
send_notification
execute_command
open_application
```

### RESTRICTED

```text
delete_file
mass_file_operations
security_setting_changes
credential-related operations
```

The permission system must be implemented before giving the agent broad Mac access.

---

# 17. Tool Execution

Every tool execution should generate an event.

Example:

```json
{
  "type": "tool_started",
  "tool": "open_application",
  "timestamp": "..."
}
```

Then:

```json
{
  "type": "tool_completed",
  "tool": "open_application",
  "success": true,
  "timestamp": "..."
}
```

Errors should also produce structured events.

---

# 18. Streaming

The Next.js frontend needs to display the agent's progress in real time.

The backend should support streaming through either:

* Server-Sent Events
* WebSockets

Prefer a simple implementation first.

The frontend should eventually receive events such as:

```text
task_started
agent_thinking
tool_requested
permission_required
tool_started
tool_completed
agent_message
task_completed
task_error
```

Do not expose hidden chain-of-thought.

Only expose safe execution status and concise agent updates.

---

# 19. API Design

Initial endpoints:

```text
GET /health
POST /api/chat
GET /api/tasks/{task_id}
WS /api/ws
```

### POST /api/chat

Request:

```json
{
  "message": "What is my battery percentage?"
}
```

Response should contain a task identifier and/or streamed execution events depending on the selected transport.

---

# 20. Task IDs

Every user request should eventually have a unique task ID.

Example:

```text
task_01K...
```

The task ID allows the frontend to:

* track execution
* reconnect
* display history
* inspect status
* cancel future long-running tasks

For v1, in-memory task tracking is acceptable.

---

# 21. Error Handling

The backend must never silently fail.

Errors should be categorized:

```text
MODEL_ERROR
TOOL_ERROR
MCP_ERROR
PERMISSION_ERROR
VALIDATION_ERROR
TIMEOUT_ERROR
INTERNAL_ERROR
```

The user should receive a clean explanation while detailed technical information is logged for debugging.

---

# 22. Logging

Create structured backend logging.

Every task should be traceable:

```text
TASK START
MODEL REQUEST
TOOL REQUEST
TOOL RESULT
MODEL RESPONSE
TASK COMPLETE
```

Do not log API keys, passwords, tokens, or sensitive file contents.

---

# 23. Security Rules

NEXUS has access to the user's computer.

Therefore:

* never expose API keys to the frontend
* never put `.env` values into Next.js
* never execute arbitrary destructive shell commands automatically
* never silently delete files
* never silently send external messages
* require permission for sensitive actions
* validate tool arguments
* log important tool executions
* keep the backend local by default

The backend should initially bind to:

```text
127.0.0.1
```

rather than exposing the agent to the local network.

---

# 24. What NOT To Build Yet

Do not implement these in the initial backend:

```text
❌ Multi-agent architecture
❌ Vector database
❌ PostgreSQL
❌ Redis
❌ Kafka
❌ Long-term memory
❌ Autonomous background agent
❌ Scheduled tasks
❌ Agent marketplace
❌ Complex planning system
❌ Computer vision
❌ Full GUI automation
❌ Dozens of MCP servers
```

First make the core agent reliable.

---

# 25. First End-to-End Goal

The first successful NEXUS workflow should be:

```text
User
 ↓
Next.js
 ↓
FastAPI
 ↓
LangGraph
 ↓
Groq
 ↓
MCP
 ↓
Mac Tool
 ↓
macOS
 ↓
Tool Result
 ↓
LangGraph
 ↓
FastAPI
 ↓
Next.js
```

Test request:

> "What is my Mac battery percentage?"

The agent should:

1. receive the request
2. determine that a system tool is required
3. call the appropriate MCP tool
4. receive the battery percentage
5. return the result
6. show the execution in the frontend

---

# 26. Second End-to-End Goal

After the first workflow works:

> "Open VS Code."

Flow:

```text
User
 ↓
Groq
 ↓
open_application
 ↓
Permission Check
 ↓
Mac MCP
 ↓
macOS
 ↓
Result
```

---

# 27. Third End-to-End Goal

Then:

> "Find my AI project and tell me its Git status."

The agent should:

```text
search_files
      ↓
find project
      ↓
inspect project
      ↓
git status
      ↓
summarize
```

This proves that NEXUS can perform a multi-step workflow.

---

# 28. Development Rules

When implementing this backend:

1. Keep modules small.
2. Use type hints.
3. Prefer async functions for network and agent operations.
4. Keep provider-specific code isolated.
5. Keep MCP-specific code isolated.
6. Keep FastAPI routes thin.
7. Keep LangGraph orchestration separate from API routes.
8. Never place business logic directly inside `main.py`.
9. Do not introduce a dependency unless it solves a real requirement.
10. Keep the system easy to understand and debug.

---

# 29. Definition of Done for Backend v0.1

Backend v0.1 is complete when:

* FastAPI starts successfully.
* `/health` works.
* Groq connection works.
* Mistral connection works.
* LangGraph agent runs.
* Tool calling works.
* MCP client can connect to a local test MCP server.
* One Mac capability works.
* Tool execution is logged.
* Permission handling exists for the first sensitive tool.
* Frontend can send a request to the backend.
* Frontend can receive execution events.
* Errors are handled cleanly.
* No API secrets are exposed to the frontend.

---

# 30. Architecture Summary

```text
                         NEXUS
                           │
                     Next.js UI
                           │
                    HTTP / WebSocket
                           │
                       FastAPI
                           │
                       LangGraph
                           │
                     Model Router
                     /           \
                  Groq          Mistral
                     \           /
                      \         /
                       Tool Layer
                           │
                       MCP Client
                           │
                    NEXUS Mac MCP
                           │
              ┌────────────┼────────────┐
              ↓            ↓            ↓
          Filesystem    macOS Apps    System
              │            │            │
              └────────────┼────────────┘
                           ↓
                         macOS
```

The guiding principle is:

> **NEXUS should understand intent, choose the appropriate tool, execute it safely, observe the result, and continue until the user's objective is complete.**

Build the simplest reliable version first. Add complexity only when a real use case requires it.
