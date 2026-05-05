import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { DeliveryResultFeedEntry } from "../../../api/types";
import { mockGitDeliveryResultFeedEntry } from "../../../mocks/fixtures";
import {
  DeliveryResultBlock,
  buildDeliveryResultViewModel,
  formatCodeReviewRequestTarget,
  formatDeliveryHighlights,
} from "../DeliveryResultBlock";

afterEach(() => {
  cleanup();
});

const gitDeliveryEntry: DeliveryResultFeedEntry = {
  entry_id: "entry-git-auto-delivery-result",
  run_id: "run-git-auto-delivery",
  type: "delivery_result",
  occurred_at: "2026-05-01T09:55:00.000Z",
  delivery_record_id: "delivery-record-git-1",
  delivery_mode: "git_auto_delivery",
  status: "succeeded",
  summary:
    "Git auto delivery pushed the reviewed changes and opened a pull request.",
  branch_name:
    "feature/extremely-long-runtime-delivery-result-branch-name-that-wraps",
  commit_sha: "8f14e45fceea167a5a36dedd4bea2543a17f8b9a",
  code_review_url: "https://github.com/acme/devflow-engine/pull/42",
  test_summary: "Frontend 214/214 tests passed.",
  result_ref: "delivery-result-ref-git-42",
};

describe("formatCodeReviewRequestTarget", () => {
  it("formats valid review URLs without losing the link target", () => {
    expect(
      formatCodeReviewRequestTarget(
        "https://github.com/acme/devflow-engine/pull/42",
      ),
    ).toBe("github.com/acme/devflow-engine/pull/42");
  });

  it("falls back to the raw value for non-url review targets", () => {
    expect(formatCodeReviewRequestTarget("review-request-42")).toBe(
      "review-request-42",
    );
  });
});

describe("formatDeliveryHighlights", () => {
  it("returns git-auto-delivery result points from the current feed contract", () => {
    expect(formatDeliveryHighlights(gitDeliveryEntry)).toEqual([
      {
        label: "Branch",
        value:
          "feature/extremely-long-runtime-delivery-result-branch-name-that-wraps",
      },
      {
        label: "Commit",
        value: "8f14e45fceea167a5a36dedd4bea2543a17f8b9a",
      },
      {
        label: "Code review",
        value: "github.com/acme/devflow-engine/pull/42",
        href: "https://github.com/acme/devflow-engine/pull/42",
      },
      { label: "Tests", value: "Frontend 214/214 tests passed." },
      { label: "Reference", value: "delivery-result-ref-git-42" },
    ]);
  });

  it("does not fabricate empty commit or code review placeholders", () => {
    expect(
      formatDeliveryHighlights({
        ...gitDeliveryEntry,
        commit_sha: null,
        code_review_url: null,
      }),
    ).toEqual([
      {
        label: "Branch",
        value:
          "feature/extremely-long-runtime-delivery-result-branch-name-that-wraps",
      },
      { label: "Tests", value: "Frontend 214/214 tests passed." },
      { label: "Reference", value: "delivery-result-ref-git-42" },
    ]);
  });
});

describe("buildDeliveryResultViewModel for git_auto_delivery", () => {
  it("maps the real backend git delivery_result payload into the shared model", () => {
    const model = buildDeliveryResultViewModel(mockGitDeliveryResultFeedEntry);

    expect(model.modeLabel).toBe("Git Auto Delivery");
    expect(model.title).toBe("Git auto delivery");
    expect(model.summary).toBe("Delivery completed.");
    expect(model.metadata).toEqual([
      { label: "Mode", value: "git_auto_delivery" },
      { label: "Branch", value: "feature/run-delivery" },
      { label: "Commit", value: "abc123def456" },
      {
        label: "Code review",
        value: "github.example/pulls/1",
        href: "https://github.example/pulls/1",
      },
      { label: "Tests", value: "Resolved upstream test summary." },
      { label: "Reference", value: "git-delivery-result:run-delivery" },
    ]);
  });

  it("uses the shared result model with git-auto-delivery mode labels", () => {
    const model = buildDeliveryResultViewModel(gitDeliveryEntry);

    expect(model.modeLabel).toBe("Git Auto Delivery");
    expect(model.title).toBe("Git auto delivery");
    expect(model.summary).toBe(
      "Git auto delivery pushed the reviewed changes and opened a pull request.",
    );
    expect(model.metadata).toEqual([
      { label: "Mode", value: "git_auto_delivery" },
      {
        label: "Branch",
        value:
          "feature/extremely-long-runtime-delivery-result-branch-name-that-wraps",
      },
      {
        label: "Commit",
        value: "8f14e45fceea167a5a36dedd4bea2543a17f8b9a",
      },
      {
        label: "Code review",
        value: "github.com/acme/devflow-engine/pull/42",
        href: "https://github.com/acme/devflow-engine/pull/42",
      },
      { label: "Tests", value: "Frontend 214/214 tests passed." },
      { label: "Reference", value: "delivery-result-ref-git-42" },
    ]);
    expect("highlights" in model).toBe(false);
  });
});

describe("DeliveryResultBlock for git_auto_delivery", () => {
  it("renders branch, commit, review link, tests, and details from the shared block", () => {
    render(
      <DeliveryResultBlock
        entry={gitDeliveryEntry}
        onOpenInspectorTarget={() => undefined}
      />,
    );

    const article = screen.getByRole("article", {
      name: "Delivery result feed entry",
    });
    expect(within(article).getByText("Git auto delivery")).toBeTruthy();
    expect(within(article).getByText("Git Auto Delivery")).toBeTruthy();
    expect(
      within(article).getByText(
        "Git auto delivery pushed the reviewed changes and opened a pull request.",
      ),
    ).toBeTruthy();
    expect(within(article).getByText("Branch")).toBeTruthy();
    expect(
      within(article).getByText(
        "feature/extremely-long-runtime-delivery-result-branch-name-that-wraps",
      ),
    ).toBeTruthy();
    expect(within(article).getByText("Commit")).toBeTruthy();
    expect(
      within(article).getByText("8f14e45fceea167a5a36dedd4bea2543a17f8b9a"),
    ).toBeTruthy();

    const reviewLink = within(article).getByRole("link", {
      name: "Code review github.com/acme/devflow-engine/pull/42",
    });
    expect(reviewLink.getAttribute("href")).toBe(
      "https://github.com/acme/devflow-engine/pull/42",
    );
    expect(reviewLink.getAttribute("target")).toBe("_blank");
    expect(reviewLink.getAttribute("rel")).toBe("noopener noreferrer");

    expect(within(article).getByText("Tests")).toBeTruthy();
    expect(
      within(article).getByText("Frontend 214/214 tests passed."),
    ).toBeTruthy();
    expect(within(article).getByText("Reference")).toBeTruthy();
    expect(within(article).getByText("delivery-result-ref-git-42")).toBeTruthy();
    expect(
      within(article).getByRole("button", {
        name: "Open git_auto_delivery details",
      }),
    ).toBeTruthy();
  });

  it("does not render empty review or commit placeholders", () => {
    render(
      <DeliveryResultBlock
        entry={{ ...gitDeliveryEntry, commit_sha: null, code_review_url: null }}
      />,
    );

    const article = screen.getByRole("article", {
      name: "Delivery result feed entry",
    });
    expect(article.textContent).toContain("Branch");
    expect(article.textContent).not.toMatch(/\bCommit\b/);
    expect(article.textContent).not.toMatch(/\bCode review\b/);
    expect(within(article).queryByRole("link")).toBeNull();
  });
});
