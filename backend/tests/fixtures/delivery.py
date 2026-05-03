from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.app.db.models.runtime import DeliveryChannelSnapshotModel
from backend.app.domain.enums import (
    CodeReviewRequestType,
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
    ScmProviderType,
)


FIXTURE_NOW = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)


def delivery_channel_snapshot_fixture(
    *,
    delivery_channel_snapshot_id: str = "delivery-channel-snapshot-1",
    run_id: str = "run-1",
    source_delivery_channel_id: str = "project-default-channel",
    delivery_mode: DeliveryMode = DeliveryMode.GIT_AUTO_DELIVERY,
    scm_provider_type: ScmProviderType | None = ScmProviderType.GITHUB,
    repository_identifier: str | None = "acme/app",
    default_branch: str | None = "main",
    code_review_request_type: CodeReviewRequestType | None = (
        CodeReviewRequestType.PULL_REQUEST
    ),
    credential_ref: str | None = "env:AI_DEVFLOW_CREDENTIAL_DELIVERY_TOKEN",
    credential_status: CredentialStatus = CredentialStatus.READY,
    readiness_status: DeliveryReadinessStatus = DeliveryReadinessStatus.READY,
    readiness_message: str | None = "git_auto_delivery is ready.",
    last_validated_at: datetime | None = None,
    schema_version: str = "delivery-channel-snapshot-v1",
    created_at: datetime | None = None,
    ) -> DeliveryChannelSnapshotModel:
    return DeliveryChannelSnapshotModel(
        delivery_channel_snapshot_id=delivery_channel_snapshot_id,
        run_id=run_id,
        source_delivery_channel_id=source_delivery_channel_id,
        delivery_mode=delivery_mode,
        scm_provider_type=scm_provider_type,
        repository_identifier=repository_identifier,
        default_branch=default_branch,
        code_review_request_type=code_review_request_type,
        credential_ref=credential_ref,
        credential_status=credential_status,
        readiness_status=readiness_status,
        readiness_message=readiness_message,
        last_validated_at=last_validated_at,
        schema_version=schema_version,
        created_at=created_at or FIXTURE_NOW,
    )


def missing_delivery_snapshot_fixture() -> None:
    return None


@dataclass
class MockRemoteDeliveryClient:
    fail_next: bool = False
    requests: list[dict[str, object]] = field(default_factory=list)

    def create_pull_request(
        self,
        *,
        repository_identifier: str,
        source_branch: str,
        target_branch: str,
        title: str,
        body: str,
    ) -> dict[str, object]:
        payload = {
            "request_type": "pull_request",
            "repository_identifier": repository_identifier,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "body": body,
        }
        self.requests.append(payload)
        self._raise_if_requested()
        return {
            "url": f"https://example.test/{repository_identifier}/pull/1",
            "number": 1,
            "request_type": "pull_request",
            "repository_identifier": repository_identifier,
            "source_branch": source_branch,
            "target_branch": target_branch,
        }

    def create_merge_request(
        self,
        *,
        repository_identifier: str,
        source_branch: str,
        target_branch: str,
        title: str,
        body: str,
    ) -> dict[str, object]:
        payload = {
            "request_type": "merge_request",
            "repository_identifier": repository_identifier,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "body": body,
        }
        self.requests.append(payload)
        self._raise_if_requested()
        return {
            "url": f"https://example.test/{repository_identifier}/merge_requests/1",
            "number": 1,
            "request_type": "merge_request",
            "repository_identifier": repository_identifier,
            "source_branch": source_branch,
            "target_branch": target_branch,
        }

    def send_delivery(self, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(dict(request))
        self._raise_if_requested()
        return {"status": "accepted", "request_index": len(self.requests)}

    def _raise_if_requested(self) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("mock remote request failed")


def mock_remote_delivery_client(*, fail_next: bool = False) -> MockRemoteDeliveryClient:
    return MockRemoteDeliveryClient(fail_next=fail_next)
