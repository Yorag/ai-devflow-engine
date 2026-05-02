import type { SessionRead, SessionStatus } from "../../api/types";

type SessionListProps = {
  sessions: SessionRead[];
};

const activeSessionStatuses: SessionStatus[] = [
  "running",
  "paused",
  "waiting_clarification",
  "waiting_approval",
  "waiting_tool_confirmation",
];

const statusLabels: Record<SessionStatus, string> = {
  draft: "Draft",
  running: "Running",
  paused: "Paused",
  waiting_clarification: "Waiting clarification",
  waiting_approval: "Waiting approval",
  waiting_tool_confirmation: "Waiting tool confirmation",
  completed: "Completed",
  failed: "Failed",
  terminated: "Terminated",
};

export function SessionList({ sessions }: SessionListProps): JSX.Element {
  return (
    <section className="session-list" aria-label="Session list">
      <div className="session-list__header">
        <h2>Sessions</h2>
        <span>{sessions.length}</span>
      </div>
      <div className="session-list__items">
        {sessions.map((session) => (
          <article className="session-list-item" key={session.session_id}>
            <div className="session-list-item__body">
              <h3>{session.display_name}</h3>
              <p>{formatStatus(session.status)}</p>
            </div>
            <div className="session-list-item__actions">
              <button type="button" aria-label={`Rename ${session.display_name}`}>
                Rename
              </button>
              <button
                type="button"
                disabled
                aria-label={
                  isActiveSession(session.status)
                    ? `Delete ${session.display_name} blocked by active run`
                    : `Delete ${session.display_name} unavailable`
                }
              >
                Delete
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function isActiveSession(status: SessionStatus): boolean {
  return activeSessionStatuses.includes(status);
}

function formatStatus(status: SessionStatus): string {
  return statusLabels[status];
}
