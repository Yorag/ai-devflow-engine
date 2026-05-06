import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { ApiRequestError, ApiRequestOptions } from "../../api/client";
import { apiQueryKeys, useProvidersQuery } from "../../api/hooks";
import { createProvider, deleteProvider, patchProvider } from "../../api/providers";
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
  apiKeyRef: string | null;
  defaultModelId: string;
  supportedModelIds: string[];
  capabilities: ModelRuntimeCapabilities[];
};

type ProviderDraft = {
  displayName: string;
  baseUrl: string;
  apiKeyInput: string;
  apiKeyTouched: boolean;
  supportedModels: string;
  defaultModel: string;
  isEnabled: boolean;
  capabilities: Record<string, CapabilityDraft>;
};

type CapabilityDraft = {
  contextWindowTokens: string;
  maxOutputTokens: string;
  supportsToolCalling: boolean;
  supportsStructuredOutput: boolean;
  supportsNativeReasoning: boolean;
};

const MASKED_API_KEY_INPUT = "*************";

const providerTemplates: ProviderTemplate[] = [
  {
    templateId: "volcengine",
    providerId: "provider-volcengine",
    displayName: "火山引擎",
    protocolType: "volcengine_native",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    apiKeyRef: null,
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
    apiKeyRef: null,
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
    apiKeyRef: null,
    defaultModelId: "gpt-4.1",
    supportedModelIds: ["gpt-4.1"],
    capabilities: [
      createDefaultCapability("gpt-4.1", {
        supports_tool_calling: true,
        supports_structured_output: true,
      }),
    ],
  },
];

export function ProviderSettings({ request }: ProviderSettingsProps): JSX.Element {
  const queryClient = useQueryClient();
  const providersQuery = useProvidersQuery({ request });
  const providers = providersQuery.data ?? [];
  const [isAddMenuOpen, setAddMenuOpen] = useState(false);
  const [openProviderIds, setOpenProviderIds] = useState<Record<string, boolean>>({});

  const addProviderMutation = useMutation<
    ProviderRead,
    ApiRequestError,
    ProviderTemplate
  >({
    mutationFn: (template) => {
      const body = providerTemplateToWriteRequest(template);
      return template.providerId && !isTemplateBuiltInConfigured(template, providers)
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
    if (!template.providerId || isTemplateBuiltInConfigured(template, providers)) {
      const draftProvider = providerTemplateToDraftProvider(template, providers);
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
            {providerTemplates.map((template) => (
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
            onDeleted={(providerId) => {
              setOpenProviderIds((current) => {
                const next = { ...current };
                delete next[providerId];
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
  onDeleted,
}: {
  provider: ProviderRead;
  request?: ApiRequestOptions;
  isOpen: boolean;
  onToggle: () => void;
  onSaved: (previousProviderId: string, updatedProvider: ProviderRead) => void;
  onDeleted: (providerId: string) => void;
}): JSX.Element {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => createProviderDraft(provider));
  const [isEditingName, setEditingName] = useState(false);
  const mutation = useMutation<ProviderRead, ApiRequestError, ProviderWriteRequest>({
    mutationFn: (body) => {
      if (isDraftProvider(provider)) {
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
  const deleteMutation = useMutation<void, ApiRequestError, void>({
    mutationFn: () => {
      if (isDraftProvider(provider)) {
        return Promise.resolve();
      }
      return deleteProvider(provider.provider_id, request);
    },
    onSuccess: () => {
      queryClient.setQueryData<ProviderRead[]>(apiQueryKeys.providers, (current) =>
        (current ?? []).filter(
          (candidate) => candidate.provider_id !== provider.provider_id,
        ),
      );
      onDeleted(provider.provider_id);
    },
  });
  const modelIds = useMemo(
    () => parseModelList(draft.supportedModels),
    [draft.supportedModels],
  );
  const hasCollapsedSummaryChanges =
    !isOpen &&
    (draft.displayName.trim() !== provider.display_name ||
      draft.isEnabled !== provider.is_enabled);
  const visibleDisplayName = draft.displayName.trim() || provider.display_name;

  useEffect(() => {
    setDraft(createProviderDraft(provider));
  }, [provider]);

  function updateDraft(next: Partial<ProviderDraft>) {
    setDraft((current) => ({ ...current, ...next }));
  }

  function updateCapability(modelId: string, next: Partial<CapabilityDraft>) {
    setDraft((current) => ({
      ...current,
      capabilities: {
        ...current.capabilities,
        [modelId]: {
          ...createCapabilityDraft(capabilityForModel(provider.runtime_capabilities, modelId)),
          ...current.capabilities[modelId],
          ...next,
        },
      },
    }));
  }

  function saveProvider() {
    mutation.mutate(providerToWriteRequest(provider, draft));
  }

  function removeProvider() {
    deleteMutation.mutate();
  }

  function closeNameEditor() {
    setEditingName(false);
  }

  return (
    <article
      className="provider-row"
      aria-label={visibleDisplayName}
      role="article"
    >
      <div className="provider-row__summary">
        <div>
          {isEditingName ? (
            <input
              aria-label="Provider name"
              className="provider-name-input"
              value={draft.displayName}
              onBlur={closeNameEditor}
              onChange={(event) => updateDraft({ displayName: event.target.value })}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === "Escape") {
                  closeNameEditor();
                }
              }}
            />
          ) : (
            <button
              type="button"
              className="provider-name-button"
              onClick={() => setEditingName(true)}
            >
              {visibleDisplayName}
            </button>
          )}
          <p>{draft.defaultModel}</p>
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
          {hasCollapsedSummaryChanges ? (
            <button
              type="button"
              className="workspace-button"
              disabled={mutation.isPending || deleteMutation.isPending}
              onClick={saveProvider}
            >
              Save
            </button>
          ) : null}
          <button
            type="button"
            className="workspace-button workspace-button--danger"
            disabled={mutation.isPending || deleteMutation.isPending}
            onClick={removeProvider}
          >
            Delete
          </button>
        </div>
      </div>
      {!isOpen && (mutation.error || deleteMutation.error) ? (
        <p className="settings-form-error" role="alert">
          {(mutation.error ?? deleteMutation.error)?.message}
        </p>
      ) : null}
      {isOpen ? (
        <>
          <div className="settings-form-grid settings-form-grid--compact">
            <label>
              <span>Base URL</span>
              <input
                placeholder="https://api.example.com/v1"
                value={draft.baseUrl}
                onChange={(event) => updateDraft({ baseUrl: event.target.value })}
              />
            </label>
            <label>
              <span>API key</span>
              <input
                autoComplete="new-password"
                placeholder="sk-..."
                type="password"
                value={draft.apiKeyInput}
                onFocus={(event) => {
                  if (event.currentTarget.value === MASKED_API_KEY_INPUT) {
                    event.currentTarget.select();
                  }
                }}
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
                placeholder="model-a, model-b"
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
                placeholder="model-a"
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
          <details className="settings-disclosure">
            <summary>高级设置</summary>
            <div className="capability-grid">
              {modelIds.map((modelId) => {
                const capabilityDraft =
                  draft.capabilities[modelId] ??
                  createCapabilityDraft(
                    capabilityForModel(provider.runtime_capabilities, modelId),
                  );

                return (
                  <div
                    key={modelId}
                    className="capability-grid__group"
                    role="group"
                    aria-label={`Runtime capabilities for ${modelId}`}
                  >
                    <div className="capability-grid__header">
                      <span>Runtime capabilities</span>
                      <p>{modelId}</p>
                    </div>
                    <div className="capability-grid__number-fields">
                      <label>
                        <span>Context window</span>
                        <input
                          inputMode="numeric"
                          min="1"
                          type="number"
                          value={capabilityDraft.contextWindowTokens}
                          onChange={(event) =>
                            updateCapability(modelId, {
                              contextWindowTokens: event.target.value,
                            })
                          }
                        />
                      </label>
                      <label>
                        <span>Max output tokens</span>
                        <input
                          inputMode="numeric"
                          min="1"
                          type="number"
                          value={capabilityDraft.maxOutputTokens}
                          onChange={(event) =>
                            updateCapability(modelId, {
                              maxOutputTokens: event.target.value,
                            })
                          }
                        />
                      </label>
                    </div>
                    <div className="capability-toggle-row">
                      <label>
                        <input
                          checked={capabilityDraft.supportsToolCalling}
                          type="checkbox"
                          onChange={(event) =>
                            updateCapability(modelId, {
                              supportsToolCalling: event.target.checked,
                            })
                          }
                        />
                        <span>Tool calling</span>
                      </label>
                      <label>
                        <input
                          checked={capabilityDraft.supportsStructuredOutput}
                          type="checkbox"
                          onChange={(event) =>
                            updateCapability(modelId, {
                              supportsStructuredOutput: event.target.checked,
                            })
                          }
                        />
                        <span>Structured output</span>
                      </label>
                      <label>
                        <input
                          checked={capabilityDraft.supportsNativeReasoning}
                          type="checkbox"
                          onChange={(event) =>
                            updateCapability(modelId, {
                              supportsNativeReasoning: event.target.checked,
                            })
                          }
                        />
                        <span>Native reasoning</span>
                      </label>
                    </div>
                  </div>
                );
              })}
            </div>
          </details>
          <div className="settings-actions">
            {mutation.error || deleteMutation.error ? (
              <p className="settings-form-error" role="alert">
                {(mutation.error ?? deleteMutation.error)?.message}
              </p>
            ) : null}
            <button
              type="button"
              className="workspace-button"
              disabled={mutation.isPending || deleteMutation.isPending}
              onClick={saveProvider}
            >
              Save
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

function providerTemplateToDraftProvider(
  template: ProviderTemplate,
  providers: ProviderRead[],
): ProviderRead {
  const timestamp = new Date(0).toISOString();
  return {
    provider_id: `provider-custom-draft-${template.templateId}-${newDraftId()}`,
    display_name: nextProviderDisplayName(template.displayName, providers),
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
    display_name: draft.displayName.trim() || provider.display_name,
    protocol_type: provider.protocol_type,
    base_url: draft.baseUrl.trim(),
    api_key_ref: apiKeyRefForWrite(provider, draft),
    default_model_id: defaultModel,
    supported_model_ids: models,
    is_enabled: draft.isEnabled,
    runtime_capabilities: models.map((modelId) =>
      capabilityForModel(
        provider.runtime_capabilities,
        modelId,
        draft.capabilities[modelId],
      ),
    ),
  };
}

function createProviderDraft(provider: ProviderRead): ProviderDraft {
  return {
    displayName: provider.display_name,
    baseUrl: provider.base_url,
    apiKeyInput: provider.api_key_ref ? MASKED_API_KEY_INPUT : "",
    apiKeyTouched: false,
    supportedModels: provider.supported_model_ids.join(", "),
    defaultModel: provider.default_model_id,
    isEnabled: provider.is_enabled,
    capabilities: Object.fromEntries(
      provider.runtime_capabilities.map((capability) => [
        capability.model_id,
        createCapabilityDraft(capability),
      ]),
    ),
  };
}

function apiKeyRefForWrite(
  provider: ProviderRead,
  draft: ProviderDraft,
): string | null {
  if (!draft.apiKeyTouched || draft.apiKeyInput === MASKED_API_KEY_INPUT) {
    return provider.api_key_ref;
  }
  return draft.apiKeyInput.trim() || null;
}

function capabilityForModel(
  capabilities: ModelRuntimeCapabilities[],
  modelId: string,
  draft?: CapabilityDraft,
): ModelRuntimeCapabilities {
  const source =
    capabilities.find((capability) => capability.model_id === modelId) ??
    createDefaultCapability(modelId);

  if (!draft) {
    return source;
  }

  return {
    model_id: modelId,
    context_window_tokens: parsePositiveInt(
      draft.contextWindowTokens,
      source.context_window_tokens,
    ),
    max_output_tokens: parsePositiveInt(
      draft.maxOutputTokens,
      source.max_output_tokens,
    ),
    supports_tool_calling: draft.supportsToolCalling,
    supports_structured_output: draft.supportsStructuredOutput,
    supports_native_reasoning: draft.supportsNativeReasoning,
  };
}

function createCapabilityDraft(
  capability: ModelRuntimeCapabilities,
): CapabilityDraft {
  return {
    contextWindowTokens: String(capability.context_window_tokens),
    maxOutputTokens: String(capability.max_output_tokens),
    supportsToolCalling: capability.supports_tool_calling,
    supportsStructuredOutput: capability.supports_structured_output,
    supportsNativeReasoning: capability.supports_native_reasoning,
  };
}

function createDefaultCapability(
  modelId: string,
  overrides: Partial<ModelRuntimeCapabilities> = {},
): ModelRuntimeCapabilities {
  return {
    model_id: modelId,
    context_window_tokens: 128000,
    max_output_tokens: 4096,
    supports_tool_calling: true,
    supports_structured_output: true,
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

function parsePositiveInt(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function isTemplateBuiltInConfigured(
  template: ProviderTemplate,
  providers: ProviderRead[],
): boolean {
  return Boolean(
    template.providerId &&
      providers.some((provider) => provider.provider_id === template.providerId),
  );
}

function nextProviderDisplayName(baseName: string, providers: ProviderRead[]): string {
  const usedNames = new Set(providers.map((provider) => provider.display_name));
  if (!usedNames.has(baseName)) {
    return baseName;
  }

  let index = 2;
  while (usedNames.has(`${baseName} ${index}`)) {
    index += 1;
  }
  return `${baseName} ${index}`;
}

function newDraftId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isDraftProvider(provider: ProviderRead): boolean {
  return provider.provider_id.startsWith("provider-custom-draft-");
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
    provider.display_name,
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
