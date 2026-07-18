# WebSocket protocol reference

Endpoint: `ws://<host>/ws/agent?conversation=<id>`

Every message is JSON with a discriminating `action` field and a `payload`. The
authoritative, always-up-to-date contract is the AsyncAPI schema at
`/asyncapi.json` (interactive docs at `/asyncapi`) — this page is a readable summary.
Clients should ignore unknown actions (chanx can emit protocol messages like
`complete` when completion signals are enabled).

## Client → server

| action          | payload                                                                 | purpose                                    |
| --------------- | ----------------------------------------------------------------------- | ------------------------------------------ |
| `chat`          | `{text: string}`                                                        | Start one agent turn                       |
| `tool_decision` | `{decisions: [{tool_call_id, approved, override_args?, reason?}]}`      | Resolve a pending `approval_request`       |

## Server → client

| action             | payload                                              | when                                                   |
| ------------------ | ---------------------------------------------------- | ------------------------------------------------------ |
| `user_message`     | `{text}`                                             | Echo of the user's prompt, broadcast before `stream_start` — every tab (the sender included) renders the bubble from this |
| `history`          | `{conversation_id, items: TranscriptItem[]}`         | On connect — full transcript replay (text **and** tool cards) |
| `tasks_updated`    | `{tasks: [{id, title, done}]}`                       | On connect, and after any run that executed tools — scoped to this conversation |
| `stream_start`     | `{conversation_id}`                                  | A run (or resume) began                                |
| `text_delta`       | `{delta: string}`                                    | Streaming chunk of the assistant's text                |
| `tool_call`        | `{tool_call_id, tool_name, args}`                    | The model called a tool (also fires for deferred calls) |
| `tool_result`      | `{tool_call_id, content}`                            | A tool finished                                        |
| `approval_request` | `{calls: [{tool_call_id, tool_name, args}]}`         | Run paused — destructive calls need a `tool_decision`. Also **replayed on connect** while still pending |
| `stream_end`       | `{text, usage: {input_tokens, output_tokens}}`       | Run finished with final text                           |
| `suggestions`      | `{follow_ups: string[]}`                             | Right after `stream_end` — 3 suggested next prompts from the same structured answer (absent when the model returns none). The latest set is persisted and **replayed on connect**; it is cleared server-side when the next run starts |
| `notification`     | `{title, body}`                                      | Out-of-band push: the `/notify` HTTP endpoint, the in-app Notify button, or a fired `schedule_reminder` job |
| `agent_error`      | `{detail: string}`                                   | Run failed, or request rejected (e.g. run in progress) |

`TranscriptItem` is a union discriminated on `kind`:

- `{kind: "text", role: "user" | "assistant", content}`
- `{kind: "tool", tool_call_id, tool_name, args, status: "done" | "denied" | "awaiting", result?}`

so a reload renders the same tool cards as the live stream. A `denied` status comes
from the persisted tool outcome; `awaiting` means the call has no result yet — the
accompanying replayed `approval_request` makes it actionable again.

## On connect

Each new socket receives, in order: `history` → `tasks_updated` → `suggestions`
(only if the last completed answer produced chips) → `approval_request` (only if a
decision is still pending for this conversation).

## Flow: a normal streaming turn

```
client                              server
  │ chat {text}                       │
  │──────────────────────────────────▶│  (run starts as a background task)
  │◀──────────────────── user_message │  echo of the prompt, to every tab
  │◀───────────────────  stream_start │
  │◀────────────────────── tool_call  │  add_task {"title": "…"}
  │◀──────────────────── tool_result  │
  │◀───────────── text_delta × N ──── │
  │◀─────────────────── tasks_updated │
  │◀────────────────────── stream_end │
  │◀─────────────────────  suggestions│  3 follow-up chips (from the same structured answer)
```

## Flow: human-in-the-loop approval

```
client                              server
  │ chat {"delete task 2"}            │
  │──────────────────────────────────▶│
  │◀──────────────────── user_message │
  │◀───────────────────  stream_start │
  │◀────────────────────── tool_call  │  delete_task — shown as "awaiting approval"
  │◀──────────────── approval_request │  run pauses; history persisted
  │                                   │
  │ tool_decision {approved: true}    │  (may come from ANY connection
  │──────────────────────────────────▶│   in the conversation, later)
  │◀───────────────────  stream_start │  run resumes with DeferredToolResults
  │◀────────────────────── tool_call  │  same tool_call_id — the tool now executes
  │◀──────────────────── tool_result  │
  │◀───────────── text_delta × N ──── │
  │◀─────────────────── tasks_updated │
  │◀────────────────────── stream_end │
```

Denial (`approved: false`, optional `reason`) follows the same shape: the tool does
not execute, the model receives the denial message, and the run still ends with
`stream_end`.

Notes for client authors:

- The `tool_call` for a deferred tool is **re-announced with the same
  `tool_call_id`** when the run resumes — dedupe on the id instead of appending.
  The same dedupe makes replayed `awaiting` transcript cards flip to running.
- Because events are broadcast to the whole conversation group, another tab may
  resolve the approval. If a `stream_end` arrives while your approval UI is still
  open, treat those cards as resolved elsewhere.
- Only one run per conversation is allowed at a time; a `chat` or `tool_decision`
  sent mid-run is answered with `agent_error`.
- Clear `suggestions` when the next run starts (`stream_start`) — they describe the
  previous answer.

## Conversation management (plain HTTP)

The conversation list is cross-conversation state, so it lives on REST rather than
the (per-conversation) WebSocket:

```
GET    /conversations                  -> [{id, title, updated_at}]   # newest first
DELETE /conversations/{conversation_id} -> {"deleted": true} | 404    # also deletes its tasks
```

Titles are set automatically from the first user prompt (truncated to 60 chars).
Deleting a conversation cancels any in-flight run and drops its pending approvals.
The web client refetches the list on connect and after each `stream_end`.

## Broadcast from HTTP

```
POST /conversations/{conversation_id}/notify
{"title": "Reminder", "body": "Stand-up in 5 minutes"}
```

Every socket in the conversation group receives a `notification` message (shown as a
toast and an inline transcript item) — the same mechanism any background worker can
use via `AgentConsumer.broadcast_event(...)`.

The `schedule_reminder` agent tool works the same way from the inside: the tool
schedules a background job (see `server/app/assistant/reminders.py`), the run finishes
normally, and when the job fires it broadcasts a `notification` into the group —
ask *"remind me in 15 seconds to stretch"* to see it.

## Regenerating the TypeScript client

```bash
cd web
pnpm generate            # fetches http://localhost:8000/asyncapi.json
# or: node scripts/generate-types.mjs <url-or-path-to-asyncapi.json>
```

The script writes `web/src/generated/messages.ts` (`ClientMessage` / `ServerMessage`
discriminated unions). After a contract change, `tsc` reports every client site that
needs updating.
