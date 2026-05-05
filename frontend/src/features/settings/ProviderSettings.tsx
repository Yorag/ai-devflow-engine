import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { ApiRequestError, ApiRequestOptions } from "../../api/client";
import { apiQueryKeys, useProvidersQuery } from "../../api/hooks";
import { createProvider, patchProvider } from "../../api/providers";
import type {
  ModelRuntimeCapabilities,
  ProviderProtocolType,
  ProviderRead,
  ProviderWriteRequest,
} from "../../api/types";

type ProviderSettingsProps = {
  request?: ApiRequestOptions;
};

type ProviderTemplate = {
  templateId: "volcengine" | "deepseek" | "openai-completions";
  providerId?: string;
  displayName: string;
  protocolType: ProviderProtocolType;
  baseUrl: string;
  apiKeyRef: string;
  defaultModelId: string;
  supportedModelIds: string[];
  capabilities: ModelRuntimeCapabilities[];
};

type ProviderDraft = {
  baseUrl: string;
  apiKeyInput: string;
  apiKeyTouched: boolean;
  supportedModels: string;
  defaultModel: string;
  isEnabled: boolean;
};

const providerTemplates: ProviderTemplate[] = [
  {
    templateId: "volcengine",
    providerId: "provider-volcengine",
    displayName: "火山引擎",
    protocolType: "volcengine_native",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    apiKeyRef: "env:VOLCENGINE_API_KEY",
    defaultModelId: "doubao-seed-1-6",
    supportedModelIds: ["doubao-seed-1-6"],
    capabilities: [
      createDefaultCapability("doubao-seed-1-6", {
        max_output_tokens: 8192,
        supports_tool_calling: true,
        supports_structured_output: true,
      }),
    ],
  },
  {
    templateId: "deepseek",
    providerId: "provider-deepseek",
    displayName: "DeepSeek",
    protocolType: "openai_completions_compatible",
    baseUrl: "https://api.deepseek.com",
    apiKeyRef: "env:DEEPSEEK_API_KEY",
    defaultModelId: "deepseek-chat",
    supportedModelIds: ["deepseek-chat", "deepseek-reasoner"],
    capabilities: [
      createDefaultCapability("deepseek-chat", {
        max_output_tokens: 8192,
        supports_tool_calling: true,
      }),
      createDefaultCapability("deepseek-reasoner", {
        max_output_tokens: 8192,
        supports_native_reasoning: true,
      }),
    ],
  },
  {
    templateId: "openai-completions",
    displayName: "OpenAI Completions",
    protocolType: "openai_completions_compatible",
    baseUrl: "https://api.openai.com/v1",
    apiKeyRef: "env:OPENAI_API_KEY",
    defaultModelId: "gpt-4.1",
    supportedModelIds: ["gpt-4.1"],
    capabilities: [createDefaultCapability("gpt-4.1")],
  },
];

export function ProviderSettings({ request }: ProviderSettingsProps): JSX.Element {
  const queryClient = useQueryClient();
  const providersQuery = useProvidersQuery({ request });
  const providers = providersQuery.data ?? [];
  const [isAddMenuOpen, setAddMenuOpen] = useState(false);
  const [openProviderIds, setOpenProviderIds] = useState<Record<string, boolean>>({});
  const visibleTemplateOptions = providerTemplates.filter(
    (template) =>
      !template.providerId ||
      !providers.some((provider) => provider.provider_id === template.providerId),
  );

  const addProviderMutation = useMutation<
    ProviderRead,
    ApiRequestError,
    ProviderTemplate
  >({
    mutationFn: (template) => {
      const body = providerTemplateToWriteRequest(template);
      return template.providerId
        ? patchProvider(template.providerId, body, request)
        : createProvider(body, request);
    },
    onSuccess: (provider) => {
      queryClient.setQueryData<ProviderRead[]>(apiQueryKeys.providers, (current) =>
        upsertProvider(current ?? [], provider),
      );
      setOpenProviderIds((current) => ({
        ...current,
        [provider.provider_id]: true,
      }));
      setAddMenuOpen(false);
    },
  });

  function addProvider(template: ProviderTemplate) {
    if (!template.providerId) {
      const draftProvider = providerTemplateToDraftProvider(template);
      queryClient.setQueryData<ProviderRead[]>(apiQueryKeys.providers, (current) =>
        upsertProvider(current ?? [], draftProvider),
      );
      setOpenProviderIds((current) => ({
        ...current,
        [draftProvider.provider_id]: true,
      }));
      setAddMenuOpen(false);
      return;
    }

    addProviderMutation.mutate(template);
  }

  function toggleDisclosure(providerId: string) {
    setOpenProviderIds((current) => ({
      ...current,
      [providerId]: !current[providerId],
    }));
  }

  return (
    <div className="settings-section">
      <div className="settings-section__heading">
        <h3>模型提供商</h3>
        <p>Provider changes apply to future runs and draft selection.</p>
      </div>
      <div className="provider-add">
        <button
          type="button"
          className="workspace-button"
          aria-expanded={isAddMenuOpen}
          onClick={() => setAddMenuOpen((current) => !current)}
        >
          Add custom provider
        </button>
        {isAddMenuOpen ? (
          <div className="provider-add__menu" role="menu">
            {visibleTemplateOptions.map((template) => (
              <button
                key={template.templateId}
                type="button"
                role="menuitem"
                disabled={addProviderMutation.isPending}
                onClick={() => addProvider(template)}
              >
                Add {template.displayName}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      {providersQuery.isLoading ? <p>Loading providers...</p> : null}
      {addProviderMutation.error ? (
        <p className="settings-form-error" role="alert">
          {addProviderMutation.error.message}
        </p>
      ) : null}
      {providers.length === 0 && !providersQuery.isLoading ? (
        <div className="settings-empty-state">
          <strong>No providers added</strong>
        </div>
      ) : null}
      <div className="provider-list">
        {providers.map((provider) => (
          <ProviderCard
            key={getProviderFormKey(provider)}
            provider={provider}
            request={request}
            isOpen={Boolean(openProviderIds[provider.provider_id])}
            onToggle={() => toggleDisclosure(provider.provider_id)}
            onSaved={(previousProviderId, updatedProvider) => {
              setOpenProviderIds((current) => {
                const next = { ...current };
                const wasOpen = Boolean(next[previousProviderId]);
                delete next[previousProviderId];
                next[updatedProvider.provider_id] =
                  wasOpen || Boolean(next[updatedProvider.provider_id]);
                return next;
              });
            }}
          />
        ))}
      </div>
    </div>
  );
}

function ProviderCard({
  provider,
  request,
  isOpen,
  onToggle,
  onSaved,
}: {
  provider: ProviderRead;
  request?: ApiRequestOptions;
  isOpen: boolean;
  onToggle: () => void;
  onSaved: (previousProviderId: string, updatedProvider: ProviderRead) => void;
}): JSX.Element {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => createProviderDraft(provider));
  const mutation = useMutation<ProviderRead, ApiRequestError, ProviderWriteRequest>({
    mutationFn: (body) => {
      if (provider.provider_id.startsWith("provider-custom-draft-")) {
        return createProvider(body, request);
      }
      return patchProvider(provider.provider_id, body, request);
    },
    onSuccess: (updatedProvider) => {
      queryClient.setQueryData<ProviderRead[]>(apiQueryKeys.providers, (current) =>
        replaceOrUpsertProvider(current ?? [], provider.provider_id, updatedProvider),
      );
      onSaved(provider.provider_id, updatedProvider);
    },
  });
  const modelIds = useMemo(
    () => parseModelList(draft.supportedModels),
    [draft.supportedModels],
  );

  useEffect(() => {
    setDraft(createProviderDraft(provider));
  }, [provider]);

  function updateDraft(next: Partial<ProviderDraft>) {
    setDraft((current) => ({ ...current, ...next }));
  }

  function saveProvider() {
    mutation.mutate(providerToWriteRequest(provider, draft));
  }

  return (
    <article
      className="provider-row"
      aria-label={provider.display_name}
      role="article"
    >
      <div className="provider-row__summary">
        <div>
          <h4>{provider.display_name}</h4>
          <p>{provider.default_model_id}</p>
        </div>
        <div className="provider-row__controls">
          <label className="provider-toggle">
            <input
              aria-label="Provider enabled"
              type="checkbox"
              checked={draft.isEnabled}
              onChange={(event) => updateDraft({ isEnabled: event.target.checked })}
            />
            <span>{draft.isEnabled ? "Enabled" : "Disabled"}</span>
          </label>
          <button
            type="button"
            className="workspace-button workspace-button--secondary"
            aria-expanded={isOpen}
            onClick={onToggle}
          >
            {isOpen ? "Collapse" : "Configure"}
          </button>
        </div>
      </div>
      {isOpen ? (
        <>
          <div className="settings-form-grid settings-form-grid--compact">
            <label>
              <span>Base URL</span>
              <input
                value={draft.baseUrl}
                onChange={(event) => updateDraft({ baseUrl: event.target.value })}
              />
            </label>
            <label>
              <span>API key</span>
              <input
                value={draft.apiKeyInput}
                onChange={(event) =>
                  updateDraft({
                    apiKeyInput: event.target.value,
                    apiKeyTouched: true,
                  })
                }
              />
            </label>
            <label>
              <span>Supported models</span>
              <input
                value={draft.supportedModels}
                onChange={(event) =>
                  updateDraft({ supportedModels: event.target.value })
                }
              />
            </label>
            <label>
              <span>Default model</span>
              <input
                list={`provider-models-${provider.provider_id}`}
                value={draft.defaultModel}
                onChange={(event) =>
                  updateDraft({ defaultModel: event.target.value })
                }
              />
              <datalist id={`provider-models-${provider.provider_id}`}>
                {modelIds.map((modelId) => (
                  <option key={modelId} value={modelId} />
                ))}
              </datalist>
            </label>
          </div>
          <div className="settings-actions">
            {mutation.error ? (
              <p className="settings-form-error" role="alert">
                {mutation.error.message}
              </p>
            ) : null}
            <button
              type="button"
              className="workspace-button"
              disabled={mutation.isPending}
              onClick={saveProvider}
            >
              Save provider
            </button>
          </div>
        </>
      ) : null}
    </article>
  );
}

function providerTemplateToWriteRequest(
  template: ProviderTemplate,
): ProviderWriteRequest {
  return {
    display_name: template.displayName,
    protocol_type: template.protocolType,
    base_url: template.baseUrl,
    api_key_ref: template.apiKeyRef,
    default_model_id: template.defaultModelId,
    supported_model_ids: template.supportedModelIds,
    is_enabled: true,
    runtime_capabilities: template.capabilities,
  };
}

function providerTemplateToDraftProvider(template: ProviderTemplate): ProviderRead {
  const timestamp = new Date(0).toISOString();
  return {
    provider_id: `provider-custom-draft-${template.templateId}`,
    display_name: template.displayName,
    provider_source: "custom",
    protocol_type: template.protocolType,
    base_url: template.baseUrl,
    api_key_ref: template.apiKeyRef,
    default_model_id: template.defaultModelId,
    supported_model_ids: template.supportedModelIds,
    is_enabled: true,
    runtime_capabilities: template.capabilities,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function providerToWriteRequest(
  provider: ProviderRead,
  draft: ProviderDraft,
): ProviderWriteRequest {
  const supportedModelIds = parseModelList(draft.supportedModels);
  const models =
    supportedModelIds.length > 0
      ? supportedModelIds
      : parseModelList(provider.supported_model_ids.join(", "));
  const defaultModel = draft.defaultModel.trim() || models[0] || provider.default_model_id;

  return {
    display_name: provider.display_name,
    protocol_type: provider.protocol_type,
    base_url: draft.baseUrl.trim(),
    api_key_ref: draft.apiKeyTouched
      ? draft.apiKeyInput.trim() || null
      : provider.api_key_ref,
    default_model_id: defaultModel,
    supported_model_ids: models,
    is_enabled: draft.isEnabled,
    runtime_capabilities: models.map((modelId) =>
      capabilityForModel(provider.runtime_capabilities, modelId),
    ),
  };
}

function createProviderDraft(provider: ProviderRead): ProviderDraft {
  return {
    baseUrl: provider.base_url,
    apiKeyInput: "",
    apiKeyTouched: false,
    supportedModels: provider.supported_model_ids.join(", "),
    defaultModel: provider.default_model_id,
    isEnabled: provider.is_enabled,
  };
}

function capabilityForModel(
  capabilities: ModelRuntimeCapabilities[],
  modelId: string,
): ModelRuntimeCapabilities {
  return (
    capabilities.find((capability) => capability.model_id === modelId) ??
    createDefaultCapability(modelId)
  );
}

function createDefaultCapability(
  modelId: string,
  overrides: Partial<ModelRuntimeCapabilities> = {},
): ModelRuntimeCapabilities {
  return {
    model_id: modelId,
    context_window_tokens: 128000,
    max_output_tokens: 4096,
    supports_tool_calling: false,
    supports_structured_output: false,
    supports_native_reasoning: false,
    ...overrides,
  };
}

function parseModelList(value: string): string[] {
  return value
    .split(",")
    .map((modelId) => modelId.trim())
    .filter(Boolean);
}

function upsertProvider(
  providers: ProviderRead[],
  nextProvider: ProviderRead,
): ProviderRead[] {
  const replaced = providers.map((provider) =>
    provider.provider_id === nextProvider.provider_id ? nextProvider : provider,
  );
  if (replaced.some((provider) => provider.provider_id === nextProvider.provider_id)) {
    return replaced;
  }
  return [...providers, nextProvider];
}

function replaceOrUpsertProvider(
  providers: ProviderRead[],
  previousProviderId: string,
  nextProvider: ProviderRead,
): ProviderRead[] {
  let inserted = false;
  const replaced: ProviderRead[] = [];

  for (const provider of providers) {
    const isPrevious = provider.provider_id === previousProviderId;
    const isNext = provider.provider_id === nextProvider.provider_id;
    if (isPrevious || isNext) {
      if (!inserted) {
        replaced.push(nextProvider);
        inserted = true;
      }
      continue;
    }

    replaced.push(provider);
  }

  if (!inserted) {
    replaced.push(nextProvider);
  }

  return replaced;
}

function getProviderFormKey(provider: ProviderRead): string {
  return [
    provider.provider_id,
    provider.updated_at,
    provider.base_url,
    provider.api_key_ref ?? "",
    provider.default_model_id,
    provider.supported_model_ids.join(","),
    String(provider.is_enabled),
    provider.runtime_capabilities
      .map((capability) =>
        [
          capability.model_id,
          capability.context_window_tokens,
          capability.max_output_tokens,
          String(capability.supports_tool_calling),
          String(capability.supports_structured_output),
          String(capability.supports_native_reasoning),
        ].join(":"),
      )
      .join("|"),
  ].join("::");
}
