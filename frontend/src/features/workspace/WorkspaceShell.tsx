import { useState } from "react";

import type { ProjectRead } from "../../api/types";
import { mockApiRequestOptions } from "../../mocks/handlers";
import { SettingsModal } from "../settings/SettingsModal";
import { ProjectSidebar } from "./ProjectSidebar";

export function WorkspaceShell(): JSX.Element {
  const [currentProjectId, setCurrentProjectId] = useState("");
  const [currentProject, setCurrentProject] = useState<ProjectRead | null>(null);
  const [isSettingsOpen, setSettingsOpen] = useState(false);

  return (
    <section className="workspace-shell" aria-label="Workspace shell">
      <ProjectSidebar
        request={mockApiRequestOptions}
        currentProjectId={currentProjectId}
        onProjectChange={setCurrentProjectId}
        onCurrentProjectChange={setCurrentProject}
      />
      <section className="workspace-main" aria-label="Narrative workspace">
        <div className="workspace-toolbar" aria-label="Global tools">
          <button
            className="workspace-button workspace-button--secondary workspace-button--compact"
            type="button"
            onClick={() => setSettingsOpen(true)}
            aria-label="Open settings"
          >
            Settings
          </button>
        </div>
        <div className="workspace-main__empty">
          <p className="workspace-eyebrow">Narrative Workspace</p>
          <h1>Workspace</h1>
          <p>Select a session to review its run history and execution feed.</p>
        </div>
      </section>
      <aside className="workspace-inspector" aria-label="Inspector">
        <p>Inspector closed</p>
      </aside>
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setSettingsOpen(false)}
        project={currentProject}
        request={mockApiRequestOptions}
      />
    </section>
  );
}
