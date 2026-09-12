import type { BaseEvent, RunAgentInput } from "@ag-ui/core";
import { useCallback, useEffect, useMemo, useRef } from "react";
import useWebSocket, { ReadyState } from "react-use-websocket";

export type SocketStatus = "connecting" | "open" | "closed";

export type AgentSocketUrl = `${"ws" | "wss"}://${string}/ws/agent`;

/** chanx routing metadata, carried beside the message on the same frame. */
interface Envelope {
  version: 1;
  topic: string;
  ref?: string;
  seq?: number;
}

type Frame = Envelope & { action: string; payload?: unknown };

export const threadTopic = (conversation: string) =>
  `agui:thread:${conversation}`;

function isAgUiEvent(frame: unknown): frame is Frame & { payload: BaseEvent } {
  return (
    typeof frame === "object" &&
    frame !== null &&
    (frame as Frame).action === "ag_ui_event"
  );
}

/**
 * Apply run events in sequence order.
 *
 * A connection joining mid-run is replayed the run so far, which can overlap
 * with what is already arriving live. The server numbers each run's events, so
 * anything already applied is dropped and a gap is held until it fills.
 */
function createOrderer() {
  let expected: number | null = null;
  const pending = new Map<number, BaseEvent>();

  return (
    event: BaseEvent,
    seq: number | undefined,
    apply: (event: BaseEvent) => void,
  ) => {
    if (seq === undefined) {
      apply(event);
      return;
    }
    // A run restarts the sequence, so trust its RUN_STARTED over what came before.
    if (event.type === "RUN_STARTED") {
      expected = seq;
      pending.clear();
    }
    if (expected === null) expected = seq;
    if (seq < expected) return;

    pending.set(seq, event);
    while (pending.has(expected)) {
      apply(pending.get(expected)!);
      pending.delete(expected);
      expected += 1;
    }
  };
}

export function useAgentSocket(
  url: AgentSocketUrl,
  conversation: string,
  onEvent: (event: BaseEvent) => void,
): {
  status: SocketStatus;
  runAgent: (input: Partial<RunAgentInput> & { messages?: unknown[] }) => void;
} {
  const topic = useMemo(() => threadTopic(conversation), [conversation]);

  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  // A new conversation is a new stream, so it starts numbering again.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the topic
  const orderer = useMemo(() => createOrderer(), [topic]);

  const { sendJsonMessage, lastJsonMessage, readyState } = useWebSocket<Frame>(
    url,
    {
      shouldReconnect: () => true,
      reconnectAttempts: 10,
      reconnectInterval: 3000,
      filter: (event) => {
        try {
          return isAgUiEvent(JSON.parse(event.data as string));
        } catch {
          return false;
        }
      },
    },
  );

  // Subscribing is what starts the flow: the topic replies with the task state,
  // then with the run in flight, if any.
  useEffect(() => {
    if (readyState !== ReadyState.OPEN) return;
    sendJsonMessage({ version: 1, topic, ref: "1", action: "subscribe" });
  }, [readyState, topic, sendJsonMessage]);

  useEffect(() => {
    if (lastJsonMessage === null || !isAgUiEvent(lastJsonMessage)) return;
    orderer(lastJsonMessage.payload, lastJsonMessage.seq, onEventRef.current);
  }, [lastJsonMessage, orderer]);

  const runAgent = useCallback(
    (input: Partial<RunAgentInput> & { messages?: unknown[] }) => {
      sendJsonMessage({
        version: 1,
        topic,
        action: "ag_ui_run",
        payload: {
          threadId: conversation,
          runId: crypto.randomUUID(),
          state: {},
          messages: [],
          tools: [],
          context: [],
          forwardedProps: {},
          ...input,
        },
      });
    },
    [conversation, topic, sendJsonMessage],
  );

  const status: SocketStatus =
    readyState === ReadyState.OPEN
      ? "open"
      : readyState === ReadyState.CONNECTING
        ? "connecting"
        : "closed";

  return { status, runAgent };
}
