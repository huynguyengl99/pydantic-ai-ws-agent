import { useState } from "react";

interface Props {
  server: string;
  conversation: string;
}

export function NotifyPopover({ server, conversation }: Props) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("Reminder");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);

  const push = async () => {
    if (!body.trim() || sending) return;
    setSending(true);
    try {
      await fetch(`http://${server}/conversations/${conversation}/notify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim() || "Notification",
          body: body.trim(),
        }),
      });
      setBody("");
      setOpen(false);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="notify-wrap">
      {open && (
        <div className="notify-popover">
          <span className="notify-caption">
            Broadcast to every tab in this conversation via{" "}
            <code>POST /notify</code>
          </span>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Title"
            aria-label="Notification title"
          />
          <input
            value={body}
            onChange={(event) => setBody(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && push()}
            placeholder="Body"
            aria-label="Notification body"
            autoFocus
          />
          <div className="notify-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-send"
              onClick={push}
              disabled={!body.trim() || sending}
            >
              Push
            </button>
          </div>
        </div>
      )}
      <button
        type="button"
        className="btn btn-ghost"
        onClick={() => setOpen((value) => !value)}
        title="Push a notification to this conversation over HTTP"
      >
        Notify
      </button>
    </div>
  );
}
