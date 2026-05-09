from __future__ import annotations

from backend.app.schemas.feed import TopLevelFeedEntry


_FEED_ENTRY_TYPE_PRIORITY: dict[str, int] = {
    "user_message": 0,
    "stage_node": 1,
    "control_item": 2,
    "approval_request": 3,
    "tool_confirmation": 4,
    "approval_result": 5,
    "delivery_result": 6,
    "system_status": 7,
}


def feed_entry_sort_key(entry: TopLevelFeedEntry) -> tuple[object, int, str]:
    return (
        entry.occurred_at,
        _FEED_ENTRY_TYPE_PRIORITY.get(entry.type.value, 99),
        entry.entry_id,
    )


__all__ = ["feed_entry_sort_key"]
