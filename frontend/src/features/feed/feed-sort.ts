import type { TopLevelFeedEntry } from "../../api/types";

const FEED_ENTRY_TYPE_PRIORITY: Record<TopLevelFeedEntry["type"], number> = {
  user_message: 0,
  stage_node: 1,
  control_item: 2,
  approval_request: 3,
  tool_confirmation: 4,
  approval_result: 5,
  delivery_result: 6,
  system_status: 7,
};

export function compareFeedEntries(
  left: TopLevelFeedEntry,
  right: TopLevelFeedEntry,
): number {
  const occurredAtComparison = left.occurred_at.localeCompare(right.occurred_at);
  if (occurredAtComparison !== 0) {
    return occurredAtComparison;
  }

  const typePriorityComparison =
    FEED_ENTRY_TYPE_PRIORITY[left.type] - FEED_ENTRY_TYPE_PRIORITY[right.type];
  if (typePriorityComparison !== 0) {
    return typePriorityComparison;
  }

  return left.entry_id.localeCompare(right.entry_id);
}

export function sortFeedEntries(
  entries: TopLevelFeedEntry[],
): TopLevelFeedEntry[] {
  return [...entries].sort(compareFeedEntries);
}
