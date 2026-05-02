import { mockApiRequestOptions } from "../../mocks/handlers";
import { ProjectSidebar } from "./ProjectSidebar";

export function WorkspaceShell(): JSX.Element {
  return (
    <section className="workspace-shell" aria-label="Workspace shell">
      <ProjectSidebar request={mockApiRequestOptions} />
      <section className="workspace-main" aria-label="Narrative workspace">
        <div className="workspace-main__empty">
          <p className="workspace-eyebrow">Narrative Workspace</p>
          <h1>Workspace</h1>
          <p>Select a session to review its run history and execution feed.</p>
        </div>
      </section>
      <aside className="workspace-inspector" aria-label="Inspector">
        <p>Inspector closed</p>
      </aside>
    </section>
  );
}
