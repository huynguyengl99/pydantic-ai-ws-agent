import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import Markdown from "react-markdown";
import { ApprovalCard } from "./components/ApprovalCard";
import { ConversationSidebar } from "./components/ConversationSidebar";
import { HelpModal } from "./components/HelpModal";
import { NotifyPopover } from "./components/NotifyPopover";
import { TaskPanel } from "./components/TaskPanel";
import { ToastStack } from "./components/ToastStack";
import { ToolCallCard } from "./components/ToolCallCard";
import { chatReducer, initialState } from "./lib/chat-state";
import {
  type Conversation,
  deleteConversation,
  fetchConversations,
} from "./lib/conversations";
import { useAgentSocket } from "./lib/ws-client";
import type { BaseEvent } from "@ag-ui/core";

const SERVER =
  (import.meta.env.VITE_SERVER_URL as string | undefined) ?? "localhost:8000";

function conversationId(): string {
  const existing = localStorage.getItem("tasklet-conversation");
  if (existing) return existing;
  const fresh = crypto.randomUUID();
  localStorage.setItem("tasklet-conversation", fresh);
  return fresh;
}

export default function App() {
  const [conversation, setConversation] = useState(conversationId);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [state, dispatch] = useReducer(chatReducer, initialState);
  const [draft, setDraft] = useState("");
  const [showHelp, setShowHelp] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const refreshConversations = useCallback(() => {
    fetchConversations(SERVER)
      .then(setConversations)
      .catch(() => {});
  }, []);

  const onEvent = useCallback(
    (event: BaseEvent) => {
      dispatch({ type: "event", event });
      // A finished run may have set the title or bumped updated_at.
      if (event.type === "RUN_FINISHED") refreshConversations();
    },
    [refreshConversations],
  );

  const { status, runAgent } = useAgentSocket(
    `ws://${SERVER}/ws/agent`,
    conversation,
    onEvent,
  );

  // Switching conversations reconnects (the url changes); reset local state.
  useEffect(() => {
    dispatch({ type: "reset" });
    refreshConversations();
  }, [conversation, refreshConversations]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [state.items, state.suggestions]);

  const pendingApproval = useMemo(
    () =>
      state.items.some(
        (item) => item.kind === "approval" && item.resolved === null,
      ),
    [state.items],
  );

  const sendText = (text: string) => {
    if (!text || status !== "open" || state.running || pendingApproval) return;
    // Only the new turn: the conversation itself lives on the server.
    runAgent({
      messages: [{ id: crypto.randomUUID(), role: "user", content: text }],
    });
    dispatch({ type: "sent_prompt", text });
    setDraft("");
  };

  const send = () => sendText(draft.trim());

  const decide = (id: string, interruptIds: string[], approved: boolean) => {
    // Resuming is another run: the interrupt id says which pause it answers,
    // and no messages are needed because the server kept the conversation.
    runAgent({
      resume: interruptIds.map((interruptId) => ({
        interruptId,
        status: "resolved",
        payload: approved
          ? { approved: true }
          : { approved: false, reason: "Denied from the web UI" },
      })),
    });
    dispatch({ type: "resolved_approval", id, approved });
  };

  const newConversation = () => {
    localStorage.removeItem("tasklet-conversation");
    setConversation(conversationId());
  };

  const selectConversation = (id: string) => {
    if (id === conversation || state.running) return;
    localStorage.setItem("tasklet-conversation", id);
    setConversation(id);
  };

  const handleDelete = (id: string) => {
    if (!window.confirm("Delete this conversation and its tasks?")) return;
    void deleteConversation(SERVER, id).then(() => {
      if (id === conversation) newConversation();
      else refreshConversations();
    });
  };

  return (
    <div className="shell">
      <ToastStack
        toasts={state.toasts}
        onDismiss={(id) => dispatch({ type: "dismiss_toast", id })}
      />
      <header className="topbar">
        <h1 className="wordmark">
          Tasklet<span className="wordmark-dot">.</span>
        </h1>
        <span className="tagline">pydantic-ai · AG-UI · chanx</span>
        <div className="topbar-right">
          <button className="btn btn-ghost" onClick={() => setShowHelp(true)}>
            Help
          </button>
          <span className={`conn conn-${status}`}>
            <span className="conn-dot" /> {status}
          </span>
        </div>
      </header>

      <main className="layout">
        <ConversationSidebar
          conversations={conversations}
          activeId={conversation}
          onSelect={selectConversation}
          onDelete={handleDelete}
          onNew={newConversation}
        />
        <section className="chat">
          <div className="messages" ref={scrollRef}>
            {state.items.length === 0 && (
              <div className="empty-hint">
                <p className="empty-title">
                  A task assistant with a paper trail.
                </p>
                <p>
                  Chat with the agent to manage the task list on the right.
                  Every tool call is shown live, and destructive ones pause for
                  your approval. Pick a starting point:
                </p>
                <div className="suggestions">
                  {[
                    "Add three tasks for launching my blog post",
                    "What's on my task list?",
                    "Add a task to review the PR, then mark it done",
                  ].map((text) => (
                    <button
                      key={text}
                      className="suggestion"
                      onClick={() => sendText(text)}
                    >
                      {text}
                    </button>
                  ))}
                </div>
                <p style={{ marginTop: 14 }}>
                  Then try <em>“delete the second task”</em> to see the approval
                  flow — or hit <strong>Help</strong> for the full tour.
                </p>
              </div>
            )}
            {state.items.map((item) => {
              switch (item.kind) {
                case "user":
                  return (
                    <div key={item.id} className="row row-user">
                      <div className="bubble bubble-user">{item.text}</div>
                    </div>
                  );
                case "assistant":
                  return (
                    <div key={item.id} className="row row-assistant">
                      <div
                        className={`bubble bubble-assistant ${item.streaming ? "streaming" : ""}`}
                      >
                        <Markdown>{item.text}</Markdown>
                      </div>
                    </div>
                  );
                case "tool":
                  return <ToolCallCard key={item.id} item={item} />;
                case "approval":
                  return (
                    <ApprovalCard
                      key={item.id}
                      item={item}
                      onDecide={(approved) =>
                        decide(
                          item.id,
                          item.interrupts.map((i) => i.id),
                          approved,
                        )
                      }
                    />
                  );
                case "error":
                  return (
                    <div key={item.id} className="error-card">
                      {item.detail}
                    </div>
                  );
              }
            })}
            {state.running && (
              <div className="thinking">
                <span />
                <span />
                <span />
              </div>
            )}
            {state.suggestions.length > 0 &&
              !state.running &&
              !pendingApproval && (
                <div className="suggestions followups">
                  {state.suggestions.map((text) => (
                    <button
                      key={text}
                      className="suggestion"
                      onClick={() => sendText(text)}
                    >
                      {text}
                    </button>
                  ))}
                </div>
              )}
          </div>

          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              send();
            }}
          >
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={
                pendingApproval
                  ? "Resolve the pending approval first…"
                  : "Ask Tasklet to manage your tasks…"
              }
              disabled={status !== "open"}
            />
            <NotifyPopover server={SERVER} conversation={conversation} />
            <button
              className="btn btn-send"
              type="submit"
              disabled={
                status !== "open" ||
                state.running ||
                pendingApproval ||
                !draft.trim()
              }
            >
              Send
            </button>
          </form>
        </section>

        <TaskPanel tasks={state.tasks} />
      </main>

      {showHelp && (
        <HelpModal
          server={SERVER}
          conversation={conversation}
          onClose={() => setShowHelp(false)}
        />
      )}
    </div>
  );
}
