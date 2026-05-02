import type { TopLevelFeedEntry } from "../../api/types";
import { renderFeedEntryByType } from "./FeedEntryRenderer";

export type NarrativeFeedProps = {
  entries: TopLevelFeedEntry[];
};

export function NarrativeFeed({ entries }: NarrativeFeedProps): JSX.Element {
  if (entries.length === 0) {
    return (
      <section
        className="narrative-feed__empty"
        aria-label="Narrative Feed empty state"
      >
        <p className="workspace-eyebrow">Narrative Feed</p>
        <h2>No run entries yet</h2>
      </section>
    );
  }

  return (
    <ol className="narrative-feed__entries" aria-label="Narrative Feed entries">
      {entries.map((entry) => (
        <li className="narrative-feed__item" key={entry.entry_id}>
          {renderFeedEntryByType(entry)}
        </li>
      ))}
    </ol>
  );
}
