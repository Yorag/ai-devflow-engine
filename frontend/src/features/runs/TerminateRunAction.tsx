import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { ApiRequestOptions } from "../../api/client";
import { apiQueryKeys } from "../../api/hooks";
import { terminateRun } from "../../api/runs";
import type { ComposerStateProjection, SessionStatus } from "../../api/types";

type TerminateRunActionProps = {
  projectId: string;
  sessionId: string;
  runId: string | null;
  sessionStatus: SessionStatus;
  secondaryActions: ComposerStateProjection["secondary_actions"];
  isBusy?: boolean;
  onBusyChange?: (busy: boolean) => void;
  request?: ApiRequestOptions;
};

export function TerminateRunAction({
  projectId,
  sessionId,
  runId,
  sessionStatus,
  secondaryActions,
  isBusy = false,
  onBusyChange,
  request,
}: TerminateRunActionProps): JSX.Element | null {
  const queryClient = useQueryClient();
  const [isSubmitting, setSubmitting] = useState(false);
  const isActionBusy = isSubmitting || isBusy;

  if (!canTerminateRun(runId, sessionStatus, secondaryActions)) {
    return null;
  }

  async function handleTerminate() {
    if (!runId || isActionBusy) {
      return;
    }

    const confirmed = window.confirm("终止当前运行后将保留历史记录。继续吗？");
    if (!confirmed) {
      return;
    }

    setSubmitting(true);
    onBusyChange?.(true);
    try {
      await terminateRun(runId, request ?? {});
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.sessionWorkspace(sessionId),
        refetchType: "all",
      });
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.projectSessions(projectId),
        refetchType: "all",
      });
    } finally {
      setSubmitting(false);
      onBusyChange?.(false);
    }
  }

  return (
    <button
      type="button"
      className="workspace-button workspace-button--danger workspace-button--compact"
      onClick={handleTerminate}
      disabled={isActionBusy}
      aria-label="终止当前运行"
    >
      {isSubmitting ? "终止中" : "终止"}
    </button>
  );
}

export function canTerminateRun(
  runId: string | null,
  sessionStatus: SessionStatus,
  secondaryActions: ComposerStateProjection["secondary_actions"],
): boolean {
  if (!runId) {
    return false;
  }

  return (
    secondaryActions.includes("terminate") &&
    !["draft", "completed", "failed", "terminated"].includes(sessionStatus)
  );
}
