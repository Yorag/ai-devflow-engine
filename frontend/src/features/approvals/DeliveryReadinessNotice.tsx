import type { ApprovalRequestFeedEntry } from "../../api/types";

type DeliveryReadinessNoticeProps = {
  entry: ApprovalRequestFeedEntry;
  onOpenSettings?: () => void;
};

export function DeliveryReadinessNotice({
  entry,
  onOpenSettings,
}: DeliveryReadinessNoticeProps): JSX.Element | null {
  if (
    entry.approval_type !== "code_review_approval" ||
    !entry.delivery_readiness_status ||
    entry.delivery_readiness_status === "ready"
  ) {
    return null;
  }

  return (
    <section
      className="approval-block__readiness"
      aria-label="Delivery readiness blocking notice"
    >
      <p>{entry.delivery_readiness_message ?? "Delivery configuration is not ready."}</p>
      {entry.open_settings_action && onOpenSettings ? (
        <button
          type="button"
          className="workspace-button workspace-button--secondary workspace-button--compact"
          onClick={onOpenSettings}
          aria-label="Open settings"
        >
          Open settings
        </button>
      ) : null}
    </section>
  );
}
