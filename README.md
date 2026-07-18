# Pydantic AI over typed WebSockets

A production-style AI agent server built with [Pydantic AI](https://pydantic.dev/docs/ai/),
FastAPI, and [chanx](https://github.com/huynguyengl99/chanx) typed WebSockets — plus a React
client whose types are generated from the server's AsyncAPI contract.

![Tasklet — live tool calls, a destructive tool paused for approval, and the per-conversation task list](assets/image.png)

The demo agent ("Tasklet") manages a task list and showcases:

- **Streaming structured output** — the agent's output is a `TextAnswer {content, follow_ups}`;
  `agent.run_stream()` + partial validation stream the growing `content` as text deltas while
  tool-call events arrive via an `event_stream_handler`, all over one WebSocket
- **Broadcast architecture** — each run executes as a background task and broadcasts its
  events to a per-conversation channel-layer group; every connected tab receives the same
  stream, and a page refresh mid-run keeps streaming. In-memory layer by default, Redis
  pub/sub with one env var (`REDIS_URL`) for multi-instance
- **Human-in-the-loop approvals** — destructive tools (`delete_task`, `clear_all_tasks`) are
  declared with `requires_approval=True`; the run pauses with `DeferredToolRequests`, the user
  approves or denies in the UI (from *any* connection), and the run resumes with
  `DeferredToolResults`
- **Conversations with scoped state** — a sidebar lists auto-titled conversations
  (`GET /conversations`, title = first prompt); each conversation has its **own task list**
  (tools read the conversation id from `RunContext[AgentDeps]`), and deleting one removes
  its history and tasks
- **A real paper trail** — reload replays the full transcript from stored pydantic-ai
  messages: text, tool cards with args/results/status (`done` / `denied` / `awaiting`),
  and a still-pending approval card that remains actionable
- **Follow-up suggestions** — the structured answer carries 3 chip-sized next prompts,
  generated in the same completion as the text and broadcast as a `suggestions` message
- **Broadcast from anywhere** — `POST /conversations/{id}/notify` pushes a typed notification
  to all of a conversation's sockets from plain HTTP (the in-app **Notify** button uses it too),
  via chanx's `broadcast_event`
- **Background jobs that notify back** — a `schedule_reminder` agent tool schedules an
  in-process job that later broadcasts a notification into the conversation ("remind me in
  30 seconds to stretch"); a real worker (ARQ, Celery) would call the same `broadcast_event`
- **A typed contract** — chanx generates AsyncAPI 3.0 docs from the consumer; a small script
  turns that schema into TypeScript discriminated unions for the client
- **Offline tests + strict typing** — the whole WebSocket flow (multi-tab broadcast,
  cross-connection approval, transcript replay) is tested without an LLM using pydantic-ai's
  `FunctionModel` / `TestModel` and chanx's `WebsocketCommunicator`; the server passes
  strict mypy **and** strict pyright

Companion repo for the blog post:
[Streaming Agents and Human-in-the-Loop with Pydantic AI over Typed WebSockets](https://huynguyengl99.github.io/posts/pydantic-ai-typed-websockets-fastapi/).

## How it works

- **[docs/architecture.md](docs/architecture.md)** — how the pieces fit: the agent and
  deferred tools, the harness that translates pydantic-ai events into typed messages,
  background runs broadcasting to conversation groups, the channel layer, codegen, and
  the testing approach
- **[docs/protocol.md](docs/protocol.md)** — every WebSocket message with payloads, plus
  sequence diagrams for a streaming turn, the approval round trip, and HTTP notifications

## Run it

Server (Python 3.11+, [uv](https://docs.astral.sh/uv/)):

```bash
cd server
cp .env.example .env   # add OPENAI_API_KEY (or ANTHROPIC_API_KEY / AGENT_MODEL)
uv sync
uv run uvicorn app.main:app --port 8000
```

Without any API key the server falls back to pydantic-ai's built-in `test` model, so
everything still runs — the responses are just synthetic.

There is no migration tooling: if the SQLite schema changes between versions, delete
the local database (`rm server/tasklet.db`) and let the server recreate it.

Web:

```bash
cd web
pnpm install
pnpm dev    # http://localhost:5173
```

Then try the flow (the in-app **Help** button walks through it too):

1. *"Add three tasks for launching my blog post"* — watch the tool cards and the task panel,
   then click one of the suggested follow-up chips
2. *"Mark the first one as done"*
3. *"Delete the second task"* — the run pauses with an approval card; approve or deny.
   Refresh mid-approval: the transcript (tool cards included) and the approval card come back
4. Open a second tab (same conversation): both tabs stream identically, and either can approve
5. Hit **+ New chat** — a fresh conversation with an empty task list; switch back and forth
   in the sidebar (each keeps its own tasks and history)
6. Push a notification with the **Notify** button, or from plain HTTP:
   `curl -X POST localhost:8000/conversations/<id>/notify -H 'Content-Type: application/json' -d '{"title":"Hi","body":"from curl"}'`
7. *"Remind me in 15 seconds to stretch"* — the agent schedules a job that notifies back

AsyncAPI docs: <http://localhost:8000/asyncapi> (spec at `/asyncapi.json`).

Regenerate the TypeScript message types after changing server messages:

```bash
pnpm generate   # fetches /asyncapi.json and rewrites src/generated/messages.ts
```

## Scaling out with Redis

The demo defaults to an in-memory channel layer (single process). To broadcast across
multiple server instances or workers, start Redis and point the server at it:

```bash
docker compose up -d redis

cd server
REDIS_URL=redis://localhost:6379 uv run uvicorn app.main:app --port 8000
# in another terminal — a second instance, same conversation state:
REDIS_URL=redis://localhost:6379 uv run uvicorn app.main:app --port 8001
```

Connect one browser tab to each instance with the same `?conversation=` id — both
receive the same stream, and an approval on either instance resumes the run. Nothing
in the code changes; only the channel layer does.

## Tests, lint & type checks

```bash
cd server
uv run pytest
uv run ruff check app tests && uv run ruff format --check app tests
uv run mypy app tests   # strict
uv run pyright          # strict

cd web
pnpm check   # eslint + prettier + tsc
```

## Layout

```
server/app/main.py               # FastAPI: /conversations list/delete, /notify, AsyncAPI docs
server/app/config.py             # typed settings (pydantic-settings), reads .env
server/app/db.py                 # SQLite: per-conversation tasks + history + titles
server/app/layers.py             # channel layer: in-memory default, Redis via REDIS_URL
server/app/ws.py                 # BaseConsumer: shared consumer defaults
server/app/assistant/            # the feature app: agent + protocol + consumer together
  agent.py                       #   Agent, per-conversation tools, TextAnswer output
  harness.py                     #   pydantic-ai streaming -> typed WS messages, replay, approvals
  messages.py                    #   the WebSocket message contract (Pydantic models)
  consumer.py                    #   chanx consumer: background runs, group broadcast
  reminders.py                   #   background jobs that notify back into the group
web/scripts/generate-types.mjs   # AsyncAPI -> TypeScript codegen
web/src/lib/ws-client.ts         # typed WebSocket client (react-use-websocket)
web/src/lib/chat-state.ts        # server events -> UI state reducer
web/src/lib/conversations.ts     # REST client for the conversation sidebar
```
