import type { ChatItem } from "../lib/chat-state";

interface Props {
  item: Extract<ChatItem, { kind: "approval" }>;
  onDecide: (approved: boolean) => void;
}

export function ApprovalCard({ item, onDecide }: Props) {
  return (
    <div
      className={`approval-card ${item.resolved ? "approval-resolved" : ""}`}
    >
      <div className="approval-title">
        <span className="approval-badge">approval required</span>
        The agent wants to run{" "}
        {item.interrupts.length === 1
          ? "a destructive tool"
          : `${item.interrupts.length} destructive tools`}
      </div>
      <ul className="approval-calls">
        {item.interrupts.map((interrupt) => (
          <li key={interrupt.id}>
            <code className="approval-args">{interrupt.message}</code>
          </li>
        ))}
      </ul>
      {item.resolved === null ? (
        <div className="approval-actions">
          <button className="btn btn-approve" onClick={() => onDecide(true)}>
            Approve
          </button>
          <button className="btn btn-deny" onClick={() => onDecide(false)}>
            Deny
          </button>
        </div>
      ) : (
        <div className={`approval-verdict verdict-${item.resolved}`}>
          {item.resolved === "approved" && "Approved — tool executed"}
          {item.resolved === "denied" && "Denied — tool skipped"}
          {item.resolved === "remote" && "Resolved from another session"}
        </div>
      )}
    </div>
  );
}
