import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { ApiRequestOptions } from "../../api/client";
import { apiQueryKeys } from "../../api/hooks";
import { pauseRun } from "../../api/runs";
import type { ComposerStateProjection } from "../../api/types";
import type { ComposerLifecycleAction } from "./composer-state";

type RunControlButtonsProps = {
  projectId: string;
  sessionId: string;
  runId: string | null;
  lifecycle: ComposerLifecycleAction;
  secondaryActions: ComposerStateProjection["secondary_actions"];
  isBusy: boolean;
  onBusyChange?: (busy: boolean) => void;
  request?: ApiRequestOptions;
};

export function RunControlButtons({
  projectId,
  sessionId,
  runId,
  lifecycle,
  secondaryActions,
  isBusy,
  onBusyChange,
  request,
}: RunControlButtonsProps): JSX.Element | null {
  const queryClient = useQueryClient();
  const [isSubmitting, setSubmitting] = useState(false);
  const canPause = canPauseRun(lifecycle, secondaryActions, runId);

  if (!canPause) {
    return null;
  }

  async function handlePause() {
    if (!runId || isBusy || isSubmitting) {
      return;
    }

    setSubmitting(true);
    onBusyChange?.(true);
    try {
      await pauseRun(runId, request ?? {});
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
    <div className="composer__run-controls" aria-label="Current run controls">
      {canPause ? (
        <button
          type="button"
          className="workspace-button workspace-button--secondary"
          disabled={isBusy || isSubmitting}
          onClick={handlePause}
          aria-label="暂停当前运行"
        >
          {isSubmitting ? "暂停中" : "暂停"}
        </button>
      ) : null}
    </div>
  );
}

export function canPauseRun(
  lifecycle: ComposerLifecycleAction,
  secondaryActions: ComposerStateProjection["secondary_actions"],
  runId: string | null,
): boolean {
  if (!runId) {
    return false;
  }

  return lifecycle === "send" && secondaryActions.includes("pause");
}
