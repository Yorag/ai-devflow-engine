import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { ApiRequestError, ApiRequestOptions } from "../../api/client";
import { apiQueryKeys } from "../../api/hooks";
import { createRerun } from "../../api/runs";
import type { SystemStatusFeedEntry } from "../../api/types";
import { getRunBoundaryId } from "../feed/RunBoundary";

type RerunActionProps = {
  entry: SystemStatusFeedEntry;
  currentRunId?: string | null;
  sessionId?: string;
  projectId?: string;
  request?: ApiRequestOptions;
};

type RerunActionState = {
  canRender: boolean;
};

export function RerunAction({
  entry,
  currentRunId = null,
  sessionId = "",
  projectId = "",
  request,
}: RerunActionProps): JSX.Element | null {
  const state = resolveRerunActionState(entry, currentRunId);

  if (!state.canRender) {
    return null;
  }

  return (
    <RenderableRerunAction
      sessionId={sessionId}
      projectId={projectId}
      request={request}
    />
  );
}

function RenderableRerunAction({
  sessionId,
  projectId,
  request,
}: Pick<RerunActionProps, "sessionId" | "projectId" | "request">): JSX.Element {
  const queryClient = useQueryClient();
  const [isSubmitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function invalidateWorkspaceQueries() {
    await queryClient.invalidateQueries({
      queryKey: apiQueryKeys.sessionWorkspace(sessionId ?? ""),
      refetchType: "all",
    });
    if (projectId) {
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.projectSessions(projectId),
        refetchType: "all",
      });
    }
  }

  async function handleRerun() {
    if (!sessionId || isSubmitting) {
      return;
    }

    const confirmed = window.confirm(
      "A new run will start from Requirement Analysis and will not inherit undelivered workspace changes from the previous run. Continue?",
    );
    if (!confirmed) {
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    try {
      const run = await createRerun(sessionId, request ?? {});
      await invalidateWorkspaceQueries();
      focusRunBoundaryWhenAvailable(run.run_id);
    } catch (error) {
      setErrorMessage(readApiErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="rerun-action">
      <p className="rerun-action__notice">
        Retry starts a new run from Requirement Analysis. It will not inherit
        undelivered workspace changes from the previous run.
      </p>
      <div className="feed-entry__actions" aria-label="System status actions">
        <button
          type="button"
          className="workspace-button workspace-button--secondary workspace-button--compact"
          onClick={handleRerun}
          disabled={!sessionId || isSubmitting}
        >
          {isSubmitting ? "Starting rerun" : "Retry run"}
        </button>
      </div>
      {errorMessage ? <p className="rerun-action__error">{errorMessage}</p> : null}
    </div>
  );
}

export function resolveRerunActionState(
  entry: SystemStatusFeedEntry,
  currentRunId: string | null,
): RerunActionState {
  const isCurrentRun = Boolean(currentRunId) && entry.run_id === currentRunId;
  return {
    canRender:
      isCurrentRun &&
      entry.retry_action === "create_rerun" &&
      (entry.status === "failed" || entry.status === "terminated"),
  };
}

function focusRunBoundaryWhenAvailable(runId: string, remainingAttempts = 8) {
  const focusBoundary = () => {
    const boundary = document.getElementById(getRunBoundaryId(runId));
    if (!boundary) {
      return false;
    }

    boundary.focus({ preventScroll: true });
    boundary.scrollIntoView({ behavior: "smooth", block: "start" });
    return true;
  };

  if (focusBoundary()) {
    return;
  }

  if (remainingAttempts <= 0) {
    return;
  }

  window.setTimeout(() => {
    focusRunBoundaryWhenAvailable(runId, remainingAttempts - 1);
  }, 16);
}

function readApiErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as ApiRequestError).message);
  }
  return "Rerun request failed.";
}
