import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ApiRequestOptions } from "../../../api/client";
import { renderWithAppProviders } from "../../../app/test-utils";
import {
  mockCodeGenerationStageNode,
  mockFeedEntriesByType,
} from "../../../mocks/fixtures";
import {
  createMockApiFetcher,
  mockApiRequestOptions,
} from "../../../mocks/handlers";
import { ConsolePage } from "../../../pages/ConsolePage";
import { NarrativeFeed } from "../../feed/NarrativeFeed";
import { useWorkspaceStore } from "../../workspace/workspace-store";
import { InspectorPanel } from "../InspectorPanel";
import { useInspector } from "../useInspector";

afterEach(() => {
  cleanup();
  useWorkspaceStore.getState().resetWorkspace();
});

function InspectorHarness({
  entries,
  request = mockApiRequestOptions,
}: {
  entries: Parameters<typeof NarrativeFeed>[0]["entries"];
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

describe("InspectorSections", () => {
  it("renders grouped stage detail content and hides inapplicable metrics", async () => {
    renderWithAppProviders(
      <InspectorHarness
        entries={[mockFeedEntriesByType.stage_node]}
        request={mockApiRequestOptions}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open Solution Design details" }));

    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(await within(inspector).findByRole("heading", { name: "Identity" })).toBeTruthy();
    expect(within(inspector).getByRole("heading", { name: "Input" })).toBeTruthy();
    expect(within(inspector).getByRole("heading", { name: "Process" })).toBeTruthy();
    expect(within(inspector).getByRole("heading", { name: "Output" })).toBeTruthy();
    expect(within(inspector).getByRole("heading", { name: "Artifacts" })).toBeTruthy();
    expect(within(inspector).getByRole("heading", { name: "Metrics" })).toBeTruthy();
    expect(within(inspector).getByText("Draft execution plan")).toBeTruthy();
    expect(within(inspector).getByText("Render grouped inspector sections")).toBeTruthy();
    expect(within(inspector).getByText("tool-confirmation-trace-1")).toBeTruthy();
    expect(within(inspector).getByText("provider-retry-trace-1")).toBeTruthy();
    expect(within(inspector).getByText("provider-circuit-trace-1")).toBeTruthy();
    expect(within(inspector).getByText("4,800")).toBeTruthy();
    expect(within(inspector).getByText("0")).toBeTruthy();
    expect(within(inspector).queryByText("Delivery Artifact Count")).toBeNull();
  });

  it("renders tool confirmation detail from the tool projection rather than the stage projection", async () => {
    renderWithAppProviders(
      <InspectorHarness
        entries={[mockFeedEntriesByType.tool_confirmation]}
        request={mockApiRequestOptions}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Open Allow dependency install details" }),
    );

    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(await within(inspector).findByText("npm install")).toBeTruthy();
    expect(within(inspector).getByText("dependency_change")).toBeTruthy();
    expect(within(inspector).getByText("package-lock update")).toBeTruthy();
    expect(within(inspector).queryByText("Draft execution plan")).toBeNull();
  });

  it("keeps the complete diff and test records in inspector detail while the feed stays preview-oriented", async () => {
    renderWithAppProviders(
      <InspectorHarness
        entries={[mockCodeGenerationStageNode]}
        request={mockApiRequestOptions}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open Code Generation details" }));

    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(await within(inspector).findByText("Full diff for F5.1")).toBeTruthy();
    expect(within(inspector).getByText("pytest stdout line 17")).toBeTruthy();
  });
});

describe("WorkspaceShell Inspector request plumbing", () => {
  it("uses the page request options when grouped detail loads inside ConsolePage", async () => {
    renderWithAppProviders(<ConsolePage request={mockApiRequestOptions} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open Add workspace shell" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Solution Design details" }),
    );

    expect(await screen.findByText("Render grouped inspector sections")).toBeTruthy();
  });
});

describe("InspectorSections detail states", () => {
  it("renders delivery result detail artifacts and review outcome", async () => {
    renderWithAppProviders(
      <InspectorHarness
        entries={[mockFeedEntriesByType.delivery_result]}
        request={mockApiRequestOptions}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open demo_delivery details" }));

    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(
      await within(inspector).findByText(
        "Prepared a display-only delivery outcome for review without Git write actions.",
      ),
    ).toBeTruthy();
    expect(within(inspector).getByText("Demo delivery workspace summary")).toBeTruthy();
    expect(
      within(inspector).getByText(
        "feat(workspace): present demo delivery result in narrative feed",
      ),
    ).toBeTruthy();
    expect(within(inspector).queryByText("feat/runtime-inspector")).toBeNull();
    expect(within(inspector).queryByText("abc1234")).toBeNull();
    expect(within(inspector).queryByText("https://example.test/pr/17")).toBeNull();
    expect(within(inspector).getByText("12 tests passed.")).toBeTruthy();

    const reviewNotes = within(inspector).getByText(/Checklist preserved\./);
    expect(reviewNotes.closest("pre")).toBeTruthy();
  });

  it("renders the unified API error state when detail loading fails", async () => {
    const fetcher = createMockApiFetcher();
    const failingRequest: ApiRequestOptions = {
      fetcher: async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/stages/stage-solution-design-running/inspector")) {
          return new Response(
            JSON.stringify({
              code: "not_found",
              message: "Missing Inspector detail.",
              request_id: "mock-request-inspector-missing",
            }),
            {
              status: 404,
              headers: { "content-type": "application/json" },
            },
          );
        }

        return fetcher(input, init);
      },
    };

    renderWithAppProviders(
      <InspectorHarness
        entries={[mockFeedEntriesByType.stage_node]}
        request={failingRequest}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open Solution Design details" }));

    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(await within(inspector).findByText("Inspector unavailable")).toBeTruthy();
    expect(within(inspector).getByText("Missing Inspector detail.")).toBeTruthy();
    expect(
      within(inspector).getByText("Request ID: mock-request-inspector-missing"),
    ).toBeTruthy();
  });
});
