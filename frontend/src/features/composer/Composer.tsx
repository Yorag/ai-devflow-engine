import { useEffect, useRef, useState, type FormEvent } from "react";
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
import { ErrorState } from "../errors/ErrorState";
import { resolveComposerState } from "./composer-state";

type ComposerProps = {
  session: SessionRead | null;
  composerState: ComposerStateProjection | null;
  currentStageType: StageType | null;
  isBusy?: boolean;
  onBusyChange?: (busy: boolean) => void;
  request?: ApiRequestOptions;
};

export function Composer({
  session,
  composerState,
  currentStageType,
  isBusy = false,
  onBusyChange,
  request,
}: ComposerProps): JSX.Element {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const [submitError, setSubmitError] = useState<unknown | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);
  const resolved = resolveComposerState(composerState, currentStageType);
  const isSharedBusy = isBusy;
  const isActionBusy = isSubmitting || isSharedBusy;
  const canSend = Boolean(session) && resolved.canSend;

  useEffect(() => {
    setValue("");
    setSubmitError(null);
  }, [session?.session_id]);

  useEffect(() => {
    resizeTextarea(inputRef.current);
  }, [value]);

  function resizeTextarea(textarea: HTMLTextAreaElement | null) {
    if (!textarea) {
      return;
    }

    textarea.style.height = "auto";
    if (textarea.value) {
      textarea.style.height = `${textarea.scrollHeight}px`;
    }
  }

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
    setSubmitError(null);
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
    } catch (error) {
      setSubmitError(error);
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
      ? !value.trim() || isActionBusy
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
    <form
      className="composer composer--compact"
      aria-label="Composer"
      onSubmit={handleSubmit}
    >
      <div className="composer__body">
        <label className="composer__field" htmlFor="workspace-composer-input">
          <span className="composer__label sr-only">当前输入</span>
          <textarea
            ref={inputRef}
            id="workspace-composer-input"
            aria-label="当前输入"
            value={value}
            onChange={(event) => {
              resizeTextarea(event.currentTarget);
              setValue(event.target.value);
            }}
            disabled={!resolved.inputEnabled || isActionBusy}
            placeholder={
              resolved.mode === "waiting_clarification" ? "补充澄清信息" : "输入需求"
            }
            rows={1}
          />
        </label>
        {submitError ? <ErrorState error={submitError} /> : null}
      </div>
      <div className="composer__actions">
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
