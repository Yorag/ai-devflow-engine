import type { RunEntryGroup } from "./RunBoundary";
import { getRunBoundaryId } from "./RunBoundary";

export type RunSwitcherProps = {
  groups: RunEntryGroup[];
  currentRunId?: string | null;
};

export function RunSwitcher({
  groups,
  currentRunId = null,
}: RunSwitcherProps): JSX.Element | null {
  if (groups.length <= 1) {
    return null;
  }

  const metadataGroups = groups.filter((group) => group.run);
  if (metadataGroups.length <= 1) {
    return null;
  }

  const focusedRunId =
    metadataGroups.find((group) => group.run?.is_active)?.runId ??
    metadataGroups.find((group) => group.runId === currentRunId)?.runId ??
    metadataGroups[metadataGroups.length - 1]?.runId ??
    null;

  return (
    <nav className="run-switcher" aria-label="Run Switcher">
      <ol className="run-switcher__items">
        {metadataGroups.map((group) => {
          const isCurrent = Boolean(group.run) && group.runId === focusedRunId;
          const label = `Run ${group.run?.attempt_index ?? ""} ${formatLabel(
            group.run?.status ?? "",
          )}`;
          return (
            <li key={group.runId}>
              <button
                type="button"
                className="run-switcher__button"
                aria-label={
                  isCurrent
                    ? `${label} Current run`
                    : label
                }
                aria-current={isCurrent ? "true" : undefined}
                onClick={() => scrollToRunBoundary(group.runId)}
              >
                <span>{label}</span>
                {isCurrent ? <strong>Current run</strong> : null}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function scrollToRunBoundary(runId: string, root: Document = document): boolean {
  const target = root.getElementById(getRunBoundaryId(runId));
  if (!target) {
    return false;
  }

  target.scrollIntoView({ behavior: "smooth", block: "start" });
  return true;
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
