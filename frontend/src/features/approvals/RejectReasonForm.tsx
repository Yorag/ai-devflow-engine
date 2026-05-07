import { useState, type FormEvent } from "react";

type RejectReasonFormProps = {
  isBusy: boolean;
  errorMessage: string | null;
  onCancel: () => void;
  onSubmit: (reason: string) => Promise<void>;
};

export function RejectReasonForm({
  isBusy,
  errorMessage,
  onCancel,
  onSubmit,
}: RejectReasonFormProps): JSX.Element {
  const [value, setValue] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || isBusy) {
      return;
    }

    await onSubmit(trimmed);
  }

  return (
    <form
      className="approval-block__reject-form"
      aria-label="填写退回原因"
      onSubmit={handleSubmit}
    >
      <label className="approval-block__field" htmlFor="approval-reject-reason">
        <span>退回原因</span>
        <textarea
          id="approval-reject-reason"
          aria-label="退回原因"
          rows={4}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          disabled={isBusy}
        />
      </label>
      {errorMessage ? <p className="approval-block__error">{errorMessage}</p> : null}
      <div className="approval-block__reject-actions">
        <button
          type="submit"
          className="workspace-button"
          disabled={!value.trim() || isBusy}
        >
          {isBusy ? "正在提交退回原因" : "提交退回原因"}
        </button>
        <button
          type="button"
          className="workspace-button workspace-button--secondary"
          disabled={isBusy}
          onClick={onCancel}
        >
          取消
        </button>
      </div>
    </form>
  );
}
