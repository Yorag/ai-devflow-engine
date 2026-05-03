from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from backend.app.prompts.definitions import (
    AGENT_ROLE_SEED_PROMPT_IDS,
    PROMPT_ASSET_ROOT,
    REQUIRED_BUILTIN_PROMPT_IDS,
    applies_to_stage_types_for_prompt_id,
    expected_source_ref,
)
from backend.app.schemas.prompts import (
    ModelCallType,
    PromptAssetRead,
    PromptAuthorityLevel,
    PromptCacheScope,
    PromptSectionRead,
    PromptType,
    PromptVersionRef,
)


PromptAsset = PromptAssetRead


class PromptAssetMetadataError(ValueError):
    def __init__(self, message: str, *, asset_path: Path | None = None) -> None:
        self.asset_path = asset_path
        super().__init__(message)


class PromptAssetNotFoundError(LookupError):
    def __init__(self, prompt_id: str, prompt_version: str | None = None) -> None:
        self.prompt_id = prompt_id
        self.prompt_version = prompt_version
        suffix = f" version {prompt_version}" if prompt_version else ""
        super().__init__(f"Prompt asset not found: {prompt_id}{suffix}")


@dataclass(frozen=True, slots=True)
class _ParsedFrontMatter:
    metadata: dict[str, str]
    body: str


class PromptRegistry:
    def __init__(self, prompt_assets: list[PromptAsset]) -> None:
        self._by_id: dict[str, dict[str, PromptAsset]] = {}
        self._by_type: dict[PromptType, list[PromptAsset]] = {}
        for asset in prompt_assets:
            self._by_id.setdefault(asset.prompt_id, {})[asset.prompt_version] = asset
            self._by_type.setdefault(asset.prompt_type, []).append(asset)
        for prompt_type, assets in self._by_type.items():
            self._by_type[prompt_type] = sorted(
                assets,
                key=lambda asset: (asset.prompt_id, asset.prompt_version),
            )

    @classmethod
    def load_builtin_assets(cls, asset_root: Path | None = None) -> PromptRegistry:
        root = asset_root or PROMPT_ASSET_ROOT
        prompt_assets: list[PromptAsset] = []
        seen_id_versions: set[tuple[str, str]] = set()
        for asset_path in sorted(root.rglob("*.md")):
            asset = cls._load_asset_file(asset_path, asset_root=root)
            key = (asset.prompt_id, asset.prompt_version)
            if key in seen_id_versions:
                raise PromptAssetMetadataError(
                    f"duplicate prompt asset identity: {asset.prompt_id} {asset.prompt_version}",
                    asset_path=asset_path,
                )
            seen_id_versions.add(key)
            prompt_assets.append(asset)

        registry = cls(prompt_assets)
        missing = REQUIRED_BUILTIN_PROMPT_IDS - set(registry._by_id)
        if missing:
            raise PromptAssetMetadataError(
                f"missing required builtin prompt assets: {sorted(missing)}",
                asset_path=None,
            )
        return registry

    def get(self, prompt_id: str, prompt_version: str | None = None) -> PromptAsset:
        versions = self._by_id.get(prompt_id)
        if not versions:
            raise PromptAssetNotFoundError(prompt_id, prompt_version)
        if prompt_version is None:
            prompt_version = max(versions, key=self._version_sort_key)
        asset = versions.get(prompt_version)
        if asset is None:
            raise PromptAssetNotFoundError(prompt_id, prompt_version)
        return asset

    def list_by_type(self, prompt_type: PromptType) -> list[PromptAsset]:
        return list(self._by_type.get(prompt_type, []))

    def resolve_version_ref(self, ref: PromptVersionRef) -> PromptAsset:
        asset = self.get(ref.prompt_id, ref.prompt_version)
        mismatches: list[str] = []
        if asset.prompt_type is not ref.prompt_type:
            mismatches.append("prompt_type")
        if asset.authority_level is not ref.authority_level:
            mismatches.append("authority_level")
        if asset.cache_scope is not ref.cache_scope:
            mismatches.append("cache_scope")
        if asset.source_ref != ref.source_ref:
            mismatches.append("source_ref")
        if asset.content_hash != ref.content_hash:
            mismatches.append("content_hash")
        if mismatches:
            raise PromptAssetMetadataError(
                f"PromptVersionRef mismatch for {ref.prompt_id}: {', '.join(mismatches)}",
                asset_path=None,
            )
        return asset

    @staticmethod
    def compute_content_hash(content: str) -> str:
        return PromptAssetRead.calculate_content_hash(content)

    @classmethod
    def _load_asset_file(cls, asset_path: Path, *, asset_root: Path) -> PromptAsset:
        markdown = asset_path.read_text(encoding="utf-8")
        parsed = cls._parse_front_matter(markdown, asset_path=asset_path)
        metadata = parsed.metadata
        body = parsed.body
        expected_ref = expected_source_ref(asset_root, asset_path)
        prompt_id = metadata.get("prompt_id")
        if "source_ref" not in metadata and prompt_id not in AGENT_ROLE_SEED_PROMPT_IDS:
            raise PromptAssetMetadataError(
                "prompt asset front matter is missing keys: ['source_ref']",
                asset_path=asset_path,
            )
        if metadata.get("source_ref", expected_ref) != expected_ref:
            raise PromptAssetMetadataError(
                f"source_ref does not match asset path for {asset_path.name}",
                asset_path=asset_path,
            )

        normalized = cls._normalize_metadata(metadata, expected_ref=expected_ref)
        prompt_id = normalized["prompt_id"]
        title = cls._derive_title(prompt_id=prompt_id, body=body, metadata=metadata)
        try:
            return PromptAssetRead(
                prompt_id=prompt_id,
                prompt_version=normalized["prompt_version"],
                prompt_type=normalized["prompt_type"],
                authority_level=normalized["authority_level"],
                model_call_type=normalized["model_call_type"],
                cache_scope=normalized["cache_scope"],
                source_ref=normalized["source_ref"],
                content_hash=cls.compute_content_hash(markdown),
                sections=[
                    PromptSectionRead(
                        section_id=metadata.get("role_id", prompt_id),
                        title=title,
                        body=body,
                        cache_scope=normalized["cache_scope"],
                    )
                ],
                applies_to_stage_types=list(
                    applies_to_stage_types_for_prompt_id(prompt_id)
                ),
            )
        except ValidationError as exc:
            raise PromptAssetMetadataError(
                f"invalid prompt asset metadata: {exc}",
                asset_path=asset_path,
            ) from exc

    @staticmethod
    def _normalize_metadata(
        metadata: dict[str, str],
        *,
        expected_ref: str,
    ) -> dict[str, str]:
        if "prompt_id" not in metadata or "prompt_version" not in metadata:
            missing = sorted({"prompt_id", "prompt_version"} - set(metadata))
            raise PromptAssetMetadataError(
                f"prompt asset front matter is missing keys: {missing}",
                asset_path=None,
            )

        prompt_id = metadata["prompt_id"]
        normalized = dict(metadata)
        normalized["source_ref"] = metadata.get("source_ref", expected_ref)
        if prompt_id in AGENT_ROLE_SEED_PROMPT_IDS:
            normalized.setdefault("prompt_type", PromptType.AGENT_ROLE_SEED.value)
            normalized.setdefault(
                "authority_level",
                PromptAuthorityLevel.AGENT_ROLE_PROMPT.value,
            )
            normalized.setdefault("model_call_type", ModelCallType.STAGE_EXECUTION.value)
            normalized.setdefault("cache_scope", PromptCacheScope.GLOBAL_STATIC.value)

        required_keys = {
            "prompt_id",
            "prompt_version",
            "prompt_type",
            "authority_level",
            "model_call_type",
            "cache_scope",
            "source_ref",
        }
        missing = sorted(required_keys - set(normalized))
        if missing:
            raise PromptAssetMetadataError(
                f"prompt asset front matter is missing keys: {missing}",
                asset_path=None,
            )
        return normalized

    @staticmethod
    def _derive_title(
        *,
        prompt_id: str,
        body: str,
        metadata: dict[str, str],
    ) -> str:
        if "role_name" in metadata:
            return metadata["role_name"]
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:]
        return prompt_id

    @staticmethod
    def _parse_front_matter(markdown: str, *, asset_path: Path) -> _ParsedFrontMatter:
        normalized = markdown.replace("\r\n", "\n")
        if not normalized.startswith("---\n"):
            raise PromptAssetMetadataError(
                "prompt asset is missing YAML front matter",
                asset_path=asset_path,
            )
        closing_index = normalized.find("\n---\n", len("---\n"))
        if closing_index == -1:
            raise PromptAssetMetadataError(
                "prompt asset front matter is not closed",
                asset_path=asset_path,
            )
        front_matter = normalized[len("---\n") : closing_index]
        body = normalized[closing_index + len("\n---\n") :].strip()
        metadata: dict[str, str] = {}
        for raw_line in front_matter.splitlines():
            if not raw_line.strip():
                continue
            key, separator, value = raw_line.partition(":")
            if separator != ":":
                raise PromptAssetMetadataError(
                    f"invalid front matter line: {raw_line}",
                    asset_path=asset_path,
                )
            metadata[key.strip()] = value.strip().strip('"')
        return _ParsedFrontMatter(metadata=metadata, body=body)

    @staticmethod
    def _version_sort_key(prompt_version: str) -> tuple[int, ...]:
        try:
            date_part, sequence_part = prompt_version.rsplit(".", 1)
            year, month, day = (int(part) for part in date_part.split("-"))
            return (year, month, day, int(sequence_part))
        except ValueError as exc:
            raise PromptAssetMetadataError(
                f"invalid prompt_version format: {prompt_version}",
                asset_path=None,
            ) from exc
