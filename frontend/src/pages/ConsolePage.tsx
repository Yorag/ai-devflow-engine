import type { ApiRequestOptions } from "../api/client";
import { WorkspaceShell } from "../features/workspace/WorkspaceShell";

type ConsolePageProps = {
  request?: ApiRequestOptions;
};

export function ConsolePage({ request }: ConsolePageProps = {}): JSX.Element {
  return (
    <div className="console-page">
      <WorkspaceShell request={request} />
    </div>
  );
}
