import type { BaseEvent, Interrupt } from "@ag-ui/core";

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
  running: boolean;
}

export const initialState: ChatState = {
  items: [],
  tasks: [],
  toasts: [],
  running: false,
};

export type ChatAction =
  | { type: "event"; event: BaseEvent }
  | { type: "sent_prompt"; text: string }
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
    (item) => item.kind === "assistant" && item.id === id,
  );
  if (index === -1) {
    return [...items, { kind: "assistant", id, text: delta, streaming: true }];
  }
  const existing = items[index] as Extract<ChatItem, { kind: "assistant" }>;
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

function applyEvent(state: ChatState, event: BaseEvent): ChatState {
  switch (event.type) {
    case "RUN_STARTED":
      return { ...state, running: true };

    case "TEXT_MESSAGE_START":
      return state;

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

    case "CUSTOM": {
      if (field<string>(event, "name") !== "notification") return state;
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
      // AG-UI never echoes the prompt back, so the bubble is ours to add. A
      // second tab therefore will not show it until the answer arrives.
      return {
        ...state,
        running: true,
        items: [...state.items, { kind: "user", id: uid(), text: action.text }],
      };
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
