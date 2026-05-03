import type { ReactNode } from "react";

import type { RunSummaryProjection, TopLevelFeedEntry } from "../../api/types";

export type RunEntryGroup = {
  runId: string;
  attemptIndex: number | null;
  run?: RunSummaryProjection;
  entries: TopLevelFeedEntry[];
};

export type RunBoundaryProps = {
  group: RunEntryGroup;
  children: ReactNode;
};

export function RunBoundary({ group, children }: RunBoundaryProps): JSX.Element {
  if (!group.run) {
    return (
      <section
        className="run-boundary run-boundary--missing-metadata"
        id={getRunBoundaryId(group.runId)}
        aria-label="Run metadata unavailable boundary"
      >
        <header className="run-boundary__header">
          <div className="run-boundary__identity">
            <h2>Run metadata unavailable</h2>
          </div>
          <div
            className="run-boundary__status-row"
            role="group"
            aria-label="Run metadata unavailable summary"
          >
            <span>
              {group.entries.length} {group.entries.length === 1 ? "entry" : "entries"}
            </span>
          </div>
        </header>
        <div
          className="run-boundary__meta-grid"
          role="group"
          aria-label="Run metadata unavailable details"
        >
          <RunDatum label="Run id" value={group.runId} />
        </div>
        {children}
      </section>
    );
  }

  const runLabel = `Run ${group.run.attempt_index}`;
  const activeLabel = group.run.is_active ? "Current run" : "Historical run";

  return (
    <section
      className={`run-boundary run-boundary--${group.run.status}`}
      id={getRunBoundaryId(group.runId)}
      aria-label={`${runLabel} boundary`}
    >
      <header className="run-boundary__header">
        <div className="run-boundary__identity">
          <span className="run-boundary__eyebrow">{activeLabel}</span>
          <h2>{runLabel}</h2>
        </div>
        <div
          className="run-boundary__status-row"
          role="group"
          aria-label={`${runLabel} summary`}
        >
          <span>{formatLabel(group.run.status)}</span>
          <span>{formatLabel(group.run.trigger_source)}</span>
          <span>
            {group.entries.length} {group.entries.length === 1 ? "entry" : "entries"}
          </span>
        </div>
      </header>
      <div
        className="run-boundary__meta-grid"
        role="group"
        aria-label={`${runLabel} metadata`}
      >
        <RunDatum label="Started" value={formatTimestamp(group.run.started_at)} />
        {group.run.ended_at ? (
          <RunDatum label="Ended" value={formatTimestamp(group.run.ended_at)} />
        ) : null}
        {group.run.current_stage_type ? (
          <RunDatum label="Stage" value={formatLabel(group.run.current_stage_type)} />
        ) : null}
        <RunDatum label="Run id" value={group.run.run_id} />
      </div>
      {children}
    </section>
  );
}

export function groupEntriesByRun(
  entries: TopLevelFeedEntry[],
  runs: RunSummaryProjection[],
): RunEntryGroup[] {
  const entriesByRun = new Map<string, TopLevelFeedEntry[]>();
  for (const entry of entries) {
    const runEntries = entriesByRun.get(entry.run_id) ?? [];
    runEntries.push(entry);
    entriesByRun.set(entry.run_id, runEntries);
  }

  const groups: RunEntryGroup[] = runs.map((run) => ({
    runId: run.run_id,
    attemptIndex: run.attempt_index,
    run,
    entries: entriesByRun.get(run.run_id) ?? [],
  }));

  for (const [runId, runEntries] of entriesByRun.entries()) {
    if (!runs.some((run) => run.run_id === runId)) {
      groups.push({
        runId,
        attemptIndex: null,
        entries: runEntries,
      });
    }
  }

  return groups;
}

export function getRunBoundaryId(runId: string): string {
  return `run-boundary-${runId}`;
}

function RunDatum({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <span className="run-boundary__datum">
      <strong>{label}</strong>
      <span>{value}</span>
    </span>
  );
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatTimestamp(value: string): string {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
