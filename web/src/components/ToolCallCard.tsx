import type { ChatItem } from "../lib/chat-state";

const STATUS_LABEL = {
  running: "running",
  awaiting: "awaiting approval",
  done: "done",
  denied: "denied",
} as const;

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
        <span className="tool-name">{call.tool_name}</span>
        <span className="tool-status">{STATUS_LABEL[status]}</span>
      </div>
      <pre className="tool-args">{JSON.stringify(call.args, null, 0)}</pre>
      {result !== undefined && (
        <pre className="tool-result">→ {JSON.stringify(result)}</pre>
      )}
    </div>
  );
}
