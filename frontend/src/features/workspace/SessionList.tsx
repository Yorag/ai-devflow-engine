import type { SessionRead, SessionStatus, StageType } from "../../api/types";

type SessionListProps = {
  sessions: SessionRead[];
  currentSessionId: string;
  onSessionChange: (sessionId: string) => void;
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

const stageLabels: Record<StageType, string> = {
  requirement_analysis: "Requirement Analysis",
  solution_design: "Solution Design",
  code_generation: "Code Generation",
  test_generation_execution: "Test Generation & Execution",
  code_review: "Code Review",
  delivery_integration: "Delivery Integration",
};

export function SessionList({
  sessions,
  currentSessionId,
  onSessionChange,
}: SessionListProps): JSX.Element {
  return (
    <section className="session-list" aria-label="Session list">
      <div className="session-list__header">
        <h2>Sessions</h2>
        <span>{sessions.length}</span>
      </div>
      <div className="session-list__items">
        {sessions.map((session) => {
          const isCurrent = session.session_id === currentSessionId;

          return (
            <article
              className={`session-list-item${
                isCurrent ? " session-list-item--active" : ""
              }`}
              key={session.session_id}
            >
              <div className="session-list-item__body">
                <button
                  className="session-list-item__open"
                  type="button"
                  onClick={() => onSessionChange(session.session_id)}
                  aria-current={isCurrent ? "page" : undefined}
                  aria-label={`Open ${session.display_name}`}
                >
                  <span>{session.display_name}</span>
                </button>
                <p>{formatStatus(session.status)}</p>
                <p>Updated {formatTimestamp(session.updated_at)}</p>
                <p>Current stage {formatStage(session.latest_stage_type)}</p>
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
          );
        })}
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

function formatStage(stageType: StageType | null): string {
  return stageType ? stageLabels[stageType] : "Not started";
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(
    date.getUTCDate(),
  )} ${pad2(date.getUTCHours())}:${pad2(date.getUTCMinutes())}`;
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}
