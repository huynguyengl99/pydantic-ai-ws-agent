import type { BaseEvent, RunAgentInput } from "@ag-ui/core";
import { useTopic } from "@chanx-js/client/react";
import { useCallback, useMemo } from "react";

import { agent } from "../generated";

export type SocketStatus = "connecting" | "open" | "closed";

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
  conversation: string,
  onEvent: (event: BaseEvent) => void,
): {
  status: SocketStatus;
  runAgent: (input: Partial<RunAgentInput>) => void;
} {
  // A new conversation is a new stream, so it starts numbering again.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the conversation
  const orderer = useMemo(() => createOrderer(), [conversation]);

  // Subscribing is what starts the flow: the topic replies with the task state,
  // then with the run in flight, if any.
  const { status, send } = useTopic(
    agent,
    agent.topics.taskletTopic.with({ thread_id: conversation }),
    {
      buffer: "none",
      on: {
        ag_ui_event: (message, { seq }) =>
          orderer(message.payload, seq, onEvent),
      },
    },
  );

  const runAgent = useCallback(
    (input: Partial<RunAgentInput>) => {
      send({
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
    [conversation, send],
  );

  return {
    status: status === "reconnecting" ? "connecting" : status,
    runAgent,
  };
}
