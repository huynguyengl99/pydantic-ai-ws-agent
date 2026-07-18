import type { Conversation } from "../lib/conversations";

export function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onDelete,
  onNew,
}: {
  conversations: Conversation[];
  activeId: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onNew: () => void;
}) {
  const hasActive = conversations.some((conv) => conv.id === activeId);
  return (
    <aside className="conv-panel">
      <button className="btn btn-new-chat" onClick={onNew}>
        + New chat
      </button>
      <ul className="conv-items">
        {!hasActive && (
          <li className="conv-item conv-active">
            <span className="conv-title">New conversation</span>
          </li>
        )}
        {conversations.map((conv) => (
          <li
            key={conv.id}
            className={`conv-item ${conv.id === activeId ? "conv-active" : ""}`}
            onClick={() => onSelect(conv.id)}
          >
            <span className="conv-title">{conv.title || "Untitled"}</span>
            <button
              className="conv-delete"
              title="Delete conversation"
              aria-label={`Delete conversation ${conv.title || conv.id}`}
              onClick={(event) => {
                event.stopPropagation();
                onDelete(conv.id);
              }}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <p className="conv-note">
        Conversations and their task lists live on the server — switch or
        refresh freely.
      </p>
    </aside>
  );
}
