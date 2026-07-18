import type {
  ServerMessage,
  TaskItem,
  ToolCallPayload,
} from "../generated/messages";

export type ChatItem =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string; streaming: boolean }
  | {
      kind: "tool";
      id: string;
      call: ToolCallPayload;
      status: "running" | "awaiting" | "done" | "denied";
      result?: unknown;
    }
  | {
      kind: "approval";
      id: string;
      calls: ToolCallPayload[];
      resolved: "approved" | "denied" | "remote" | null;
    }
  | { kind: "notification"; id: string; title: string; body: string }
  | { kind: "error"; id: string; detail: string };

export interface Toast {
  id: string;
  title: string;
  body: string;
}

export interface ChatState {
  items: ChatItem[];
  tasks: TaskItem[];
  toasts: Toast[];
  suggestions: string[];
  running: boolean;
  usage: { input: number; output: number };
}

export const initialState: ChatState = {
  items: [],
  tasks: [],
  toasts: [],
  suggestions: [],
  running: false,
  usage: { input: 0, output: 0 },
};

export type ChatAction =
  | { type: "server"; msg: ServerMessage }
  | { type: "sent_prompt" }
  | {
      type: "resolved_approval";
      id: string;
      approved: boolean;
      callIds: string[];
    }
  | { type: "dismiss_toast"; id: string }
  | { type: "reset" };

let nextId = 0;
const uid = () => `item-${nextId++}`;

function withAssistantDelta(items: ChatItem[], delta: string): ChatItem[] {
  const last = items[items.length - 1];
  if (last?.kind === "assistant" && last.streaming) {
    return [...items.slice(0, -1), { ...last, text: last.text + delta }];
  }
  return [
    ...items,
    { kind: "assistant", id: uid(), text: delta, streaming: true },
  ];
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "reset":
      return initialState;
    case "dismiss_toast":
      return {
        ...state,
        toasts: state.toasts.filter((toast) => toast.id !== action.id),
      };
    case "sent_prompt":
      // The user bubble itself arrives via the `user_message` broadcast, so
      // every tab (this one included) renders it from the same event.
      return { ...state, running: true, suggestions: [] };
    case "resolved_approval":
      return {
        ...state,
        running: true,
        items: state.items.map((item) => {
          if (item.kind === "approval" && item.id === action.id) {
            return {
              ...item,
              resolved: action.approved ? "approved" : "denied",
            };
          }
          if (
            item.kind === "tool" &&
            item.status === "awaiting" &&
            action.callIds.includes(item.call.tool_call_id) &&
            !action.approved
          ) {
            return { ...item, status: "denied" };
          }
          return item;
        }),
      };
    case "server":
      return applyServer(state, action.msg);
  }
}

function applyServer(state: ChatState, msg: ServerMessage): ChatState {
  switch (msg.action) {
    case "user_message":
      return {
        ...state,
        running: true,
        suggestions: [],
        items: [
          ...state.items,
          { kind: "user", id: uid(), text: msg.payload.text },
        ],
      };
    case "stream_start":
      return { ...state, running: true, suggestions: [] };
    case "text_delta":
      return {
        ...state,
        items: withAssistantDelta(state.items, msg.payload.delta),
      };
    case "tool_call": {
      // An approved deferred call is re-announced on resume with the same id —
      // flip the existing card back to running instead of duplicating it.
      const seen = state.items.some(
        (item) =>
          item.kind === "tool" &&
          item.call.tool_call_id === msg.payload.tool_call_id,
      );
      return {
        ...state,
        items: seen
          ? state.items.map((item) =>
              item.kind === "tool" &&
              item.call.tool_call_id === msg.payload.tool_call_id
                ? { ...item, status: "running" as const }
                : item,
            )
          : [
              ...state.items,
              { kind: "tool", id: uid(), call: msg.payload, status: "running" },
            ],
      };
    }
    case "tool_result":
      return {
        ...state,
        items: state.items.map((item) =>
          item.kind === "tool" &&
          item.call.tool_call_id === msg.payload.tool_call_id &&
          item.status !== "denied"
            ? { ...item, status: "done", result: msg.payload.content }
            : item,
        ),
      };
    case "approval_request": {
      const pendingIds = msg.payload.calls.map((c) => c.tool_call_id);
      return {
        ...state,
        running: false,
        items: [
          ...state.items.map((item) =>
            item.kind === "tool" && pendingIds.includes(item.call.tool_call_id)
              ? { ...item, status: "awaiting" as const }
              : item,
          ),
          {
            kind: "approval",
            id: uid(),
            calls: msg.payload.calls,
            resolved: null,
          },
        ],
      };
    }
    case "stream_end": {
      // The run only continues after pending approvals were decided — if this
      // tab still shows an open card, it was resolved from another connection.
      const settled = state.items.map((item) =>
        item.kind === "approval" && item.resolved === null
          ? { ...item, resolved: "remote" as const }
          : item,
      );
      const last = settled[settled.length - 1];
      let items: ChatItem[];
      if (last?.kind === "assistant" && last.streaming) {
        items = [
          ...settled.slice(0, -1),
          { ...last, text: msg.payload.text, streaming: false },
        ];
      } else if (msg.payload.text) {
        items = [
          ...settled,
          {
            kind: "assistant",
            id: uid(),
            text: msg.payload.text,
            streaming: false,
          },
        ];
      } else {
        items = settled;
      }
      return {
        ...state,
        running: false,
        items,
        usage: {
          input: state.usage.input + msg.payload.usage.input_tokens,
          output: state.usage.output + msg.payload.usage.output_tokens,
        },
      };
    }
    case "history":
      return {
        ...state,
        items: msg.payload.items.map((item): ChatItem =>
          item.kind === "text"
            ? item.role === "user"
              ? { kind: "user", id: uid(), text: item.content }
              : {
                  kind: "assistant",
                  id: uid(),
                  text: item.content,
                  streaming: false,
                }
            : {
                kind: "tool",
                id: uid(),
                call: {
                  tool_call_id: item.tool_call_id,
                  tool_name: item.tool_name,
                  args: item.args,
                },
                status: item.status,
                result: item.result ?? undefined,
              },
        ),
      };
    case "suggestions":
      return { ...state, suggestions: msg.payload.follow_ups };
    case "tasks_updated":
      return { ...state, tasks: msg.payload.tasks };
    case "notification":
      return {
        ...state,
        items: [
          ...state.items,
          {
            kind: "notification",
            id: uid(),
            title: msg.payload.title,
            body: msg.payload.body,
          },
        ],
        toasts: [
          ...state.toasts,
          { id: uid(), title: msg.payload.title, body: msg.payload.body },
        ],
      };
    case "agent_error":
      return {
        ...state,
        running: false,
        items: [
          ...state.items,
          { kind: "error", id: uid(), detail: msg.payload.detail },
        ],
      };
  }
}
