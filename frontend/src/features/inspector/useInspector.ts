import { useCallback } from "react";

import type { TopLevelFeedEntry } from "../../api/types";
import {
  useWorkspaceStore,
  type WorkspaceInspectorTarget,
} from "../workspace/workspace-store";

export type InspectorTarget = WorkspaceInspectorTarget;
export type InspectorOpenableEntry = Extract<
  TopLevelFeedEntry,
  { type: "stage_node" | "tool_confirmation" | "control_item" | "delivery_result" }
>;

export function openInspectorTarget(entry: TopLevelFeedEntry): InspectorTarget | null {
  switch (entry.type) {
    case "stage_node":
      return {
        type: "stage",
        runId: entry.run_id,
        stageRunId: entry.stage_run_id,
      };
    case "tool_confirmation":
      return {
        type: "tool_confirmation",
        runId: entry.run_id,
        toolConfirmationId: entry.tool_confirmation_id,
      };
    case "control_item":
      return {
        type: "control_item",
        runId: entry.run_id,
        controlRecordId: entry.control_record_id,
      };
    case "delivery_result":
      return {
        type: "delivery_result",
        runId: entry.run_id,
        deliveryRecordId: entry.delivery_record_id,
      };
    case "approval_request":
    case "approval_result":
    case "system_status":
    case "user_message":
      return null;
  }
}

export function closeInspector(): void {
  useWorkspaceStore.getState().closeInspector();
}

export function useInspector(): {
  isOpen: boolean;
  target: InspectorTarget | null;
  openEntry: (entry: TopLevelFeedEntry) => InspectorTarget | null;
  close: () => void;
} {
  const isOpen = useWorkspaceStore((state) => state.inspector.isOpen);
  const target = useWorkspaceStore((state) => state.inspector.target);
  const openInspector = useWorkspaceStore((state) => state.openInspector);
  const close = useWorkspaceStore((state) => state.closeInspector);

  const openEntry = useCallback(
    (entry: TopLevelFeedEntry): InspectorTarget | null => {
      const nextTarget = openInspectorTarget(entry);
      if (nextTarget) {
        openInspector(nextTarget);
      }
      return nextTarget;
    },
    [openInspector],
  );

  return {
    isOpen,
    target,
    openEntry,
    close,
  };
}
