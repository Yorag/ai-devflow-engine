import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { DeliveryResultFeedEntry } from "../../../api/types";
import {
  mockDeliveryResultDetailProjection,
  mockFeedEntriesByType,
} from "../../../mocks/fixtures";
import {
  DeliveryResultBlock,
  buildDeliveryResultViewModel,
} from "../DeliveryResultBlock";

afterEach(() => {
  cleanup();
});

describe("buildDeliveryResultViewModel", () => {
  it("builds a demo-delivery summary without fabricating git-only fields", () => {
    const model = buildDeliveryResultViewModel(
      mockFeedEntriesByType.delivery_result as DeliveryResultFeedEntry,
    );

    expect(model.modeLabel).toBe("Demo Delivery");
    expect(model.title).toBe("Demo delivery");
    expect(model.summary).toBe("Demo delivery completed without Git writes.");
    expect(model.metadata).toEqual([
      { label: "Mode", value: "demo_delivery" },
      { label: "Display branch", value: "demo/run-completed" },
      { label: "Tests", value: "Deterministic test path completed." },
      { label: "Reference", value: "demo-delivery-result:run-completed" },
    ]);
    expect("highlights" in model).toBe(false);
  });

  it("renders the demo display branch but not git write fields when git-like fields are present", () => {
    const model = buildDeliveryResultViewModel({
      ...(mockFeedEntriesByType.delivery_result as DeliveryResultFeedEntry),
      branch_name: "feat/leaked",
      commit_sha: "abc1234",
      code_review_url: "https://example.test/pr/17",
    });

    expect(model.modeLabel).toBe("Demo Delivery");
    expect(model.metadata).toContainEqual({
      label: "Display branch",
      value: "feat/leaked",
    });
    expect(model.metadata).not.toContainEqual({
      label: "Commit",
      value: "abc1234",
    });
    expect(model.metadata).not.toContainEqual({
      label: "Code review",
      value: "example.test/pr/17",
      href: "https://example.test/pr/17",
    });
    expect("highlights" in model).toBe(false);
  });
});

describe("DeliveryResultBlock", () => {
  it("renders the demo-delivery result block with summary metadata and details trigger", () => {
    render(
      <DeliveryResultBlock
        entry={mockFeedEntriesByType.delivery_result as DeliveryResultFeedEntry}
        onOpenInspectorTarget={() => undefined}
      />,
    );

    const article = screen.getByRole("article", {
      name: "Delivery result feed entry",
    });
    expect(within(article).getByText("Delivery result")).toBeTruthy();
    expect(within(article).getByText("Demo delivery")).toBeTruthy();
    expect(
      within(article).getByText("Demo delivery completed without Git writes."),
    ).toBeTruthy();
    expect(within(article).getByText("Mode")).toBeTruthy();
    expect(within(article).getByText("demo_delivery")).toBeTruthy();
    expect(within(article).getByText("Display branch")).toBeTruthy();
    expect(within(article).getByText("demo/run-completed")).toBeTruthy();
    expect(within(article).getByText("Tests")).toBeTruthy();
    expect(
      within(article).getByText("Deterministic test path completed."),
    ).toBeTruthy();
    expect(within(article).getByText("Reference")).toBeTruthy();
    expect(
      within(article).getByText("demo-delivery-result:run-completed"),
    ).toBeTruthy();
    expect(article.textContent).not.toMatch(/\bCommit\b/i);
    expect(article.textContent).not.toMatch(/\bCode review\b/i);
    expect(
      within(article).getByRole("button", { name: "Open demo_delivery details" }),
    ).toBeTruthy();
  });

  it("does not render git-specific text for demo delivery and uses the shared title-row hook", () => {
    render(
      <DeliveryResultBlock
        entry={{
          ...(mockFeedEntriesByType.delivery_result as DeliveryResultFeedEntry),
          branch_name: "feat/leaked",
          commit_sha: "abc1234",
          code_review_url: "https://example.test/pr/17",
        }}
        onOpenInspectorTarget={() => undefined}
      />,
    );

    const article = screen.getByRole("article", {
      name: "Delivery result feed entry",
    });
    expect(article.textContent).toContain("Display branch");
    expect(article.textContent).toContain("feat/leaked");
    expect(article.textContent).not.toMatch(/Commit:\s*abc1234/i);
    expect(article.textContent).not.toMatch(
      /Code review:\s*https:\/\/example\.test\/pr\/17/i,
    );
    expect(
      within(article)
        .getByText("Demo delivery")
        .parentElement?.classList.contains("feed-entry__title-row"),
    ).toBe(true);
  });

  it("renders without an inspector action when no open callback is provided", () => {
    render(
      <DeliveryResultBlock
        entry={mockFeedEntriesByType.delivery_result as DeliveryResultFeedEntry}
      />,
    );

    expect(screen.queryByRole("button", { name: /open .* details/i })).toBeNull();
  });
});

describe("demo delivery detail fixture", () => {
  it("matches the real backend demo DeliveryResultDetailProjection payload", () => {
    expect(mockDeliveryResultDetailProjection.delivery_mode).toBe("demo_delivery");
    expect(mockDeliveryResultDetailProjection.input.records).toMatchObject({
      delivery_channel_snapshot_ref: "delivery-snapshot-1",
    });
    expect(mockDeliveryResultDetailProjection.process.records).toMatchObject({
      no_git_actions: true,
      git_write_actions: [],
      delivery_result_event_ref: "event-delivery-result-1",
    });
    expect(mockDeliveryResultDetailProjection.output.records).toMatchObject({
      summary: "Delivery integration completed for demo_delivery path.",
      delivery_status: "succeeded",
      result_ref: "demo-delivery-result:run-completed",
      branch_name: "demo/run-completed",
      commit_sha: null,
      code_review_url: null,
      failure_reason: null,
      test_summary: "Deterministic test plan and execution summary produced.",
      review_summary: "Deterministic review summary produced.",
    });
  });
});
