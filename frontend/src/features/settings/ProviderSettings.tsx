import { useState } from "react";

import type { ApiRequestOptions } from "../../api/client";
import { useProvidersQuery } from "../../api/hooks";
import type { ProviderRead } from "../../api/types";

type ProviderSettingsProps = {
  request: ApiRequestOptions;
};

export function ProviderSettings({ request }: ProviderSettingsProps): JSX.Element {
  const providersQuery = useProvidersQuery({ request });
  const providers = providersQuery.data ?? [];
  const [openProviderIds, setOpenProviderIds] = useState<Record<string, boolean>>({});

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
      <div className="settings-actions settings-actions--start">
        <button type="button" className="workspace-button">
          Add custom provider
        </button>
      </div>
      <div className="provider-list">
        {providers.map((provider) => (
          <article className="provider-row" key={getProviderFormKey(provider)}>
            <div className="provider-row__summary">
              <div>
                <h4>{provider.display_name}</h4>
                {provider.provider_id === "provider-volcengine" ? (
                  <p>
                    {provider.provider_source} / {provider.protocol_type}
                  </p>
                ) : null}
                {provider.provider_id === "provider-volcengine" &&
                provider.api_key_ref ? (
                  <p>{provider.api_key_ref}</p>
                ) : null}
              </div>
              <span>{provider.default_model_id}</span>
            </div>
            <div className="settings-form-grid settings-form-grid--compact">
              <label>
                <span>Provider id</span>
                <input value={provider.provider_id} readOnly />
              </label>
              <label>
                <span>Provider source</span>
                <input value={provider.provider_source} readOnly />
              </label>
              <label>
                <span>Protocol type</span>
                <input value={provider.protocol_type} readOnly />
              </label>
              <label>
                <span>Base URL</span>
                <input defaultValue={provider.base_url} />
              </label>
              <label>
                <span>API key reference</span>
                <input defaultValue={provider.api_key_ref ?? ""} />
              </label>
              <label>
                <span>Supported models</span>
                <input defaultValue={provider.supported_model_ids.join(", ")} />
              </label>
              <label>
                <span>Default model</span>
                <input defaultValue={provider.default_model_id} />
              </label>
            </div>
            <details
              className="settings-disclosure"
              open={Boolean(openProviderIds[provider.provider_id])}
            >
              <summary
                onClick={(event) => {
                  event.preventDefault();
                  toggleDisclosure(provider.provider_id);
                }}
              >
                高级设置
              </summary>
              {openProviderIds[provider.provider_id] ? (
                <div className="capability-grid">
                  {provider.runtime_capabilities.map((capability) => (
                    <div className="capability-grid__fields" key={capability.model_id}>
                      <label>
                        <span>model_id</span>
                        <input defaultValue={capability.model_id} />
                      </label>
                      <label>
                        <span>context_window_tokens</span>
                        <input
                          defaultValue={capability.context_window_tokens}
                          inputMode="numeric"
                        />
                      </label>
                      <label>
                        <span>max_output_tokens</span>
                        <input
                          defaultValue={capability.max_output_tokens}
                          inputMode="numeric"
                        />
                      </label>
                      <label>
                        <span>supports_tool_calling</span>
                        <input
                          defaultChecked={capability.supports_tool_calling}
                          type="checkbox"
                        />
                      </label>
                      <label>
                        <span>supports_structured_output</span>
                        <input
                          defaultChecked={capability.supports_structured_output}
                          type="checkbox"
                        />
                      </label>
                      <label>
                        <span>supports_native_reasoning</span>
                        <input
                          defaultChecked={capability.supports_native_reasoning}
                          type="checkbox"
                        />
                      </label>
                    </div>
                  ))}
                </div>
              ) : null}
            </details>
          </article>
        ))}
      </div>
    </div>
  );
}

function getProviderFormKey(provider: ProviderRead): string {
  return [
    provider.provider_id,
    provider.updated_at,
    provider.base_url,
    provider.api_key_ref ?? "",
    provider.default_model_id,
    provider.supported_model_ids.join(","),
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
