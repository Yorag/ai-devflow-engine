from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.app.schemas.observability import RedactionStatus


SENSITIVE_FIELD_PLACEHOLDER = "[blocked:sensitive_field]"
SENSITIVE_TEXT_PLACEHOLDER = "[blocked:sensitive_text_pattern]"
UNSERIALIZABLE_PLACEHOLDER = "[blocked:payload_unserializable]"
TRUNCATED_SUFFIX = "...[truncated]"


@dataclass(frozen=True)
class RedactedPayload:
    summary: dict[str, Any]
    excerpt: str
    redacted_payload: Any | None
    payload_size_bytes: int
    content_hash: str
    redaction_status: RedactionStatus


@dataclass(frozen=True)
class _SanitizedPayload:
    payload: Any
    blocked_fields: list[str]
    truncated_fields: list[str]
    sensitive_text_detected: bool = False


class RedactionPolicy:
    _safe_field_names = {
        "api_key_ref",
        "apikeyref",
        "credential_ref",
        "credentialref",
        "credential_status",
        "credentialstatus",
    }
    _sensitive_field_names = {
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "auth_header",
        "authheader",
        "auth_token",
        "bearer_token",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "id_token",
        "password",
        "private_key",
        "privatekey",
        "refresh_token",
        "secret",
        "token",
    }
    _sensitive_field_tokens = {
        "authorization",
        "cookie",
        "credential",
        "key",
        "password",
        "secret",
        "token",
    }
    _sensitive_text_patterns = (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
        re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]*", re.IGNORECASE),
    )

    def __init__(self, max_text_length: int = 4096, excerpt_length: int = 512) -> None:
        if max_text_length < 1:
            raise ValueError("max_text_length must be at least 1")
        if excerpt_length < 1:
            raise ValueError("excerpt_length must be at least 1")
        self.max_text_length = max_text_length
        self.excerpt_length = excerpt_length

    def redact_mapping(self, payload: Mapping[str, Any]) -> RedactedPayload:
        return self.summarize_payload(payload)

    def summarize_payload(
        self,
        payload: Any,
        *,
        payload_type: str | None = None,
    ) -> RedactedPayload:
        try:
            serialized_input = self._serialize(payload)
        except (TypeError, ValueError):
            return self._blocked_result(
                placeholder=UNSERIALIZABLE_PLACEHOLDER,
                status=RedactionStatus.UNSERIALIZABLE,
                payload_type=payload_type,
                blocked_reason="payload_unserializable",
                input_type=type(payload).__name__,
            )

        if isinstance(payload, str):
            return self.summarize_text(payload, payload_type=payload_type)

        sanitized = self._sanitize(payload, path="")
        if sanitized.sensitive_text_detected:
            return self._blocked_result(
                placeholder=SENSITIVE_TEXT_PLACEHOLDER,
                status=RedactionStatus.BLOCKED,
                payload_type=payload_type,
                blocked_reason="sensitive_text_pattern",
                input_type=type(payload).__name__,
            )

        serialized_sanitized = self._serialize(sanitized.payload)
        summary = self._summary(
            payload_type=payload_type,
            blocked_fields=sanitized.blocked_fields,
            truncated_fields=sanitized.truncated_fields,
        )
        status = (
            RedactionStatus.REDACTED
            if sanitized.blocked_fields or sanitized.truncated_fields
            else RedactionStatus.NOT_REQUIRED
        )
        return RedactedPayload(
            summary=summary,
            excerpt=self._excerpt(serialized_sanitized),
            redacted_payload=sanitized.payload,
            payload_size_bytes=self._byte_length(serialized_input),
            content_hash=self._content_hash(serialized_sanitized),
            redaction_status=status,
        )

    def summarize_text(
        self,
        text: str,
        *,
        payload_type: str | None = None,
    ) -> RedactedPayload:
        if self._contains_sensitive_text(text):
            return self._blocked_result(
                placeholder=SENSITIVE_TEXT_PLACEHOLDER,
                status=RedactionStatus.BLOCKED,
                payload_type=payload_type,
                blocked_reason="sensitive_text_pattern",
                input_type="str",
            )

        redacted_text = self._truncate_text(text)
        serialized_input = self._serialize(text)
        serialized_sanitized = self._serialize(redacted_text)
        summary = self._summary(
            payload_type=payload_type,
            blocked_fields=[],
            truncated_fields=[""] if redacted_text != text else [],
        )
        return RedactedPayload(
            summary=summary,
            excerpt=self._excerpt(serialized_sanitized),
            redacted_payload=redacted_text,
            payload_size_bytes=self._byte_length(serialized_input),
            content_hash=self._content_hash(serialized_sanitized),
            redaction_status=(
                RedactionStatus.REDACTED
                if redacted_text != text
                else RedactionStatus.NOT_REQUIRED
            ),
        )

    def _sanitize(self, value: Any, *, path: str) -> _SanitizedPayload:
        if isinstance(value, Mapping):
            sanitized_mapping: dict[str, Any] = {}
            blocked_fields: list[str] = []
            truncated_fields: list[str] = []
            sensitive_text_detected = False
            for key, child in value.items():
                key_path = self._child_path(path, str(key))
                if self._is_sensitive_field(str(key)):
                    sanitized_mapping[key] = SENSITIVE_FIELD_PLACEHOLDER
                    blocked_fields.append(key_path)
                    continue

                sanitized = self._sanitize(child, path=key_path)
                sanitized_mapping[key] = sanitized.payload
                blocked_fields.extend(sanitized.blocked_fields)
                truncated_fields.extend(sanitized.truncated_fields)
                sensitive_text_detected = (
                    sensitive_text_detected or sanitized.sensitive_text_detected
                )
            return _SanitizedPayload(
                payload=sanitized_mapping,
                blocked_fields=blocked_fields,
                truncated_fields=truncated_fields,
                sensitive_text_detected=sensitive_text_detected,
            )

        if isinstance(value, list):
            sanitized_items: list[Any] = []
            blocked_fields: list[str] = []
            truncated_fields: list[str] = []
            sensitive_text_detected = False
            for index, child in enumerate(value):
                sanitized = self._sanitize(child, path=f"{path}[{index}]")
                sanitized_items.append(sanitized.payload)
                blocked_fields.extend(sanitized.blocked_fields)
                truncated_fields.extend(sanitized.truncated_fields)
                sensitive_text_detected = (
                    sensitive_text_detected or sanitized.sensitive_text_detected
                )
            return _SanitizedPayload(
                payload=sanitized_items,
                blocked_fields=blocked_fields,
                truncated_fields=truncated_fields,
                sensitive_text_detected=sensitive_text_detected,
            )

        if isinstance(value, tuple):
            sanitized_tuple = self._sanitize(list(value), path=path)
            return _SanitizedPayload(
                payload=sanitized_tuple.payload,
                blocked_fields=sanitized_tuple.blocked_fields,
                truncated_fields=sanitized_tuple.truncated_fields,
                sensitive_text_detected=sanitized_tuple.sensitive_text_detected,
            )

        if isinstance(value, str):
            if self._contains_sensitive_text(value):
                return _SanitizedPayload(
                    payload=None,
                    blocked_fields=[],
                    truncated_fields=[],
                    sensitive_text_detected=True,
                )
            truncated = self._truncate_text(value)
            return _SanitizedPayload(
                payload=truncated,
                blocked_fields=[],
                truncated_fields=[path] if truncated != value else [],
            )

        return _SanitizedPayload(payload=value, blocked_fields=[], truncated_fields=[])

    def _blocked_result(
        self,
        *,
        placeholder: str,
        status: RedactionStatus,
        payload_type: str | None,
        blocked_reason: str,
        input_type: str,
    ) -> RedactedPayload:
        summary = self._blocked_summary(
            payload_type=payload_type,
            blocked_reason=blocked_reason,
            input_type=input_type,
        )
        hash_input = self._serialize(
            {
                "blocked_reason": blocked_reason,
                "input_type": input_type,
                "payload_type": payload_type,
                "placeholder": placeholder,
            }
        )
        return RedactedPayload(
            summary=summary,
            excerpt=placeholder,
            redacted_payload=None,
            payload_size_bytes=self._byte_length(hash_input),
            content_hash=self._content_hash(hash_input),
            redaction_status=status,
        )

    def _summary(
        self,
        *,
        payload_type: str | None,
        blocked_fields: list[str],
        truncated_fields: list[str],
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        if payload_type is not None:
            summary["payload_type"] = payload_type
        summary["blocked_fields"] = blocked_fields
        summary["truncated_fields"] = truncated_fields
        return summary

    def _blocked_summary(
        self,
        *,
        payload_type: str | None,
        blocked_reason: str,
        input_type: str,
    ) -> dict[str, str]:
        summary = {
            "blocked_reason": blocked_reason,
            "input_type": input_type,
        }
        if payload_type is not None:
            return {"payload_type": payload_type, **summary}
        return summary

    def _is_sensitive_field(self, field_name: str) -> bool:
        camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", field_name)
        normalized = re.sub(r"[^a-z0-9]+", "_", camel_split.lower()).strip("_")
        compact = normalized.replace("_", "")
        if normalized in self._safe_field_names or compact in self._safe_field_names:
            return False
        if normalized in self._sensitive_field_names or compact in self._sensitive_field_names:
            return True
        tokens = normalized.split("_")
        return any(token in self._sensitive_field_tokens for token in tokens)

    def _contains_sensitive_text(self, text: str) -> bool:
        return any(pattern.search(text) is not None for pattern in self._sensitive_text_patterns)

    def _truncate_text(self, text: str) -> str:
        if len(text) <= self.max_text_length:
            return text
        if self.max_text_length <= len(TRUNCATED_SUFFIX):
            return TRUNCATED_SUFFIX[: self.max_text_length]
        prefix_length = self.max_text_length - len(TRUNCATED_SUFFIX)
        return f"{text[:prefix_length]}{TRUNCATED_SUFFIX}"

    def _excerpt(self, serialized_payload: str) -> str:
        if len(serialized_payload) <= self.excerpt_length:
            return serialized_payload
        if self.excerpt_length <= len(TRUNCATED_SUFFIX):
            return TRUNCATED_SUFFIX[: self.excerpt_length]
        prefix_length = self.excerpt_length - len(TRUNCATED_SUFFIX)
        return f"{serialized_payload[:prefix_length]}{TRUNCATED_SUFFIX}"

    def _serialize(self, payload: Any) -> str:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _content_hash(self, serialized_payload: str) -> str:
        digest = hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _byte_length(self, serialized_payload: str) -> int:
        return len(serialized_payload.encode("utf-8"))

    def _child_path(self, parent: str, child: str) -> str:
        if not parent:
            return child
        return f"{parent}.{child}"


__all__ = ["RedactedPayload", "RedactionPolicy"]
