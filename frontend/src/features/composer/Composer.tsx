import { useEffect, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { ApiRequestOptions } from "../../api/client";
import { apiQueryKeys } from "../../api/hooks";
import { appendSessionMessage } from "../../api/sessions";
import type {
  ComposerStateProjection,
  SessionRead,
  StageType,
} from "../../api/types";
import { getComposerHelperText } from "./composer-mode";
import { resolveComposerState } from "./composer-state";

type ComposerProps = {
  session: SessionRead | null;
  composerState: ComposerStateProjection | null;
  currentStageType: StageType | null;
  request?: ApiRequestOptions;
};

export function Composer({
  session,
  composerState,
  currentStageType,
  request,
}: ComposerProps): JSX.Element {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const [isSubmitting, setSubmitting] = useState(false);
  const resolved = resolveComposerState(composerState, currentStageType);
  const canSend = Boolean(session) && resolved.canSend;

  useEffect(() => {
    setValue("");
  }, [session?.session_id]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !canSend || !value.trim() || !resolved.messageType) {
      return;
    }

    setSubmitting(true);
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
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="composer" aria-label="Composer" onSubmit={handleSubmit}>
      <div className="composer__body">
        <label className="composer__field" htmlFor="workspace-composer-input">
          <span className="composer__label">当前输入</span>
          <textarea
            id="workspace-composer-input"
            aria-label="Composer input"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={!resolved.inputEnabled || isSubmitting}
            placeholder={
              resolved.mode === "waiting_clarification" ? "补充澄清信息" : "输入需求"
            }
            rows={3}
          />
        </label>
        <p className="composer__helper">
          {getComposerHelperText(composerState, currentStageType)}
        </p>
      </div>
      <div className="composer__actions">
        <span className="composer__binding">
          {composerState?.bound_run_id
            ? `绑定 run ${composerState.bound_run_id}`
            : "尚未绑定 run"}
        </span>
        <button
          type={resolved.lifecycle === "send" ? "submit" : "button"}
          className={`workspace-button${
            resolved.lifecycle === "send" ? "" : " workspace-button--secondary"
          }`}
          disabled={
            resolved.lifecycle !== "send" || !value.trim() || isSubmitting
          }
        >
          {isSubmitting ? "发送中" : resolved.actionLabel}
        </button>
      </div>
    </form>
  );
}
