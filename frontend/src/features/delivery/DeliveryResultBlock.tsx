import type { DeliveryResultFeedEntry, TopLevelFeedEntry } from "../../api/types";

export type DeliveryResultMetadata = {
  label: string;
  value: string;
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
  const metadata: DeliveryResultMetadata[] = [
    { label: "Mode", value: entry.delivery_mode },
  ];

  if (entry.test_summary) {
    metadata.push({ label: "Tests", value: entry.test_summary });
  }

  if (entry.result_ref) {
    metadata.push({ label: "Reference", value: entry.result_ref });
  }

  return {
    modeLabel: "Demo Delivery",
    title: entry.delivery_mode === "demo_delivery" ? "Demo delivery" : "Delivery result",
    summary: entry.summary,
    metadata,
  };
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
            <span>{item.value}</span>
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

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatTimestamp(value: string): string {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
