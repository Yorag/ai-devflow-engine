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
      aria-label="Reject approval with reason"
      onSubmit={handleSubmit}
    >
      <label className="approval-block__field" htmlFor="approval-reject-reason">
        <span>Reject reason</span>
        <textarea
          id="approval-reject-reason"
          aria-label="Reject reason"
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
          {isBusy ? "Submitting rejection" : "Submit reject reason"}
        </button>
        <button
          type="button"
          className="workspace-button workspace-button--secondary"
          disabled={isBusy}
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
