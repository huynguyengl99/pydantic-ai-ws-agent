# WebSocket protocol reference

Endpoint: `ws://<host>/ws/agent`

The wire format is the [AG-UI protocol](https://ag-ui.com), carried inside two chanx
messages — one per direction. A client switches on `payload.type` exactly as it would
over SSE, so the protocol's own TypeScript package (`@ag-ui/core`) is the contract;
there is nothing project-specific to generate.

One connection serves any number of conversations. A conversation is a topic:

```
agui:thread:<conversation_id>
```

## The envelope

chanx routing metadata rides on the same flat frame as the message:

| field | meaning |
| --- | --- |
| `version` | envelope version, currently `1` |
| `topic` | which subscription the frame belongs to |
| `ref` | correlates a reply with the request that caused it |
| `seq` | per-run sequence number, present on broadcast run events |

`seq` sits beside the payload rather than inside it, so the AG-UI event is unmodified
and a client that ignores the envelope still reads a valid stream.

## Client → server

| action | payload | purpose |
| --- | --- | --- |
| `subscribe` | — | Join a conversation. Reply is `subscribed` |
| `ag_ui_run` | AG-UI `RunAgentInput` | Start a run, or resume a paused one |
| `unsubscribe` | — | Leave a conversation |

`RunAgentInput` carries `threadId`, `runId`, `messages`, `tools`, `state`,
`forwardedProps` and optionally `resume`.

**`messages` carries only the new turn.** The server holds the conversation, so there
is no need to resend it — and a resume sends `"messages": []`.

## Server → client

| action | payload |
| --- | --- |
| `ag_ui_event` | AG-UI `Event`, keyed on `type` |

The events this server emits:

| type | when |
| --- | --- |
| `RUN_STARTED` / `RUN_FINISHED` | brackets each run; `RUN_FINISHED` carries the outcome |
| `RUN_ERROR` | the run raised; `message` describes it |
| `TEXT_MESSAGE_START` / `_CONTENT` / `_END` | the answer, streamed per message id |
| `TOOL_CALL_START` / `_ARGS` / `_END` | a tool call, with arguments streamed as a JSON string |
| `TOOL_CALL_RESULT` | a tool returned |
| `STATE_SNAPSHOT` | the task list: `{"tasks": [{id, title, done}]}` |
| `CUSTOM` | `name: "notification"`, `value: {title, body}` |

`STATE_SNAPSHOT` is sent on subscribe, and again immediately before each run's last
event — including on `RUN_ERROR`, since a run that fails part-way through has still
changed the task list.

## On subscribe

A new subscription receives, in order:

1. `subscribed` — the reply, carrying your `ref`
2. `STATE_SNAPSHOT` — the current task list, with no `seq`
3. the run in flight, if any: every event so far, replayed with its original `seq`

Step 3 is what makes a mid-run refresh work. AG-UI has no way to join a stream in
progress — a content delta arriving before its `TEXT_MESSAGE_START` is malformed — so
the run is replayed from `RUN_STARTED` rather than picked up mid-flight.

## Ordering, and what the client owes you

Replayed and live events share one sequence, and both may be in flight at once. A
client applies them in order, drops what it has already applied, and holds a gap:

```ts
let expected: number | null = null;
const pending = new Map<number, BaseEvent>();

function onEvent(event: BaseEvent, seq: number | undefined) {
  if (seq === undefined) return apply(event);      // not part of a run
  if (event.type === "RUN_STARTED") expected = seq; // a run renumbers
  if (expected === null) expected = seq;
  if (seq < expected) return;                       // already applied via replay
  pending.set(seq, event);
  while (pending.has(expected)) {
    apply(pending.get(expected)!);
    pending.delete(expected++);
  }
}
```

`web/src/lib/ws-client.ts` is this, wired to a socket.

## Flow: a normal turn

```
client                                    server
  │ subscribe {topic}                        │
  │─────────────────────────────────────────▶│
  │◀──────────────────────────── subscribed  │
  │◀─────────────────────── STATE_SNAPSHOT   │  current task list
  │ ag_ui_run {messages: [user turn]}        │
  │─────────────────────────────────────────▶│
  │◀──────────────────────────  RUN_STARTED  │  seq 1
  │◀─────────────── TOOL_CALL_START/ARGS/END │  add_task
  │◀────────────────────── TOOL_CALL_RESULT  │
  │◀──────────── TEXT_MESSAGE_START/CONTENT… │
  │◀─────────────────────── STATE_SNAPSHOT   │  tasks after the run
  │◀───────────────────────── RUN_FINISHED   │  outcome: success
```

## Flow: human-in-the-loop approval

```
client                                    server
  │ ag_ui_run {"delete task 2"}              │
  │─────────────────────────────────────────▶│
  │◀──────────────────────────  RUN_STARTED  │
  │◀─────────────── TOOL_CALL_START/ARGS/END │  delete_task — not executed
  │◀───────────────────────── RUN_FINISHED   │  outcome: interrupt
  │                                          │    interrupts: [{id, message,
  │                                          │      toolCallId, responseSchema}]
  │ ag_ui_run {messages: [], resume: [...]}  │  from ANY tab, at any time
  │─────────────────────────────────────────▶│
  │◀──────────────────────────  RUN_STARTED  │  seq restarts at 1
  │◀────────────────────── TOOL_CALL_RESULT  │  the tool now executes
  │◀──────────── TEXT_MESSAGE_START/CONTENT… │
  │◀─────────────────────── STATE_SNAPSHOT   │
  │◀───────────────────────── RUN_FINISHED   │  outcome: success
```

A resume entry looks like:

```json
{
  "interruptId": "int-call-1",
  "status": "resolved",
  "payload": { "approved": true }
}
```

Approval is **deny-by-default**: only an explicit `approved: true` runs the tool.
Anything else denies it, optionally with a `reason` the model is told about — the run
still finishes normally, it just skips the tool.

Notes for client authors:

- The paused tool call arrives as a normal `TOOL_CALL_*` sequence, *then*
  `RUN_FINISHED` says it is waiting. Mark the card from the interrupt's `toolCallId`.
- Because runs broadcast, another tab may resolve the approval. A `RUN_STARTED` you
  did not send means someone else answered.
- A resume is a new run with a new `runId`, so `seq` starts again at 1.

## Conversation management (plain HTTP)

The conversation list spans conversations, so it lives on REST rather than on a
per-conversation topic:

```
GET    /conversations                   -> [{id, title, updated_at}]   # newest first
DELETE /conversations/{conversation_id} -> {"deleted": true} | 404     # also deletes its tasks
```

Titles are set from the first user prompt, truncated to 60 characters. The web client
refetches the list on connect and after each `RUN_FINISHED`.

## Broadcast from HTTP

```
POST /conversations/{conversation_id}/notify
{"title": "Reminder", "body": "Stand-up in 5 minutes"}
```

Every client on the conversation receives a `CUSTOM` event named `notification`. The
`schedule_reminder` tool works the same way from the inside: the tool schedules a
background job, the run finishes normally, and the job emits into the thread when it
fires — ask *"remind me in 15 seconds to stretch"* to watch it.

Both paths call `TaskletTopic.emit_to_thread`, which holds no socket of its own, so
any worker or signal can do the same.

## AsyncAPI

`GET /asyncapi` documents the channel and its two actions. It describes the
*transport* — how AG-UI is carried — not the protocol's event union, which is
specified by AG-UI itself.
