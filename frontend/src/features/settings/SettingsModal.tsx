import { useEffect, useRef, useState } from "react";

import type { ApiRequestOptions } from "../../api/client";
import type { ProjectRead } from "../../api/types";
import { ConfigurationPackageSettings } from "./ConfigurationPackageSettings";
import { DeliveryChannelSettings } from "./DeliveryChannelSettings";
import { ProviderSettings } from "./ProviderSettings";

type SettingsTab = "general" | "providers" | "configuration-package";

type SettingsModalProps = {
  isOpen: boolean;
  onClose: () => void;
  project: ProjectRead | null;
  request: ApiRequestOptions;
};

const tabs: Array<{ id: SettingsTab; label: string }> = [
  { id: "general", label: "通用配置" },
  { id: "providers", label: "模型提供商" },
  { id: "configuration-package", label: "导入导出" },
];

export function SettingsModal({
  isOpen,
  onClose,
  project,
  request,
}: SettingsModalProps): JSX.Element | null {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const activeTabLabel = tabs.find((tab) => tab.id === activeTab)?.label;

  onCloseRef.current = onClose;

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const activeElement = document.activeElement;
    openerRef.current =
      activeElement instanceof HTMLElement &&
      !dialogRef.current?.contains(activeElement)
        ? activeElement
        : null;
    const initialFocus =
      closeButtonRef.current ??
      getFocusableElements(dialogRef.current).at(0) ??
      dialogRef.current;
    initialFocus?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const dialog = dialogRef.current;
      if (!dialog) {
        return;
      }

      const focusableElements = getFocusableElements(dialog);
      if (focusableElements.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;

      if (event.shiftKey) {
        if (activeElement === firstElement || !dialog.contains(activeElement)) {
          event.preventDefault();
          lastElement.focus();
        }
        return;
      }

      if (activeElement === lastElement || !dialog.contains(activeElement)) {
        event.preventDefault();
        firstElement.focus();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (openerRef.current?.isConnected) {
        openerRef.current.focus();
      }
      openerRef.current = null;
    };
  }, [isOpen]);

  if (!isOpen) {
    return null;
  }

  return (
    <div className="settings-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="settings-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        tabIndex={-1}
      >
        <header className="settings-modal__header">
          <div>
            <p className="workspace-eyebrow">Settings</p>
            <h2 id="settings-title">Settings</h2>
          </div>
          <button
            ref={closeButtonRef}
            className="settings-icon-button"
            type="button"
            onClick={onClose}
            aria-label="Close settings"
          >
            x
          </button>
        </header>
        <div className="settings-modal__body">
          <nav className="settings-tabs" role="tablist" aria-label="Settings sections">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                aria-controls={`settings-panel-${tab.id}`}
                id={`settings-tab-${tab.id}`}
                className="settings-tab"
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </nav>
          <section
            className="settings-panel"
            role="tabpanel"
            id={`settings-panel-${activeTab}`}
            aria-labelledby={`settings-tab-${activeTab}`}
            aria-label={activeTabLabel}
          >
            {activeTab === "general" ? (
              <DeliveryChannelSettings project={project} request={request} />
            ) : activeTab === "providers" ? (
              <ProviderSettings request={request} />
            ) : activeTab === "configuration-package" ? (
              <ConfigurationPackageSettings project={project} request={request} />
            ) : (
              <>
                <h3>{activeTabLabel}</h3>
                <p>{project?.name ?? "No project loaded"}</p>
              </>
            )}
          </section>
        </div>
      </section>
    </div>
  );
}

function getFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) {
    return [];
  }

  return Array.from(
    container.querySelectorAll<HTMLElement>(
      [
        "button:not([disabled])",
        "input:not([disabled])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "summary",
        "a[href]",
        "[tabindex]:not([tabindex='-1'])",
      ].join(","),
    ),
  );
}
