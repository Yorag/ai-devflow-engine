import { useEffect, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { ApiRequestOptions } from "../../api/client";
import { apiQueryKeys } from "../../api/hooks";
import { pauseRun, resumeRun } from "../../api/runs";
import { appendSessionMessage } from "../../api/sessions";
import type {
  ComposerStateProjection,
  SessionRead,
  StageType,
} from "../../api/types";
import { getComposerHelperText } from "./composer-mode";
import { resolveComposerState } from "./composer-state";
import { RunControlButtons } from "./RunControlButtons";

type ComposerProps = {
  session: SessionRead | null;
  composerState: ComposerStateProjection | null;
  currentStageType: StageType | null;
  isBusy?: boolean;
  onBusyChange?: (busy: boolean) => void;
  request?: ApiRequestOptions;
  startBlockedReason?: string | null;
};

export function Composer({
  session,
  composerState,
  currentStageType,
  isBusy = false,
  onBusyChange,
  request,
  startBlockedReason = null,
}: ComposerProps): JSX.Element {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const [isSubmitting, setSubmitting] = useState(false);
  const [isNestedActionBusy, setNestedActionBusy] = useState(false);
  const resolved = resolveComposerState(composerState, currentStageType);
  const isSharedBusy = isBusy;
  const isActionBusy = isSubmitting || isSharedBusy || isNestedActionBusy;
  const isStartBlocked = Boolean(
    startBlockedReason && resolved.messageType === "new_requirement",
  );
  const canSend = Boolean(session) && resolved.canSend && !isStartBlocked;

  useEffect(() => {
    setValue("");
  }, [session?.session_id]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !session ||
      !canSend ||
      !value.trim() ||
      !resolved.messageType ||
      isActionBusy
    ) {
      return;
    }

    setSubmitting(true);
    onBusyChange?.(true);
    try {
      await appendSessionMessage(
        session.session_id,
        {
          message_type: resolved.messageType,
          content: value.trim(),
        },
        request,
      );
      setValue("");
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.sessionWorkspace(session.session_id),
        refetchType: "all",
      });
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.projectSessions(session.project_id),
        refetchType: "all",
      });
    } finally {
      setSubmitting(false);
      onBusyChange?.(false);
    }
  }

  async function handleLifecycleAction() {
    if (
      !session ||
      !composerState?.bound_run_id ||
      isActionBusy ||
      resolved.lifecycle === "send" ||
      resolved.lifecycle === "disabled"
    ) {
      return;
    }

    setSubmitting(true);
    onBusyChange?.(true);
    try {
      if (resolved.lifecycle === "pause") {
        await pauseRun(composerState.bound_run_id, request ?? {});
      } else {
        await resumeRun(composerState.bound_run_id, request ?? {});
      }
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.sessionWorkspace(session.session_id),
        refetchType: "all",
      });
      await queryClient.invalidateQueries({
        queryKey: apiQueryKeys.projectSessions(session.project_id),
        refetchType: "all",
      });
    } finally {
      setSubmitting(false);
      onBusyChange?.(false);
    }
  }

  const primaryButtonDisabled =
    resolved.lifecycle === "send"
      ? !value.trim() || isStartBlocked || isActionBusy
      : resolved.lifecycle === "disabled" ||
        !composerState?.bound_run_id ||
        isActionBusy;

  const primaryButtonLabel =
    isSubmitting && resolved.lifecycle === "send"
      ? "发送中"
      : isSubmitting && resolved.lifecycle === "pause"
        ? "暂停中"
        : isSubmitting && resolved.lifecycle === "resume"
          ? "恢复中"
          : resolved.actionLabel;

  return (
    <form className="composer" aria-label="Composer" onSubmit={handleSubmit}>
      <div className="composer__body">
        <label className="composer__field" htmlFor="workspace-composer-input">
          <span className="composer__label">当前输入</span>
          <textarea
            id="workspace-composer-input"
            aria-label="当前输入"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={!resolved.inputEnabled || isStartBlocked || isActionBusy}
            placeholder={
              resolved.mode === "waiting_clarification" ? "补充澄清信息" : "输入需求"
            }
            rows={3}
          />
        </label>
        <p className="composer__helper">
          {isStartBlocked
            ? startBlockedReason
            : getComposerHelperText(composerState, currentStageType)}
        </p>
      </div>
      <div className="composer__actions">
        <span className="composer__binding">
          {composerState?.bound_run_id
            ? `绑定 run ${composerState.bound_run_id}`
            : "尚未绑定 run"}
        </span>
        {session ? (
          <RunControlButtons
            projectId={session.project_id}
            sessionId={session.session_id}
            runId={composerState?.bound_run_id ?? null}
            lifecycle={resolved.lifecycle}
            secondaryActions={composerState?.secondary_actions ?? []}
            isBusy={isActionBusy}
            onBusyChange={(busy) => {
              setNestedActionBusy(busy);
              onBusyChange?.(busy);
            }}
            request={request}
          />
        ) : null}
        <div className="composer__primary-actions">
          <button
            type={resolved.lifecycle === "send" ? "submit" : "button"}
            className={`workspace-button${
              resolved.lifecycle === "send" ? "" : " workspace-button--secondary"
            }`}
            disabled={primaryButtonDisabled}
            onClick={
              resolved.lifecycle === "send" ? undefined : handleLifecycleAction
            }
            aria-busy={isSubmitting || (isSharedBusy && !isSubmitting)}
          >
            {primaryButtonLabel}
          </button>
        </div>
      </div>
    </form>
  );
}
