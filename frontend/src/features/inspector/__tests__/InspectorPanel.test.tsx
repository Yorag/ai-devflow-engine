import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import type { ApiRequestOptions } from "../../../api/client";
import type {
  ControlItemFeedEntry,
  DeliveryResultFeedEntry,
  ExecutionNodeProjection,
  ToolConfirmationFeedEntry,
  TopLevelFeedEntry,
} from "../../../api/types";
import { renderWithAppProviders } from "../../../app/test-utils";
import { mockFeedEntriesByType } from "../../../mocks/fixtures";
import { mockApiRequestOptions } from "../../../mocks/handlers";
import { ConsolePage } from "../../../pages/ConsolePage";
import { FeedEntryRenderer } from "../../feed/FeedEntryRenderer";
import { NarrativeFeed } from "../../feed/NarrativeFeed";
import { useWorkspaceStore } from "../../workspace/workspace-store";
import { InspectorPanel, getInspectorQueryLabel } from "../InspectorPanel";
import { openInspectorTarget, useInspector } from "../useInspector";

afterEach(() => {
  cleanup();
  useWorkspaceStore.getState().resetWorkspace();
});

function InspectorHarness({
  entries,
  request = mockApiRequestOptions,
}: {
  entries: TopLevelFeedEntry[];
  request?: ApiRequestOptions;
}): JSX.Element {
  const inspector = useInspector();

  return (
    <section
      className={
        inspector.isOpen
          ? "workspace-shell workspace-shell--inspector-open"
          : "workspace-shell"
      }
    >
      <main className="workspace-main">
        <NarrativeFeed entries={entries} onOpenInspectorTarget={inspector.openEntry} />
      </main>
      <InspectorPanel
        isOpen={inspector.isOpen}
        target={inspector.target}
        onClose={inspector.close}
        request={request}
      />
    </section>
  );
}

describe("Inspector target mapping", () => {
  it("maps only supported top-level entries to Inspector query targets", () => {
    expect(openInspectorTarget(mockFeedEntriesByType.stage_node)).toEqual({
      type: "stage",
      runId: "run-running",
      stageRunId: "stage-solution-design-running",
    });
    expect(openInspectorTarget(mockFeedEntriesByType.control_item)).toEqual({
      type: "control_item",
      runId: "run-waiting-clarification",
      controlRecordId: "control-clarification",
    });
    expect(openInspectorTarget(mockFeedEntriesByType.tool_confirmation)).toEqual({
      type: "tool_confirmation",
      runId: "run-running",
      toolConfirmationId: "tool-confirmation-1",
    });
    expect(openInspectorTarget(mockFeedEntriesByType.delivery_result)).toEqual({
      type: "delivery_result",
      runId: "run-completed",
      deliveryRecordId: "delivery-record-1",
    });

    expect(openInspectorTarget(mockFeedEntriesByType.approval_result)).toBeNull();
    expect(openInspectorTarget(mockFeedEntriesByType.approval_request)).toBeNull();
    expect(openInspectorTarget(mockFeedEntriesByType.user_message)).toBeNull();
    expect(openInspectorTarget(mockFeedEntriesByType.system_status)).toBeNull();
  });

  it("exposes query labels for the supported detail endpoints", () => {
    expect(
      getInspectorQueryLabel({
        type: "stage",
        runId: "run-1",
        stageRunId: "stage-1",
      }),
    ).toBe("/api/stages/stage-1/inspector");
    expect(
      getInspectorQueryLabel({
        type: "control_item",
        runId: "run-1",
        controlRecordId: "control-1",
      }),
    ).toBe("/api/control-records/control-1");
    expect(
      getInspectorQueryLabel({
        type: "tool_confirmation",
        runId: "run-1",
        toolConfirmationId: "tool-1",
      }),
    ).toBe("/api/tool-confirmations/tool-1");
    expect(
      getInspectorQueryLabel({
        type: "delivery_result",
        runId: "run-1",
        deliveryRecordId: "delivery-1",
      }),
    ).toBe("/api/delivery-records/delivery-1");
  });
});

describe("InspectorPanel", () => {
  it("renders closed by default without a selected target", () => {
    renderWithAppProviders(
      <InspectorPanel
        isOpen={false}
        target={null}
        onClose={() => undefined}
        request={mockApiRequestOptions}
      />,
    );

    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(within(inspector).getByText("Inspector closed")).toBeTruthy();
    expect(
      within(inspector).queryByRole("button", { name: "Close inspector" }),
    ).toBeNull();
  });

  it("renders a selected stage target and closes with Escape", async () => {
    const target = {
      type: "stage",
      runId: "run-running",
      stageRunId: "stage-solution-design-running",
    } as const;
    renderWithAppProviders(<ControlledInspectorPanel target={target} />);

    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(within(inspector).getByRole("heading", { name: "Stage details" })).toBeTruthy();
    expect(await within(inspector).findByText("stage-solution-design-running")).toBeTruthy();
    expect(within(inspector).getByText("run-running")).toBeTruthy();
    expect(within(inspector).queryByRole("button", { name: /approve/i })).toBeNull();
    expect(
      within(inspector).queryByRole("button", { name: /allow this execution/i }),
    ).toBeNull();

    fireEvent.keyDown(inspector, { key: "Escape" });

    expect(screen.getByText("Inspector closed")).toBeTruthy();
  });
});

describe("Feed Inspector opening", () => {
  it("opens stage, control item, tool confirmation, and delivery result details", async () => {
    const entries: TopLevelFeedEntry[] = [
      mockFeedEntriesByType.stage_node,
      mockFeedEntriesByType.control_item,
      mockFeedEntriesByType.tool_confirmation,
      mockFeedEntriesByType.delivery_result,
    ];

    renderWithAppProviders(
      <InspectorHarness entries={entries} request={mockApiRequestOptions} />,
    );

    expect(screen.getByText("Inspector closed")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open Solution Design details" }));
    expect(screen.getByRole("heading", { name: "Stage details" })).toBeTruthy();
    expect(await screen.findByText("stage-solution-design-running")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open Clarification needed details" }));
    expect(screen.getByRole("heading", { name: "Control item details" })).toBeTruthy();
    expect(await screen.findByText("control-clarification")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open Allow dependency install details" }));
    expect(screen.getByRole("heading", { name: "Tool confirmation details" })).toBeTruthy();
    expect(await screen.findByText("tool-confirmation-1")).toBeTruthy();
    const toolEntry = screen.getByRole("article", {
      name: "Tool confirmation feed entry",
    });
    expect(within(toolEntry).getByRole("button", { name: "Allow this execution" })).toBeTruthy();
    expect(within(toolEntry).getByRole("button", { name: "Deny this execution" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open demo_delivery details" }));
    expect(screen.getByRole("heading", { name: "Delivery result details" })).toBeTruthy();
    expect(await screen.findByText("delivery-record-1")).toBeTruthy();
  });

  it("does not expose approval_result as an independent Inspector target", () => {
    renderWithAppProviders(
      <InspectorHarness
        entries={[
          mockFeedEntriesByType.approval_request,
          mockFeedEntriesByType.approval_result,
        ]}
      />,
    );

    expect(screen.queryByRole("button", { name: /open approved details/i })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /open review solution design details/i }),
    ).toBeNull();
    expect(screen.getByText("Inspector closed")).toBeTruthy();
  });

  it("closes the Inspector with the close button", () => {
    renderWithAppProviders(
      <InspectorHarness
        entries={[mockFeedEntriesByType.stage_node]}
        request={mockApiRequestOptions}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open Solution Design details" }));
    expect(screen.getByRole("heading", { name: "Stage details" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Close inspector" }));

    expect(screen.getByText("Inspector closed")).toBeTruthy();
  });

  it("closes the Inspector with Escape after focus leaves the panel", () => {
    renderWithAppProviders(
      <>
        <button type="button">Outside action</button>
        <InspectorHarness
          entries={[mockFeedEntriesByType.stage_node]}
          request={mockApiRequestOptions}
        />
      </>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open Solution Design details" }));
    expect(screen.getByRole("heading", { name: "Stage details" })).toBeTruthy();

    screen.getByRole("button", { name: "Outside action" }).focus();
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.getByText("Inspector closed")).toBeTruthy();
  });

  it("mounts the Inspector shell from the selected workspace projection", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Solution Design details" }),
    );

    expect(await screen.findByRole("heading", { name: "Stage details" })).toBeTruthy();
    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(await within(inspector).findByText("stage-solution-design-running")).toBeTruthy();
    expect(within(inspector).getByText("run-running")).toBeTruthy();
  });

  it("closes and clears the Inspector target when the selected session changes", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Solution Design details" }),
    );

    expect(await screen.findByRole("heading", { name: "Stage details" })).toBeTruthy();
    expect(await screen.findByText("stage-solution-design-running")).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Open Clarify provider behavior" }),
    );

    expect(await screen.findByText("Clarification needed")).toBeTruthy();
    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(within(inspector).getByText("Inspector closed")).toBeTruthy();
    expect(within(inspector).queryByText("stage-solution-design-running")).toBeNull();
  });

  it("closes and clears the Inspector target when the selected project changes", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Solution Design details" }),
    );

    expect(await screen.findByRole("heading", { name: "Stage details" })).toBeTruthy();
    expect(await screen.findByText("stage-solution-design-running")).toBeTruthy();

    fireEvent.change(await screen.findByLabelText("Switch project"), {
      target: { value: "project-loaded" },
    });

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Checkout Service",
      }),
    ).toBeTruthy();
    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(within(inspector).getByText("Inspector closed")).toBeTruthy();
    expect(within(inspector).queryByText("stage-solution-design-running")).toBeNull();
  });
});

function ControlledInspectorPanel({
  target,
}: {
  target: {
    type: "stage";
    runId: string;
    stageRunId: string;
  };
}): JSX.Element {
  const [isOpen, setIsOpen] = useState(true);

  return (
    <InspectorPanel
      isOpen={isOpen}
      target={isOpen ? target : null}
      onClose={() => setIsOpen(false)}
      request={mockApiRequestOptions}
    />
  );
}

describe("Inspector trigger preservation", () => {
  it("keeps feed-only rendering working when no Inspector handler is passed", () => {
    render(<FeedEntryRenderer entry={mockFeedEntriesByType.stage_node} />);

    expect(screen.getByRole("article", { name: "Stage feed entry" })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Open Solution Design details" }),
    ).toBeNull();
  });

  it("keeps StageNode title fallback specific to the stage label", () => {
    const stage = mockFeedEntriesByType.stage_node as ExecutionNodeProjection;
    render(
      <FeedEntryRenderer entry={stage} onOpenInspectorTarget={() => undefined} />,
    );

    expect(
      screen.getByRole("button", { name: "Open Solution Design details" }),
    ).toBeTruthy();
  });

  it("uses entry titles for non-stage detail buttons", () => {
    const control = mockFeedEntriesByType.control_item as ControlItemFeedEntry;
    const tool = mockFeedEntriesByType.tool_confirmation as ToolConfirmationFeedEntry;
    const delivery = mockFeedEntriesByType.delivery_result as DeliveryResultFeedEntry;

    render(
      <NarrativeFeed
        entries={[control, tool, delivery]}
        onOpenInspectorTarget={() => undefined}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Open Clarification needed details" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Open Allow dependency install details" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Open demo_delivery details" }),
    ).toBeTruthy();
  });

  it("marks the high-risk tool confirmation details trigger as quiet", () => {
    const tool = mockFeedEntriesByType.tool_confirmation as ToolConfirmationFeedEntry;

    render(
      <FeedEntryRenderer entry={tool} onOpenInspectorTarget={() => undefined} />,
    );

    const detailsButton = screen.getByRole("button", {
      name: "Open Allow dependency install details",
    });
    expect(detailsButton.getAttribute("class")).toContain("inspector-trigger");
    expect(detailsButton.getAttribute("class")).toContain("inspector-trigger--quiet");
  });
});
