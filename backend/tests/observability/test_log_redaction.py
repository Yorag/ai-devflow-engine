from __future__ import annotations

from backend.app.schemas.observability import RedactionStatus


def test_l62_redaction_blocks_sensitive_assignment_patterns_in_command_output() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy(max_text_length=256, excerpt_length=256)

    result = policy.summarize_payload(
        {
            "command": "uv run pytest",
            "stdout": "ok\nTOKEN=raw-token-value\npassword=raw-password-value\n",
            "stderr": "api_key=raw-api-key-value",
        },
        payload_type="command_output",
    )

    assert result.redaction_status is RedactionStatus.BLOCKED
    assert result.redacted_payload is None
    assert result.excerpt == "[blocked:sensitive_text_pattern]"
    assert result.summary == {
        "payload_type": "command_output",
        "blocked_reason": "sensitive_text_pattern",
        "input_type": "dict",
    }
    dumped = str(result.summary) + result.excerpt + result.content_hash
    assert "raw-token-value" not in dumped
    assert "raw-password-value" not in dumped
    assert "raw-api-key-value" not in dumped


def test_l62_redaction_blocks_common_env_var_secret_assignment_names() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy(max_text_length=512, excerpt_length=512)

    result = policy.summarize_payload(
        {
            "stdout": (
                "OPENAI_API_KEY=raw-openai-key\n"
                "GITHUB_TOKEN=raw-github-token\n"
                "DATABASE_PASSWORD=raw-db-password\n"
                "AWS_SECRET_ACCESS_KEY=raw-aws-secret-key\n"
            )
        },
        payload_type="command_output",
    )

    assert result.redaction_status is RedactionStatus.BLOCKED
    assert result.redacted_payload is None
    assert result.excerpt == "[blocked:sensitive_text_pattern]"
    dumped = str(result.summary) + result.excerpt + result.content_hash
    assert "raw-openai-key" not in dumped
    assert "raw-github-token" not in dumped
    assert "raw-db-password" not in dumped
    assert "raw-aws-secret-key" not in dumped


def test_l62_redaction_blocks_provider_tool_and_exception_secret_shapes() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy(max_text_length=512, excerpt_length=512)
    payloads = [
        (
            "model_input",
            {"messages": [{"role": "user", "content": "use secret=my-model-secret"}]},
        ),
        (
            "model_output",
            {"text": "temporary key ghp_1234567890abcdef should not be logged"},
        ),
        (
            "tool_input",
            {"arguments": {"headers": "Cookie: session=raw-cookie-value"}},
        ),
        (
            "tool_output",
            {"stdout": "AWS key AKIA1234567890ABCDEF reached stdout"},
        ),
        (
            "exception_stack",
            {
                "traceback": (
                    "Traceback (most recent call last):\n"
                    "RuntimeError: password=raw-stack-password"
                )
            },
        ),
    ]

    for payload_type, payload in payloads:
        result = policy.summarize_payload(payload, payload_type=payload_type)

        assert result.redaction_status is RedactionStatus.BLOCKED
        assert result.redacted_payload is None
        assert result.excerpt == "[blocked:sensitive_text_pattern]"
        assert result.summary["payload_type"] == payload_type
        dumped = str(result.summary) + result.excerpt + result.content_hash
        assert "raw-" not in dumped
        assert "ghp_1234567890abcdef" not in dumped
        assert "AKIA1234567890ABCDEF" not in dumped


def test_l62_redaction_keeps_safe_reference_names_and_usage_metrics() -> None:
    from backend.app.observability.redaction import RedactionPolicy

    policy = RedactionPolicy(max_text_length=256, excerpt_length=256)

    result = policy.summarize_payload(
        {
            "api_key_ref": "env:OPENAI_API_KEY",
            "credential_ref": "env:GITHUB_TOKEN",
            "token_count": 128,
            "token_usage": {
                "input_tokens": 14,
                "output_tokens": 9,
                "total_tokens": 23,
            },
            "max_output_tokens": 4096,
            "context": "api_key_ref=env:OPENAI_API_KEY token_count=128",
        },
        payload_type="model_call_trace",
    )

    assert result.redaction_status is RedactionStatus.NOT_REQUIRED
    assert result.redacted_payload["api_key_ref"] == "env:OPENAI_API_KEY"
    assert result.redacted_payload["credential_ref"] == "env:GITHUB_TOKEN"
    assert result.redacted_payload["token_count"] == 128
    assert result.redacted_payload["token_usage"] == {
        "input_tokens": 14,
        "output_tokens": 9,
        "total_tokens": 23,
    }
    assert result.redacted_payload["max_output_tokens"] == 4096
    assert "api_key_ref=env:OPENAI_API_KEY" in result.excerpt
