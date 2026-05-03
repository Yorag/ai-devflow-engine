import { useEffect, useRef } from "react";

import type { InspectorTarget } from "./useInspector";

export type InspectorPanelProps = {
  isOpen: boolean;
  target: InspectorTarget | null;
  onClose: () => void;
};

export function InspectorPanel({
  isOpen,
  target,
  onClose,
}: InspectorPanelProps): JSX.Element {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

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
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose, target]);

  if (!isOpen || !target) {
    return (
      <aside
        className="workspace-inspector workspace-inspector--closed"
        aria-label="Inspector"
      >
        <p>Inspector closed</p>
      </aside>
    );
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
        <section className="inspector-panel__section" aria-label="Selected target">
          <h3>Selected target</h3>
          <InspectorDatum label="Run" value={target.runId} />
          {renderTargetIdentifier(target)}
        </section>
        <section className="inspector-panel__section" aria-label="Future query source">
          <h3>Future query source</h3>
          <InspectorDatum label="Endpoint" value={getInspectorQueryLabel(target)} />
        </section>
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

function renderTargetIdentifier(target: InspectorTarget): JSX.Element {
  switch (target.type) {
    case "stage":
      return <InspectorDatum label="Stage run" value={target.stageRunId} />;
    case "control_item":
      return <InspectorDatum label="Control record" value={target.controlRecordId} />;
    case "tool_confirmation":
      return (
        <InspectorDatum
          label="Tool confirmation"
          value={target.toolConfirmationId}
        />
      );
    case "delivery_result":
      return <InspectorDatum label="Delivery record" value={target.deliveryRecordId} />;
  }
}

function InspectorDatum({
  label,
  value,
}: {
  label: string;
  value: string;
}): JSX.Element {
  return (
    <span className="inspector-panel__datum">
      <strong>{label}</strong>
      <span>{value}</span>
    </span>
  );
}
