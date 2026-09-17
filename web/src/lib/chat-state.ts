import type { BaseEvent, Interrupt, Message } from "@ag-ui/core";

export interface TaskItem {
  id: number;
  title: string;
  done: boolean;
}

export interface ToolCall {
  toolCallId: string;
  toolCallName: string;
  args: string;
}

export type ChatItem =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string; streaming: boolean }
  | {
      kind: "tool";
      id: string;
      call: ToolCall;
      status: "running" | "awaiting" | "done" | "denied";
      result?: unknown;
    }
  | {
      kind: "approval";
      id: string;
      interrupts: Interrupt[];
      resolved: "approved" | "denied" | "remote" | null;
    }
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
}

export const initialState: ChatState = {
  items: [],
  tasks: [],
  toasts: [],
  suggestions: [],
  running: false,
};

export type ChatAction =
  | { type: "event"; event: BaseEvent }
  | { type: "sent_prompt" }
  | { type: "resolved_approval"; id: string; approved: boolean }
  | { type: "dismiss_toast"; id: string }
  | { type: "reset" };

let nextId = 0;
const uid = () => `item-${nextId++}`;

/** Narrow an AG-UI event, whose union is keyed on `type`. */
function field<T>(event: BaseEvent, name: string): T {
  return (event as unknown as Record<string, T>)[name];
}

function appendDelta(items: ChatItem[], id: string, delta: string): ChatItem[] {
  const index = items.findIndex(
    (item) =>
      (item.kind === "assistant" || item.kind === "user") && item.id === id,
  );
  if (index === -1) {
    return [...items, { kind: "assistant", id, text: delta, streaming: true }];
  }
  const existing = items[index] as Extract<
    ChatItem,
    { kind: "assistant" | "user" }
  >;
  const updated: ChatItem = { ...existing, text: existing.text + delta };
  return [...items.slice(0, index), updated, ...items.slice(index + 1)];
}

function updateTool(
  items: ChatItem[],
  toolCallId: string,
  change: Partial<Extract<ChatItem, { kind: "tool" }>>,
): ChatItem[] {
  return items.map((item) =>
    item.kind === "tool" && item.call.toolCallId === toolCallId
      ? { ...item, ...change }
      : item,
  );
}

/**
 * A stored conversation, as chat items.
 *
 * Tool results arrive as their own `role: "tool"` messages keyed by call id, so
 * they are indexed first and then folded into the call they answer.
 */
/** User content may be multimodal; the transcript shows its text. */
function plainText(content: Message["content"]): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => (part.type === "text" ? part.text : `[${part.type}]`))
    .join(" ");
}

export function transcriptItems(messages: Message[]): ChatItem[] {
  const results = new Map<string, unknown>();
  for (const message of messages) {
    if (message.role === "tool") {
      results.set(message.toolCallId, message.content);
    }
  }

  const items: ChatItem[] = [];
  for (const message of messages) {
    if (message.role === "user") {
      items.push({
        kind: "user",
        id: message.id,
        text: plainText(message.content),
      });
      continue;
    }
    if (message.role !== "assistant") continue;

    if (message.content) {
      items.push({
        kind: "assistant",
        id: message.id,
        text: message.content,
        streaming: false,
      });
    }
    for (const call of message.toolCalls ?? []) {
      const result = results.get(call.id);
      items.push({
        kind: "tool",
        id: call.id,
        // A call with no result never ran: it is still waiting on approval.
        status: result === undefined ? "awaiting" : "done",
        result,
        call: {
          toolCallId: call.id,
          toolCallName: call.function.name,
          args: call.function.arguments,
        },
      });
    }
  }
  return items;
}

function applyEvent(state: ChatState, event: BaseEvent): ChatState {
  switch (event.type) {
    case "RUN_STARTED":
      // A run starting while a card is unresolved means another tab answered
      // the interrupt: this one would stay blocked on it otherwise.
      return {
        ...state,
        running: true,
        suggestions: [],
        items: state.items.map((item) =>
          item.kind === "approval" && item.resolved === null
            ? { ...item, resolved: "remote" }
            : item,
        ),
      };

    case "TEXT_MESSAGE_START": {
      // The server echoes the prompt so every tab renders it from the run
      // rather than from having been the one that sent it.
      if (field<string>(event, "role") !== "user") return state;
      const id = field<string>(event, "messageId");
      if (state.items.some((item) => item.kind === "user" && item.id === id)) {
        return state;
      }
      return {
        ...state,
        items: [...state.items, { kind: "user", id, text: "" }],
      };
    }

    case "TEXT_MESSAGE_CONTENT":
      return {
        ...state,
        items: appendDelta(
          state.items,
          field<string>(event, "messageId"),
          field<string>(event, "delta"),
        ),
      };

    case "TEXT_MESSAGE_END": {
      const id = field<string>(event, "messageId");
      return {
        ...state,
        items: state.items.map((item) =>
          item.kind === "assistant" && item.id === id
            ? { ...item, streaming: false }
            : item,
        ),
      };
    }

    case "TOOL_CALL_START":
      return {
        ...state,
        items: [
          ...state.items,
          {
            kind: "tool",
            id: uid(),
            status: "running",
            call: {
              toolCallId: field<string>(event, "toolCallId"),
              toolCallName: field<string>(event, "toolCallName"),
              args: "",
            },
          },
        ],
      };

    case "TOOL_CALL_ARGS": {
      const toolCallId = field<string>(event, "toolCallId");
      const delta = field<string>(event, "delta");
      return {
        ...state,
        items: state.items.map((item) =>
          item.kind === "tool" && item.call.toolCallId === toolCallId
            ? { ...item, call: { ...item.call, args: item.call.args + delta } }
            : item,
        ),
      };
    }

    case "TOOL_CALL_RESULT": {
      const toolCallId = field<string>(event, "toolCallId");
      return {
        ...state,
        items: updateTool(state.items, toolCallId, {
          status: "done",
          result: field<unknown>(event, "content"),
        }),
      };
    }

    case "STATE_SNAPSHOT": {
      const snapshot = field<{ tasks?: TaskItem[] }>(event, "snapshot");
      return { ...state, tasks: snapshot?.tasks ?? state.tasks };
    }

    case "MESSAGES_SNAPSHOT": {
      // The conversation as the server has it. Replaces what is on screen rather
      // than appending: this is the truth, and a reconnect must not double it.
      const messages = field<Message[]>(event, "messages") ?? [];
      return { ...state, items: transcriptItems(messages) };
    }

    case "CUSTOM": {
      const name = field<string>(event, "name");
      if (name === "suggestions") {
        const value = field<{ prompts?: string[] }>(event, "value");
        return { ...state, suggestions: value?.prompts ?? [] };
      }
      if (name !== "notification") return state;
      const value = field<{ title: string; body: string }>(event, "value");
      return {
        ...state,
        toasts: [...state.toasts, { id: uid(), ...value }],
      };
    }

    case "RUN_FINISHED": {
      const outcome = field<
        { type: string; interrupts?: Interrupt[] } | undefined
      >(event, "outcome");
      if (outcome?.type === "interrupt" && outcome.interrupts?.length) {
        // A paused run is still the client's turn: the approval card is the
        // only thing that can resume it.
        const waiting = outcome.interrupts;
        return {
          ...state,
          running: false,
          items: [
            ...waiting.reduce(
              (items, interrupt) =>
                updateTool(items, interrupt.toolCallId ?? "", {
                  status: "awaiting",
                }),
              state.items,
            ),
            {
              kind: "approval",
              id: uid(),
              interrupts: waiting,
              resolved: null,
            },
          ],
        };
      }
      return { ...state, running: false };
    }

    case "RUN_ERROR":
      return {
        ...state,
        running: false,
        items: [
          ...state.items,
          { kind: "error", id: uid(), detail: field<string>(event, "message") },
        ],
      };

    default:
      return state;
  }
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
      // The bubble arrives with the run, the same as it does for every other
      // tab, so there is nothing to add here.
      return { ...state, running: true };
    case "resolved_approval":
      return {
        ...state,
        items: state.items.map((item) =>
          item.kind === "approval" && item.id === action.id
            ? { ...item, resolved: action.approved ? "approved" : "denied" }
            : item,
        ),
      };
    case "event":
      return applyEvent(state, action.event);
  }
}
