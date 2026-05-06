import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import type { ApiRequestError, ApiRequestOptions } from "../../api/client";
import type { TopLevelFeedEntry } from "../../api/types";
import {
  getControlRecord,
  getDeliveryRecord,
  getStageInspector,
  getToolConfirmation,
} from "../../api/query";
import { InspectorSections, type InspectorDetail } from "./InspectorSections";
import { useWorkspaceStore } from "../workspace/workspace-store";
import type { InspectorTarget } from "./useInspector";

export type InspectorPanelProps = {
  isOpen: boolean;
  target: InspectorTarget | null;
  onClose: () => void;
  request?: ApiRequestOptions;
};

export function InspectorPanel({
  isOpen,
  target,
  onClose,
  request,
}: InspectorPanelProps): JSX.Element | null {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const liveEntryRefreshKey = useWorkspaceStore((state) =>
    getLiveEntryRefreshKey(state.narrativeFeed, target),
  );
  const detailQuery = useQuery<InspectorDetail, ApiRequestError>({
    queryKey: target
      ? [
          "inspector-detail",
          target.type,
          getTargetCacheKey(target),
          liveEntryRefreshKey ?? "no-live-entry",
        ]
      : ["inspector-detail", "closed"],
    queryFn: () => {
      if (!target) {
        throw new Error("Inspector target is required.");
      }

      switch (target.type) {
        case "stage":
          return getStageInspector(target.stageRunId, request);
        case "control_item":
          return getControlRecord(target.controlRecordId, request);
        case "tool_confirmation":
          return getToolConfirmation(target.toolConfirmationId, request);
        case "delivery_result":
          return getDeliveryRecord(target.deliveryRecordId, request);
      }
    },
    enabled: isOpen && target !== null,
    retry: false,
  });

  const shouldRenderInspector = isOpen && target !== null;

  useEffect(() => {
    if (isOpen && target) {
      const activeElement = document.activeElement;
      if (activeElement instanceof HTMLElement) {
        previousFocusRef.current = activeElement;
      }
      closeButtonRef.current?.focus();
      return;
    }

    previousFocusRef.current?.focus();
    previousFocusRef.current = null;
  }, [isOpen, target]);

  useEffect(() => {
    if (!isOpen || !target) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (isEscapeFromModalDialog(event)) {
        return;
      }

      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose, target]);

  if (!shouldRenderInspector) {
    return null;
  }

  return (
    <aside
      className="workspace-inspector workspace-inspector--open"
      aria-label="Inspector"
    >
      <header className="inspector-panel__header">
        <div>
          <p className="workspace-eyebrow">Inspector</p>
          <h2>{getInspectorHeading(target)}</h2>
        </div>
        <button
          ref={closeButtonRef}
          type="button"
          className="inspector-panel__close"
          onClick={onClose}
          aria-label="Close inspector"
        >
          Close
        </button>
      </header>

      <div className="inspector-panel__body">
        {detailQuery.isPending ? (
          <section className="inspector-panel__section" aria-label="Loading inspector">
            <h3>Loading</h3>
            <p>Loading inspector details...</p>
          </section>
        ) : null}
        {detailQuery.isError ? (
          <section
            className="inspector-panel__section inspector-panel__section--error"
            aria-label="Inspector error"
          >
            <h3>Inspector unavailable</h3>
            <p>{detailQuery.error.message}</p>
            {detailQuery.error.requestId ? (
              <p>Request ID: {detailQuery.error.requestId}</p>
            ) : null}
          </section>
        ) : null}
        {detailQuery.data ? <InspectorSections detail={detailQuery.data} /> : null}
      </div>
    </aside>
  );
}

export function getInspectorQueryLabel(target: InspectorTarget): string {
  switch (target.type) {
    case "stage":
      return `/api/stages/${target.stageRunId}/inspector`;
    case "control_item":
      return `/api/control-records/${target.controlRecordId}`;
    case "tool_confirmation":
      return `/api/tool-confirmations/${target.toolConfirmationId}`;
    case "delivery_result":
      return `/api/delivery-records/${target.deliveryRecordId}`;
  }
}

function getInspectorHeading(target: InspectorTarget): string {
  switch (target.type) {
    case "stage":
      return "Stage details";
    case "control_item":
      return "Control item details";
    case "tool_confirmation":
      return "Tool confirmation details";
    case "delivery_result":
      return "Delivery result details";
  }
}

function getTargetCacheKey(target: InspectorTarget): string {
  switch (target.type) {
    case "stage":
      return target.stageRunId;
    case "control_item":
      return target.controlRecordId;
    case "tool_confirmation":
      return target.toolConfirmationId;
    case "delivery_result":
      return target.deliveryRecordId;
  }
}

function getLiveEntryRefreshKey(
  entries: TopLevelFeedEntry[],
  target: InspectorTarget | null,
): string | null {
  if (!target) {
    return null;
  }

  if (target.type === "stage") {
    const sameRunEntries = entries.filter((entry) => entry.run_id === target.runId);
    if (sameRunEntries.length === 0) {
      return null;
    }

    return sameRunEntries
      .map((entry) => `${entry.entry_id}:${entry.occurred_at}`)
      .join("|");
  }

  const matchingEntry = entries.find((entry) => matchesInspectorTarget(entry, target));
  if (!matchingEntry) {
    return null;
  }

  return `${matchingEntry.entry_id}:${matchingEntry.occurred_at}`;
}

function matchesInspectorTarget(
  entry: TopLevelFeedEntry,
  target: InspectorTarget,
): boolean {
  switch (target.type) {
    case "stage":
      return entry.type === "stage_node" && entry.stage_run_id === target.stageRunId;
    case "control_item":
      return (
        entry.type === "control_item" &&
        entry.control_record_id === target.controlRecordId
      );
    case "tool_confirmation":
      return (
        entry.type === "tool_confirmation" &&
        entry.tool_confirmation_id === target.toolConfirmationId
      );
    case "delivery_result":
      return (
        entry.type === "delivery_result" &&
        entry.delivery_record_id === target.deliveryRecordId
      );
  }
}

function isEscapeFromModalDialog(event: KeyboardEvent): boolean {
  if (event.key !== "Escape") {
    return false;
  }

  const target = event.target;
  if (!(target instanceof Element)) {
    return false;
  }

  return Boolean(target.closest('[role="dialog"][aria-modal="true"]'));
}
