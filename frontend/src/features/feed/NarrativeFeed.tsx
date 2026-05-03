import type { RunSummaryProjection, TopLevelFeedEntry } from "../../api/types";
import { renderFeedEntryByType } from "./FeedEntryRenderer";
import { groupEntriesByRun, RunBoundary } from "./RunBoundary";
import { RunSwitcher } from "./RunSwitcher";

export type NarrativeFeedProps = {
  entries: TopLevelFeedEntry[];
  runs?: RunSummaryProjection[];
  currentRunId?: string | null;
  onOpenInspectorTarget?: (entry: TopLevelFeedEntry) => void;
};

export function NarrativeFeed({
  entries,
  runs = [],
  currentRunId = null,
  onOpenInspectorTarget,
}: NarrativeFeedProps): JSX.Element {
  const groups = runs.length > 0 ? groupEntriesByRun(entries, runs) : [];

  if (groups.length > 0) {
    return (
      <>
        <RunSwitcher groups={groups} currentRunId={currentRunId} />
        <div className="narrative-feed__run-groups" aria-label="Narrative Feed run groups">
          {groups.map((group) => (
            <RunBoundary group={group} key={group.runId}>
              <ol
                className="narrative-feed__entries"
                aria-label={
                  group.run
                    ? `Run ${group.run.attempt_index} entries`
                    : `Entries for ${group.runId}`
                }
              >
                {group.entries.map((entry) => (
                  <li className="narrative-feed__item" key={entry.entry_id}>
                    {renderFeedEntryByType(entry, { onOpenInspectorTarget })}
                  </li>
                ))}
              </ol>
            </RunBoundary>
          ))}
        </div>
      </>
    );
  }

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
          {renderFeedEntryByType(entry, { onOpenInspectorTarget })}
        </li>
      ))}
    </ol>
  );
}
