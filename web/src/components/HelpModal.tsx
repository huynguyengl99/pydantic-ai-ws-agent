interface Props {
  server: string;
  conversation: string;
  onClose: () => void;
}

export function HelpModal({ server, conversation, onClose }: Props) {
  return (
    <div className="help-backdrop" onClick={onClose}>
      <div className="help-modal" onClick={(event) => event.stopPropagation()}>
        <div className="help-head">
          <h2>What is this?</h2>
          <button
            className="help-close"
            onClick={onClose}
            aria-label="Close help"
          >
            ×
          </button>
        </div>
        <p>
          Tasklet is a demo of a <strong>Pydantic AI</strong> agent served over{" "}
          <strong>typed WebSockets</strong> (FastAPI + chanx). The agent manages
          the task list on the right; everything you see — streaming text, tool
          calls, approvals — is a typed message defined by the server&apos;s
          AsyncAPI contract.
        </p>

        <h3>Try this flow</h3>
        <ol>
          <li>
            <strong>“Add three tasks for launching my blog post”</strong> —
            watch the tool cards run and the task panel update live
          </li>
          <li>
            <strong>“Mark the first one as done”</strong>
          </li>
          <li>
            <strong>“Delete the second task”</strong> — destructive tools pause
            the run and ask for your approval before executing
          </li>
          <li>
            Open this page in a <strong>second tab</strong> — both tabs stream
            the same conversation, and either one can approve
          </li>
          <li>
            Refresh mid-answer — the run keeps going and the transcript is
            replayed
          </li>
          <li>
            <strong>“Remind me in 15 seconds to stretch”</strong> — the agent
            schedules a background job that pushes a notification back into the
            conversation when it fires
          </li>
        </ol>

        <h3>Push a notification from outside</h3>
        <p>
          Click <strong>Notify</strong> next to the composer, or use any HTTP
          client — both hit the same endpoint and broadcast to every connected
          tab:
        </p>
        <pre>
          <code>
            {`curl -X POST http://${server}/conversations/${conversation}/notify \\
  -H 'Content-Type: application/json' \\
  -d '{"title":"Reminder","body":"Stand-up in 5 minutes"}'`}
          </code>
        </pre>

        <div className="help-links">
          <a
            href={`http://${server}/asyncapi`}
            target="_blank"
            rel="noreferrer"
          >
            AsyncAPI docs
          </a>
          <a
            href="https://github.com/huynguyengl99/pydantic-ai-ws-agent"
            target="_blank"
            rel="noreferrer"
          >
            Source + guide
          </a>
          <a
            href="https://pydantic.dev/docs/ai/"
            target="_blank"
            rel="noreferrer"
          >
            Pydantic AI
          </a>
          <a
            href="https://github.com/huynguyengl99/chanx"
            target="_blank"
            rel="noreferrer"
          >
            chanx
          </a>
        </div>
      </div>
    </div>
  );
}
