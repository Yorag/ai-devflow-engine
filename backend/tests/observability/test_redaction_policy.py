from __future__ import annotations

from backend.app.schemas.observability import RedactionStatus


class NonJsonSerializable:
    def __repr__(self) -> str:
        return "NonJsonSerializable(secret='must-not-leak')"


def test_redact_mapping_blocks_sensitive_field_values_and_preserves_safe_refs() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy(max_text_length=32)

    result = policy.redact_mapping(
        {
            "api_key": "sk-live-secret",
            "credential_ref": "env:GITHUB_TOKEN",
            "credential_status": "ready",
            "nested": {
                "Authorization": "Bearer raw-token",
                "safe": "visible",
            },
            "items": [
                {
                    "cookie": "session=secret",
                    "count": 2,
                }
            ],
        }
    )

    assert result.redaction_status is RedactionStatus.REDACTED
    assert result.redacted_payload["api_key"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["credential_ref"] == "env:GITHUB_TOKEN"
    assert result.redacted_payload["credential_status"] == "ready"
    assert result.redacted_payload["nested"]["Authorization"] == (
        "[blocked:sensitive_field]"
    )
    assert result.redacted_payload["nested"]["safe"] == "visible"
    assert result.redacted_payload["items"][0]["cookie"] == (
        "[blocked:sensitive_field]"
    )
    assert result.summary["blocked_fields"] == [
        "api_key",
        "nested.Authorization",
        "items[0].cookie",
    ]
    assert result.summary["truncated_fields"] == []
    assert result.content_hash.startswith("sha256:")
    assert "sk-live-secret" not in result.excerpt
    assert "Bearer raw-token" not in result.excerpt
    assert "session=secret" not in result.excerpt


def test_redact_mapping_blocks_equivalent_sensitive_field_names() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy(max_text_length=64)
    raw_values = [
        "raw-credential-value",
        "raw-access-token",
        "raw-refresh-token",
        "raw-cookie-header",
        "raw-authorization-header",
        "raw-private-key",
        "raw-db-password",
        "raw-nested-db-password",
        "raw-list-authorization-header",
    ]

    result = policy.redact_mapping(
        {
            "credential_value": raw_values[0],
            "access_token": raw_values[1],
            "refresh_token": raw_values[2],
            "cookie_header": raw_values[3],
            "authorization_header": raw_values[4],
            "private-key": raw_values[5],
            "db_password": raw_values[6],
            "credential_ref": "env:GITHUB_TOKEN",
            "credential_status": "ready",
            "nested": {
                "db_password": raw_values[7],
            },
            "items": [
                {
                    "authorization_header": raw_values[8],
                }
            ],
        }
    )

    assert result.redaction_status is RedactionStatus.REDACTED
    assert result.redacted_payload["credential_value"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["access_token"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["refresh_token"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["cookie_header"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["authorization_header"] == (
        "[blocked:sensitive_field]"
    )
    assert result.redacted_payload["private-key"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["db_password"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["credential_ref"] == "env:GITHUB_TOKEN"
    assert result.redacted_payload["credential_status"] == "ready"
    assert result.redacted_payload["nested"]["db_password"] == (
        "[blocked:sensitive_field]"
    )
    assert result.redacted_payload["items"][0]["authorization_header"] == (
        "[blocked:sensitive_field]"
    )
    assert result.summary["blocked_fields"] == [
        "credential_value",
        "access_token",
        "refresh_token",
        "cookie_header",
        "authorization_header",
        "private-key",
        "db_password",
        "nested.db_password",
        "items[0].authorization_header",
    ]
    for raw_value in raw_values:
        assert raw_value not in result.excerpt


def test_redact_mapping_blocks_camel_case_equivalent_sensitive_field_names() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy(max_text_length=64)
    raw_values = {
        "authorizationHeader": "raw-camel-authorization-header",
        "cookieHeader": "raw-camel-cookie-header",
        "dbPassword": "raw-camel-db-password",
        "credentialValue": "raw-camel-credential-value",
        "accessToken": "raw-camel-access-token",
        "refreshToken": "raw-camel-refresh-token",
        "clientSecret": "raw-camel-client-secret",
        "authToken": "raw-camel-auth-token",
        "idToken": "raw-camel-id-token",
        "nested.authorizationHeader": "raw-nested-camel-authorization-header",
        "items[0].cookieHeader": "raw-list-camel-cookie-header",
    }

    result = policy.redact_mapping(
        {
            "authorizationHeader": raw_values["authorizationHeader"],
            "cookieHeader": raw_values["cookieHeader"],
            "dbPassword": raw_values["dbPassword"],
            "credentialValue": raw_values["credentialValue"],
            "accessToken": raw_values["accessToken"],
            "refreshToken": raw_values["refreshToken"],
            "clientSecret": raw_values["clientSecret"],
            "authToken": raw_values["authToken"],
            "idToken": raw_values["idToken"],
            "credentialRef": "env:GITHUB_TOKEN",
            "credentialStatus": "ready",
            "nested": {
                "authorizationHeader": raw_values["nested.authorizationHeader"],
            },
            "items": [
                {
                    "cookieHeader": raw_values["items[0].cookieHeader"],
                }
            ],
        }
    )

    assert result.redaction_status is RedactionStatus.REDACTED
    assert result.redacted_payload["authorizationHeader"] == (
        "[blocked:sensitive_field]"
    )
    assert result.redacted_payload["cookieHeader"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["dbPassword"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["credentialValue"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["accessToken"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["refreshToken"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["clientSecret"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["authToken"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["idToken"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["credentialRef"] == "env:GITHUB_TOKEN"
    assert result.redacted_payload["credentialStatus"] == "ready"
    assert result.redacted_payload["nested"]["authorizationHeader"] == (
        "[blocked:sensitive_field]"
    )
    assert result.redacted_payload["items"][0]["cookieHeader"] == (
        "[blocked:sensitive_field]"
    )
    assert result.summary["blocked_fields"] == [
        "authorizationHeader",
        "cookieHeader",
        "dbPassword",
        "credentialValue",
        "accessToken",
        "refreshToken",
        "clientSecret",
        "authToken",
        "idToken",
        "nested.authorizationHeader",
        "items[0].cookieHeader",
    ]
    for raw_value in raw_values.values():
        assert raw_value not in result.excerpt


def test_redact_mapping_blocks_auth_header_equivalent_field_names() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy(max_text_length=64)
    raw_values = [
        "raw-auth-header",
        "raw-camel-auth-header",
        "raw-nested-auth-header",
        "raw-list-auth-header",
    ]

    result = policy.redact_mapping(
        {
            "auth_header": raw_values[0],
            "authHeader": raw_values[1],
            "nested": {
                "auth_header": raw_values[2],
            },
            "items": [
                {
                    "authHeader": raw_values[3],
                }
            ],
        }
    )

    assert result.redaction_status is RedactionStatus.REDACTED
    assert result.redacted_payload["auth_header"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["authHeader"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["nested"]["auth_header"] == (
        "[blocked:sensitive_field]"
    )
    assert result.redacted_payload["items"][0]["authHeader"] == (
        "[blocked:sensitive_field]"
    )
    assert result.summary["blocked_fields"] == [
        "auth_header",
        "authHeader",
        "nested.auth_header",
        "items[0].authHeader",
    ]
    for raw_value in raw_values:
        assert raw_value not in result.excerpt


def test_redact_mapping_blocks_provider_api_key_fields_but_preserves_delivery_refs() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy(max_text_length=64)

    result = policy.redact_mapping(
        {
            "api_key_ref": "sk-provider-secret",
            "apiKeyRef": "provider-secret-value",
            "credential_ref": "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
            "api_key": "raw-api-key",
            "apiKey": "raw-camel-api-key",
        }
    )

    assert result.redaction_status is RedactionStatus.REDACTED
    assert result.redacted_payload["api_key_ref"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["apiKeyRef"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["credential_ref"] == (
        "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN"
    )
    assert result.redacted_payload["api_key"] == "[blocked:sensitive_field]"
    assert result.redacted_payload["apiKey"] == "[blocked:sensitive_field]"
    assert result.summary["blocked_fields"] == [
        "api_key_ref",
        "apiKeyRef",
        "api_key",
        "apiKey",
    ]
    for forbidden in [
        "sk-provider-secret",
        "provider-secret-value",
        "raw-api-key",
        "raw-camel-api-key",
    ]:
        assert forbidden not in result.excerpt


def test_summarize_payload_bounds_large_text_before_log_or_audit_storage() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy(max_text_length=20, excerpt_length=120)
    long_output = "pytest output line " * 20

    result = policy.summarize_payload(
        {
            "command": "uv run pytest",
            "output": long_output,
        },
        payload_type="command_output",
    )

    assert result.redaction_status is RedactionStatus.REDACTED
    assert result.redacted_payload["command"] == "uv run pytest"
    assert result.redacted_payload["output"].endswith("...[truncated]")
    assert result.redacted_payload["output"].startswith("pytest")
    assert len(result.redacted_payload["output"]) == 20
    assert result.summary["payload_type"] == "command_output"
    assert result.summary["truncated_fields"] == ["output"]
    assert result.summary["blocked_fields"] == []
    assert result.payload_size_bytes > len(result.excerpt)
    assert long_output not in result.excerpt
    assert result.content_hash.startswith("sha256:")


def test_summarize_text_blocks_secret_patterns_without_echoing_secret_text() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy()
    private_key_output = (
        "build failed\n"
        "-----BEGIN PRIVATE KEY-----\n"
        "raw-private-key-material\n"
        "-----END PRIVATE KEY-----"
    )

    result = policy.summarize_text(private_key_output, payload_type="command_output")

    assert result.redaction_status is RedactionStatus.BLOCKED
    assert result.redacted_payload is None
    assert result.excerpt == "[blocked:sensitive_text_pattern]"
    assert result.summary == {
        "payload_type": "command_output",
        "blocked_reason": "sensitive_text_pattern",
        "input_type": "str",
    }
    assert "PRIVATE KEY" not in result.content_hash
    assert "raw-private-key-material" not in result.excerpt


def test_summarize_payload_marks_unserializable_payload_without_repr_leakage() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy()

    result = policy.summarize_payload(
        {"safe": "visible", "bad": NonJsonSerializable()},
        payload_type="model_response",
    )

    assert result.redaction_status is RedactionStatus.UNSERIALIZABLE
    assert result.redacted_payload is None
    assert result.excerpt == "[blocked:payload_unserializable]"
    assert result.summary == {
        "payload_type": "model_response",
        "blocked_reason": "payload_unserializable",
        "input_type": "dict",
    }
    assert "must-not-leak" not in str(result.summary)
    assert "must-not-leak" not in result.excerpt
    assert result.content_hash.startswith("sha256:")


def test_redaction_policy_has_no_log_file_or_audit_write_side_effects(tmp_path) -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy()
    result = policy.summarize_payload({"message": "visible"}, payload_type="api")

    assert result.redaction_status is RedactionStatus.NOT_REQUIRED
    assert result.redacted_payload == {"message": "visible"}
    assert list(tmp_path.iterdir()) == []
    assert not hasattr(policy, "record_audit")
    assert not hasattr(policy, "write_jsonl")
