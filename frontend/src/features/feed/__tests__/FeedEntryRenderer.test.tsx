import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithAppProviders } from "../../../app/test-utils";
import type { TopLevelFeedEntry } from "../../../api/types";
import { mockFeedEntriesByType, mockSessionWorkspaces } from "../../../mocks/fixtures";
import { mockApiRequestOptions } from "../../../mocks/handlers";
import { ConsolePage } from "../../../pages/ConsolePage";
import { FeedEntryRenderer, renderFeedEntryByType } from "../FeedEntryRenderer";
import { NarrativeFeed } from "../NarrativeFeed";

afterEach(() => {
  cleanup();
});

describe("FeedEntryRenderer", () => {
  it("renders each supported top-level entry with distinct semantics", () => {
    render(<NarrativeFeed entries={Object.values(mockFeedEntriesByType)} />);

    expect(
      screen.getByRole("article", { name: "User message feed entry" }),
    ).toBeTruthy();
    expect(screen.getByText("Add a workspace shell.")).toBeTruthy();

    const stageEntry = screen.getByRole("article", {
      name: "Stage feed entry",
    });
    expect(within(stageEntry).getByText("Solution Design")).toBeTruthy();
    expect(within(stageEntry).getByText("Running")).toBeTruthy();
    expect(within(stageEntry).getByText("2 items")).toBeTruthy();

    const approvalEntry = screen.getByRole("article", {
      name: "Approval request feed entry",
    });
    expect(within(approvalEntry).getByText("Review solution design")).toBeTruthy();
    expect(within(approvalEntry).getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(within(approvalEntry).getByRole("button", { name: "Reject" })).toBeTruthy();

    const toolEntry = screen.getByRole("article", {
      name: "Tool confirmation feed entry",
    });
    expect(within(toolEntry).getByText("Allow dependency install")).toBeTruthy();
    expect(within(toolEntry).getByText("bash")).toBeTruthy();
    expect(
      within(toolEntry).getByRole("button", { name: "Allow this execution" }),
    ).toBeTruthy();
    expect(
      within(toolEntry).getByRole("button", { name: "Deny this execution" }),
    ).toBeTruthy();
    expect(within(toolEntry).queryByText("Approve")).toBeNull();
    expect(within(toolEntry).queryByText("Reject")).toBeNull();

    expect(
      screen.getByRole("article", { name: "Control item feed entry" }),
    ).toBeTruthy();
    expect(screen.getByText("Clarification needed")).toBeTruthy();

    expect(
      screen.getByRole("article", { name: "Approval result feed entry" }),
    ).toBeTruthy();
    expect(screen.getByText("Approved")).toBeTruthy();

    expect(
      screen.getByRole("article", { name: "Delivery result feed entry" }),
    ).toBeTruthy();
    expect(
      screen.getByText("Demo delivery generated a reviewable summary."),
    ).toBeTruthy();

    const systemEntry = screen.getByRole("article", {
      name: "System status feed entry",
    });
    expect(within(systemEntry).getByText("Run failed")).toBeTruthy();
    expect(within(systemEntry).getByRole("button", { name: "Retry run" })).toBeTruthy();
  });

  it("preserves the provided top-level feed order", () => {
    const entries: TopLevelFeedEntry[] = [
      mockFeedEntriesByType.user_message,
      mockFeedEntriesByType.approval_request,
      mockFeedEntriesByType.tool_confirmation,
      mockFeedEntriesByType.delivery_result,
    ];

    render(<NarrativeFeed entries={entries} />);

    const labels = screen
      .getAllByRole("listitem")
      .map((item) => within(item).getByRole("article").getAttribute("aria-label"));

    expect(labels).toEqual([
      "User message feed entry",
      "Approval request feed entry",
      "Tool confirmation feed entry",
      "Delivery result feed entry",
    ]);
  });

  it("does not fabricate a completed-run system status entry", () => {
    render(
      <NarrativeFeed
        entries={mockSessionWorkspaces["session-completed"].narrative_feed}
      />,
    );

    expect(
      screen.getByRole("article", { name: "Delivery result feed entry" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("article", { name: "System status feed entry" }),
    ).toBeNull();
  });

  it("exposes the direct render helper for focused top-level entry dispatch", () => {
    render(renderFeedEntryByType(mockFeedEntriesByType.control_item));

    expect(
      screen.getByRole("article", { name: "Control item feed entry" }),
    ).toBeTruthy();
    expect(screen.getByText("Requirement Analysis")).toBeTruthy();
  });

  it("renders the selected non-draft workspace feed instead of placeholder copy", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );

    expect(
      await screen.findByRole("article", { name: "User message feed entry" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("article", { name: "Stage feed entry" }),
    ).toBeTruthy();
    expect(
      screen.getByText("Designing the workspace shell boundaries."),
    ).toBeTruthy();
    expect(
      screen.queryByText("Run history and execution feed will appear here."),
    ).toBeNull();
  });

  it("renders an empty feed state for non-draft sessions without feed entries", () => {
    render(<NarrativeFeed entries={[]} />);

    expect(
      screen.getByRole("region", { name: "Narrative Feed empty state" }),
    ).toBeTruthy();
    expect(screen.getByText("No run entries yet")).toBeTruthy();
  });
});

describe("FeedEntryRenderer guards", () => {
  it("renders single entries without requiring the list wrapper", () => {
    render(<FeedEntryRenderer entry={mockFeedEntriesByType.delivery_result} />);

    expect(
      screen.getByRole("article", { name: "Delivery result feed entry" }),
    ).toBeTruthy();
    expect(screen.getByText("demo_delivery")).toBeTruthy();
  });
});
