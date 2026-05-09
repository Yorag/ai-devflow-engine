import type { ExecutionNodeProjection } from "../../api/types";
import {
  formatStatusLabel,
  stageLabels,
} from "./display-labels";
import { stageNodeItemsForDisplay, StageNodeItems } from "./StageNodeItems";

export type StageNodeProps = {
  entry: ExecutionNodeProjection;
  onOpenInspectorTarget?: (entry: ExecutionNodeProjection) => void;
};

export function StageNode({
  entry,
  onOpenInspectorTarget,
}: StageNodeProps): JSX.Element {
  const hasDisplayItems = stageNodeItemsForDisplay(entry.items).length > 0;

  return (
    <article
      className={`feed-entry feed-entry--stage-node stage-node stage-node--${entry.status}`}
      aria-label="阶段执行流"
    >
      <header className="stage-node__header">
        <div className="stage-node__identity">
          <h2>{stageLabels[entry.stage_type]}</h2>
          <p className="stage-node__summary">{entry.summary}</p>
        </div>
        <div className="stage-node__header-actions">
          <span className="stage-node__status">{formatStatusLabel(entry.status)}</span>
          {onOpenInspectorTarget ? (
            <button
              type="button"
              className="inspector-trigger"
              onClick={() => onOpenInspectorTarget(entry)}
              aria-label={`查看${stageLabels[entry.stage_type]}详情`}
            >
              查看详情
            </button>
          ) : null}
        </div>
      </header>
      {hasDisplayItems ? (
        <StageNodeItems
          items={entry.items}
          stageType={entry.stage_type}
          stageMetrics={entry.metrics}
        />
      ) : (
        <p className="stage-node__empty" aria-label="Stage has no internal items">
          暂无执行步骤。
        </p>
      )}
    </article>
  );
}
