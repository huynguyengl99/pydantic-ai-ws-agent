import type { TaskItem } from "../lib/chat-state";

export function TaskPanel({ tasks }: { tasks: TaskItem[] }) {
  const open = tasks.filter((t) => !t.done).length;
  return (
    <aside className="task-panel">
      <div className="task-panel-head">
        <h2>Task list</h2>
        <span className="task-count">
          {open} open · {tasks.length} total
        </span>
      </div>
      {tasks.length === 0 ? (
        <p className="task-empty">Nothing yet. Ask the agent to add a task.</p>
      ) : (
        <ul className="task-items">
          {tasks.map((task) => (
            <li key={task.id} className={task.done ? "task-done" : ""}>
              <span className="task-tick" aria-hidden>
                {task.done ? "✓" : ""}
              </span>
              <span className="task-title">{task.title}</span>
              <span className="task-id">#{task.id}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="task-note">
        Live from AG-UI <code>STATE_SNAPSHOT</code> — sent on connect and again
        with every run.
      </p>
    </aside>
  );
}
