import type {
  DeliveryMode,
  DeliveryResultFeedEntry,
  TopLevelFeedEntry,
} from "../../api/types";

export type DeliveryResultMetadata = {
  label: string;
  value: string;
  href?: string;
};

export type DeliveryResultViewModel = {
  modeLabel: string;
  title: string;
  summary: string;
  metadata: DeliveryResultMetadata[];
};

export function buildDeliveryResultViewModel(
  entry: DeliveryResultFeedEntry,
): DeliveryResultViewModel {
  return {
    modeLabel: formatDeliveryModeLabel(entry.delivery_mode),
    title:
      entry.delivery_mode === "demo_delivery" ? "Demo delivery" : "Git auto delivery",
    summary: entry.summary,
    metadata: [
      { label: "Mode", value: entry.delivery_mode },
      ...formatDeliveryHighlights(entry),
    ],
  };
}

export function formatDeliveryHighlights(
  entry: DeliveryResultFeedEntry,
): DeliveryResultMetadata[] {
  const metadata: DeliveryResultMetadata[] = [];

  if (entry.delivery_mode === "git_auto_delivery" && entry.branch_name) {
    metadata.push({ label: "Branch", value: entry.branch_name });
  }

  if (entry.delivery_mode === "git_auto_delivery" && entry.commit_sha) {
    metadata.push({ label: "Commit", value: entry.commit_sha });
  }

  if (entry.delivery_mode === "git_auto_delivery" && entry.code_review_url) {
    metadata.push({
      label: "Code review",
      value: formatCodeReviewRequestTarget(entry.code_review_url),
      href: entry.code_review_url,
    });
  }

  if (entry.test_summary) {
    metadata.push({ label: "Tests", value: entry.test_summary });
  }

  if (entry.result_ref) {
    metadata.push({ label: "Reference", value: entry.result_ref });
  }

  return metadata;
}

export function formatCodeReviewRequestTarget(value: string): string {
  try {
    const url = new URL(value);
    return `${url.hostname}${url.pathname}`;
  } catch {
    return value;
  }
}

export function DeliveryResultBlock({
  entry,
  onOpenInspectorTarget,
}: {
  entry: DeliveryResultFeedEntry;
  onOpenInspectorTarget?: (entry: TopLevelFeedEntry) => void;
}): JSX.Element {
  const model = buildDeliveryResultViewModel(entry);

  return (
    <article
      className="feed-entry feed-entry--delivery-result delivery-result-block"
      aria-label="Delivery result feed entry"
    >
      <header className="feed-entry__header">
        <span>Delivery result</span>
        <time dateTime={entry.occurred_at}>{formatTimestamp(entry.occurred_at)}</time>
        <strong>{formatLabel(entry.status)}</strong>
      </header>
      <div className="feed-entry__title-row delivery-result-block__title-row">
        <h2>{model.title}</h2>
        <span className="delivery-result-block__mode-chip">{model.modeLabel}</span>
      </div>
      <p className="feed-entry__body">{model.summary}</p>
      <div className="feed-entry__meta-grid" aria-label="Delivery result metadata">
        {model.metadata.map((item) => (
          <span className="feed-entry__metadata" key={item.label}>
            <strong>{item.label}</strong>
            <span>
              {item.href ? (
                <a
                  href={item.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`${item.label} ${item.value}`}
                >
                  {item.value}
                </a>
              ) : (
                item.value
              )}
            </span>
          </span>
        ))}
      </div>
      {onOpenInspectorTarget ? (
        <div className="feed-entry__actions" aria-label="Delivery result actions">
          <button
            type="button"
            className="inspector-trigger"
            onClick={() => onOpenInspectorTarget(entry)}
            aria-label={`Open ${entry.delivery_mode} details`}
          >
            Details
          </button>
        </div>
      ) : null}
    </article>
  );
}

function formatDeliveryModeLabel(value: DeliveryMode): string {
  return value === "demo_delivery" ? "Demo Delivery" : "Git Auto Delivery";
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatTimestamp(value: string): string {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
