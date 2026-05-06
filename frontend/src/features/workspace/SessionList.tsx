import { useState, type FormEvent } from "react";

import type { ApiRequestOptions } from "../../api/client";
import { renameSession } from "../../api/sessions";
import type { SessionRead, SessionStatus, StageType } from "../../api/types";

type SessionListProps = {
  sessions: SessionRead[];
  currentSessionId: string;
  onSessionChange: (sessionId: string) => void;
  onSessionRename?: (session: SessionRead) => void;
  request?: ApiRequestOptions;
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
  onSessionRename,
  request,
}: SessionListProps): JSX.Element {
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [savingSessionId, setSavingSessionId] = useState<string | null>(null);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [displayNameOverrides, setDisplayNameOverrides] = useState<
    Record<string, string>
  >({});

  function startRename(session: SessionRead) {
    const displayName =
      displayNameOverrides[session.session_id] ?? session.display_name;
    setEditingSessionId(session.session_id);
    setDraftName(displayName);
    setRenameError(null);
  }

  function cancelRename() {
    setEditingSessionId(null);
    setDraftName("");
    setRenameError(null);
  }

  async function handleRenameSubmit(
    event: FormEvent<HTMLFormElement>,
    session: SessionRead,
  ) {
    event.preventDefault();
    const nextName = draftName.trim();
    const displayName =
      displayNameOverrides[session.session_id] ?? session.display_name;
    if (!nextName || nextName === displayName || savingSessionId) {
      return;
    }

    setSavingSessionId(session.session_id);
    setRenameError(null);
    try {
      const renamedSession = await renameSession(
        session.session_id,
        { display_name: nextName },
        request,
      );
      setDisplayNameOverrides((current) => ({
        ...current,
        [session.session_id]: renamedSession.display_name,
      }));
      onSessionRename?.(renamedSession);
      cancelRename();
    } catch (error) {
      setRenameError(getRenameErrorMessage(error));
    } finally {
      setSavingSessionId(null);
    }
  }

  return (
    <section className="session-list" aria-label="Session list">
      <div className="session-list__header">
        <h2>Sessions</h2>
        <span>{sessions.length}</span>
      </div>
      <div className="session-list__items">
        {sessions.map((session) => {
          const isCurrent = session.session_id === currentSessionId;
          const isEditing = editingSessionId === session.session_id;
          const displayName =
            displayNameOverrides[session.session_id] ?? session.display_name;
          const trimmedDraftName = draftName.trim();
          const isSaveDisabled =
            !trimmedDraftName ||
            trimmedDraftName === displayName ||
            savingSessionId === session.session_id;

          return (
            <article
              className={`session-list-item${
                isCurrent ? " session-list-item--active" : ""
              }`}
              aria-label={`Session ${displayName}`}
              key={session.session_id}
            >
              <div className="session-list-item__body">
                <div className="session-list-item__title-row">
                  {isEditing ? (
                    <label className="session-list-item__rename">
                      <span className="sr-only">
                        Rename {displayName}
                      </span>
                      <input
                        className="session-list-item__rename-input"
                        type="text"
                        value={draftName}
                        onChange={(event) => setDraftName(event.target.value)}
                        aria-label={`Rename ${displayName}`}
                      />
                    </label>
                  ) : (
                    <button
                      className="session-list-item__open"
                      type="button"
                      onClick={() => onSessionChange(session.session_id)}
                      aria-current={isCurrent ? "page" : undefined}
                      aria-label={`Open ${displayName}`}
                    >
                      <span className="session-list-item__title session-list-item__name-text">
                        {displayName}
                      </span>
                    </button>
                  )}
                  <button
                    className="session-list-item__delete"
                    type="button"
                    disabled
                    aria-label={
                      isActiveSession(session.status)
                        ? `Delete ${displayName} blocked by active run`
                        : `Delete ${displayName} unavailable`
                    }
                  >
                    Delete
                  </button>
                </div>
                {isEditing ? (
                  <form
                    className="session-list-item__rename-actions"
                    onSubmit={(event) => handleRenameSubmit(event, session)}
                  >
                    <button
                      className="session-list-item__rename-save"
                      type="submit"
                      disabled={isSaveDisabled}
                      aria-label="Save session name"
                    >
                      {savingSessionId === session.session_id ? "Saving" : "Save"}
                    </button>
                    <button
                      className="session-list-item__rename-cancel"
                      type="button"
                      disabled={savingSessionId === session.session_id}
                      onClick={cancelRename}
                      aria-label="Cancel rename"
                    >
                      Cancel
                    </button>
                  </form>
                ) : (
                  <button
                    className="session-list-item__rename-trigger"
                    type="button"
                    onClick={() => startRename(session)}
                    aria-label={`Rename ${displayName}`}
                  >
                    Rename
                  </button>
                )}
                {isEditing && renameError ? (
                  <p className="session-list-item__rename-error" role="alert">
                    {renameError}
                  </p>
                ) : null}
                <p>{formatStatus(session.status)}</p>
                <p>Updated {formatTimestamp(session.updated_at)}</p>
                <p>Current stage {formatStage(session.latest_stage_type)}</p>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function getRenameErrorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Session name could not be saved.";
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
