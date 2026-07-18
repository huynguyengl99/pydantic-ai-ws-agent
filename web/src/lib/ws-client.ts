import { useEffect } from "react";
import useWebSocket, { ReadyState } from "react-use-websocket";
import type { ClientMessage, ServerMessage } from "../generated/messages";

export type SocketStatus = "connecting" | "open" | "closed";

// Only the agent endpoint (ws or wss) is a valid target for this hook — a
// template-literal type turns a malformed url into a compile error.
export type AgentSocketUrl =
  `${"ws" | "wss"}://${string}/ws/agent?conversation=${string}`;

// Record<action, true> instead of an array: a newly generated server action that
// is missing here becomes a compile error rather than a silently dropped message.
const SERVER_ACTION_MAP: Record<ServerMessage["action"], true> = {
  user_message: true,
  stream_start: true,
  text_delta: true,
  tool_call: true,
  tool_result: true,
  approval_request: true,
  stream_end: true,
  suggestions: true,
  history: true,
  tasks_updated: true,
  notification: true,
  agent_error: true,
};

const SERVER_ACTIONS: ReadonlySet<string> = new Set(
  Object.keys(SERVER_ACTION_MAP),
);

// chanx can emit protocol frames (e.g. `complete`) alongside our contract —
// narrow to the messages the reducer knows about.
function isServerMessage(data: unknown): data is ServerMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    "action" in data &&
    SERVER_ACTIONS.has((data as { action: string }).action)
  );
}

const STATUS: Record<ReadyState, SocketStatus> = {
  [ReadyState.UNINSTANTIATED]: "closed",
  [ReadyState.CONNECTING]: "connecting",
  [ReadyState.OPEN]: "open",
  [ReadyState.CLOSING]: "closed",
  [ReadyState.CLOSED]: "closed",
};

export function useAgentSocket(
  url: AgentSocketUrl,
  onMessage: (msg: ServerMessage) => void,
): { status: SocketStatus; send: (msg: ClientMessage) => void } {
  const { sendJsonMessage, lastJsonMessage, readyState } =
    useWebSocket<ServerMessage>(url, {
      shouldReconnect: () => true,
      reconnectAttempts: 10,
      reconnectInterval: 3000,
      // chanx can emit protocol frames (e.g. `complete`) alongside the
      // contract; filtering them out here is what makes the generic honest —
      // `lastJsonMessage` only ever holds a ServerMessage.
      filter: (event) => {
        try {
          return isServerMessage(JSON.parse(event.data as string));
        } catch {
          return false;
        }
      },
    });

  useEffect(() => {
    if (lastJsonMessage !== null) onMessage(lastJsonMessage);
  }, [lastJsonMessage, onMessage]);

  return { status: STATUS[readyState], send: sendJsonMessage };
}
