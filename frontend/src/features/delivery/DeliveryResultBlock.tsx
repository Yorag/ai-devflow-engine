import type {
  DeliveryMode,
  DeliveryResultFeedEntry,
  TopLevelFeedEntry,
} from "../../api/types";
import { formatStatusLabel } from "../feed/display-labels";

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
      { label: "模式", value: entry.delivery_mode },
      ...formatDeliveryHighlights(entry),
    ],
  };
}

export function formatDeliveryHighlights(
  entry: DeliveryResultFeedEntry,
): DeliveryResultMetadata[] {
  const metadata: DeliveryResultMetadata[] = [];

  if (entry.delivery_mode === "demo_delivery" && entry.branch_name) {
    metadata.push({ label: "展示分支", value: entry.branch_name });
  }

  if (entry.delivery_mode === "git_auto_delivery" && entry.branch_name) {
    metadata.push({ label: "分支", value: entry.branch_name });
  }

  if (entry.delivery_mode === "git_auto_delivery" && entry.commit_sha) {
    metadata.push({ label: "提交", value: entry.commit_sha });
  }

  if (entry.delivery_mode === "git_auto_delivery" && entry.code_review_url) {
    metadata.push({
      label: "代码评审",
      value: formatCodeReviewRequestTarget(entry.code_review_url),
      href: entry.code_review_url,
    });
  }

  if (entry.test_summary) {
    metadata.push({ label: "测试", value: entry.test_summary });
  }

  if (entry.result_ref) {
    metadata.push({ label: "引用", value: entry.result_ref });
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
      <header className="feed-entry__header feed-entry__header--with-actions">
        <div className="feed-entry__header-main">
          <span>交付结果</span>
          <time dateTime={entry.occurred_at}>{formatTimestamp(entry.occurred_at)}</time>
          <strong>{formatStatusLabel(entry.status)}</strong>
        </div>
        {onOpenInspectorTarget ? (
          <button
            type="button"
            className="inspector-trigger inspector-trigger--quiet"
            onClick={() => onOpenInspectorTarget(entry)}
            aria-label={`查看${entry.delivery_mode}详情`}
          >
            查看详情
          </button>
        ) : null}
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
    </article>
  );
}

function formatDeliveryModeLabel(value: DeliveryMode): string {
  return value === "demo_delivery" ? "Demo Delivery" : "Git Auto Delivery";
}

function formatTimestamp(value: string): string {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
