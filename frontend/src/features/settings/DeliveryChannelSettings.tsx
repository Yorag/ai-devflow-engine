import { useEffect, useState } from "react";

import type { ApiRequestOptions } from "../../api/client";
import { useProjectDeliveryChannelQuery } from "../../api/hooks";
import type {
  CodeReviewRequestType,
  DeliveryMode,
  ProjectRead,
  ScmProviderType,
} from "../../api/types";

type DeliveryChannelSettingsProps = {
  project: ProjectRead | null;
  request: ApiRequestOptions;
};

type DirtyFields = {
  deliveryMode: boolean;
  scmProviderType: boolean;
  repositoryIdentifier: boolean;
  defaultBranch: boolean;
  codeReviewRequestType: boolean;
  credentialRef: boolean;
};

const cleanFields: DirtyFields = {
  deliveryMode: false,
  scmProviderType: false,
  repositoryIdentifier: false,
  defaultBranch: false,
  codeReviewRequestType: false,
  credentialRef: false,
};

export function DeliveryChannelSettings({
  project,
  request,
}: DeliveryChannelSettingsProps): JSX.Element {
  const deliveryQuery = useProjectDeliveryChannelQuery(project?.project_id ?? "", {
    request,
  });
  const channel =
    deliveryQuery.data?.project_id === project?.project_id ? deliveryQuery.data : null;
  const [deliveryMode, setDeliveryMode] = useState<DeliveryMode>("demo_delivery");
  const [scmProviderType, setScmProviderType] = useState<ScmProviderType | "">("");
  const [repositoryIdentifier, setRepositoryIdentifier] = useState("");
  const [defaultBranch, setDefaultBranch] = useState("");
  const [codeReviewRequestType, setCodeReviewRequestType] =
    useState<CodeReviewRequestType | "">("");
  const [credentialRef, setCredentialRef] = useState("");
  const [dirtyFields, setDirtyFields] = useState<DirtyFields>(cleanFields);
  const [formProjectId, setFormProjectId] = useState<string | null>(null);

  useEffect(() => {
    setDirtyFields(cleanFields);
    setDeliveryMode("demo_delivery");
    setScmProviderType("");
    setRepositoryIdentifier("");
    setDefaultBranch("");
    setCodeReviewRequestType("");
    setCredentialRef("");
    setFormProjectId(null);
  }, [project?.project_id]);

  useEffect(() => {
    if (!channel) {
      return;
    }

    if (!dirtyFields.deliveryMode) {
      setDeliveryMode(channel.delivery_mode);
    }
    if (!dirtyFields.scmProviderType) {
      setScmProviderType(channel.scm_provider_type ?? "");
    }
    if (!dirtyFields.repositoryIdentifier) {
      setRepositoryIdentifier(channel.repository_identifier ?? "");
    }
    if (!dirtyFields.defaultBranch) {
      setDefaultBranch(channel.default_branch ?? "");
    }
    if (!dirtyFields.codeReviewRequestType) {
      setCodeReviewRequestType(channel.code_review_request_type ?? "");
    }
    if (!dirtyFields.credentialRef) {
      setCredentialRef(channel.credential_ref ?? "");
    }
    setFormProjectId(channel.project_id);
  }, [channel, dirtyFields]);

  function markDirty(field: keyof DirtyFields) {
    setDirtyFields((current) => ({ ...current, [field]: true }));
  }

  const heading = (
    <div className="settings-section__heading">
      <h3>通用配置</h3>
      <p>
        {project ? (
          <>
            Project: <span>{project.name}</span>
          </>
        ) : (
          "No project loaded"
        )}
      </p>
    </div>
  );

  if (!project) {
    return <div className="settings-section">{heading}</div>;
  }

  if (deliveryQuery.isError) {
    return (
      <div className="settings-section">
        {heading}
        <p className="settings-inline-error">Delivery channel is unavailable.</p>
      </div>
    );
  }

  if (deliveryQuery.isLoading || deliveryQuery.isFetching || !channel) {
    return (
      <div className="settings-section">
        {heading}
        <p>Loading delivery channel...</p>
      </div>
    );
  }

  if (formProjectId !== project.project_id) {
    return (
      <div className="settings-section">
        {heading}
        <p>Loading delivery channel...</p>
      </div>
    );
  }

  return (
    <div className="settings-section">
      {heading}
      <div className="settings-form-grid">
        <label>
          <span>Delivery mode</span>
          <select
            value={deliveryMode}
            onChange={(event) => {
              markDirty("deliveryMode");
              setDeliveryMode(event.target.value as DeliveryMode);
            }}
          >
            <option value="demo_delivery">demo_delivery</option>
            <option value="git_auto_delivery">git_auto_delivery</option>
          </select>
        </label>
        <label>
          <span>Readiness</span>
          <output>{channel?.readiness_status ?? "unconfigured"}</output>
        </label>
        <label>
          <span>Credential status</span>
          <output>
            {channel?.credential_status
              ? `credential ${channel.credential_status}`
              : "credential unbound"}
          </output>
        </label>
        <label>
          <span>SCM provider</span>
          <select
            value={scmProviderType}
            onChange={(event) => {
              markDirty("scmProviderType");
              setScmProviderType(event.target.value as ScmProviderType | "");
            }}
          >
            <option value="">Not required</option>
            <option value="github">github</option>
            <option value="gitlab">gitlab</option>
          </select>
        </label>
        <label>
          <span>Repository</span>
          <input
            value={repositoryIdentifier}
            onChange={(event) => {
              markDirty("repositoryIdentifier");
              setRepositoryIdentifier(event.target.value);
            }}
          />
        </label>
        <label>
          <span>Default branch</span>
          <input
            value={defaultBranch}
            onChange={(event) => {
              markDirty("defaultBranch");
              setDefaultBranch(event.target.value);
            }}
          />
        </label>
        <label>
          <span>Review request</span>
          <select
            value={codeReviewRequestType}
            onChange={(event) => {
              markDirty("codeReviewRequestType");
              setCodeReviewRequestType(
                event.target.value as CodeReviewRequestType | "",
              );
            }}
          >
            <option value="">Not required</option>
            <option value="pull_request">pull_request</option>
            <option value="merge_request">merge_request</option>
          </select>
        </label>
        <label>
          <span>Credential reference</span>
          <input
            value={credentialRef}
            onChange={(event) => {
              markDirty("credentialRef");
              setCredentialRef(event.target.value);
            }}
          />
        </label>
      </div>
      {channel?.readiness_message ? (
        <p className="settings-inline-error">{channel.readiness_message}</p>
      ) : null}
      <div className="settings-actions">
        <button type="button" className="workspace-button workspace-button--secondary">
          Validate delivery channel
        </button>
        <button type="button" className="workspace-button">
          Save delivery channel
        </button>
      </div>
    </div>
  );
}
