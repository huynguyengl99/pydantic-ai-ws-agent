import type { ChatItem } from "../lib/chat-state";

const STATUS_LABEL = {
  running: "running",
  awaiting: "awaiting approval",
  done: "done",
  denied: "denied",
} as const;

function formatResult(result: unknown): string {
  // AG-UI carries tool results as an already-serialised string, so stringifying
  // one again would show it escaped and quoted.
  if (typeof result !== "string") return JSON.stringify(result);
  try {
    return JSON.stringify(JSON.parse(result));
  } catch {
    return result;
  }
}

export function ToolCallCard({
  item,
}: {
  item: Extract<ChatItem, { kind: "tool" }>;
}) {
  const { call, status, result } = item;
  return (
    <div className={`tool-card tool-${status}`}>
      <div className="tool-head">
        <span className="tool-glyph" aria-hidden>
          {status === "running"
            ? "◌"
            : status === "done"
              ? "●"
              : status === "awaiting"
                ? "◍"
                : "○"}
        </span>
        <span className="tool-name">{call.toolCallName}</span>
        <span className="tool-status">{STATUS_LABEL[status]}</span>
      </div>
      {call.args && <pre className="tool-args">{call.args}</pre>}
      {result !== undefined && (
        <pre className="tool-result">→ {formatResult(result)}</pre>
      )}
    </div>
  );
}
