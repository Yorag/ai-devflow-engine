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
    expect(model.summary).toBe("Demo delivery generated a reviewable summary.");
    expect(model.metadata).toEqual([
      { label: "Mode", value: "demo_delivery" },
      { label: "Tests", value: "12 tests passed." },
      { label: "Reference", value: "delivery-result-ref-1" },
    ]);
    expect("highlights" in model).toBe(false);
  });

  it("keeps demo-delivery display summary-only even if git-like fields are present", () => {
    const model = buildDeliveryResultViewModel({
      ...(mockFeedEntriesByType.delivery_result as DeliveryResultFeedEntry),
      branch_name: "feat/leaked",
      commit_sha: "abc1234",
      code_review_url: "https://example.test/pr/17",
    });

    expect(model.modeLabel).toBe("Demo Delivery");
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
      within(article).getByText("Demo delivery generated a reviewable summary."),
    ).toBeTruthy();
    expect(within(article).getByText("Mode")).toBeTruthy();
    expect(within(article).getByText("demo_delivery")).toBeTruthy();
    expect(within(article).getByText("Tests")).toBeTruthy();
    expect(within(article).getByText("12 tests passed.")).toBeTruthy();
    expect(within(article).getByText("Reference")).toBeTruthy();
    expect(within(article).getByText("delivery-result-ref-1")).toBeTruthy();
    expect(article.textContent).not.toMatch(/\bBranch\b/i);
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
    expect(article.textContent).not.toMatch(/Branch:\s*feat\/leaked/i);
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
  it("keeps demo delivery detail free of git-auto-delivery output fields", () => {
    expect(mockDeliveryResultDetailProjection.delivery_mode).toBe("demo_delivery");
    expect(mockDeliveryResultDetailProjection.output.records).toEqual({
      delivery_summary:
        "Prepared a display-only delivery outcome for review without Git write actions.",
      delivery_target: "Demo delivery workspace summary",
      commit_message_preview:
        "feat(workspace): present demo delivery result in narrative feed",
    });
    expect(mockDeliveryResultDetailProjection.process.records).toEqual({
      integration_summary: "Prepared reviewable delivery summary for demo output.",
      review_status: "ready_for_review",
      review_notes: "Checklist preserved.\nNo semantic rewrites.",
    });
  });
});
