"""What a job is, and the states it can be in.

A research call takes about nine seconds against a live model. Holding an HTTP
connection open for that is fine for a demo and wrong for anything else: it
couples the caller's timeout to the model's latency, it loses the work if the
client disconnects, and it gives the server no way to shed load beyond refusing
outright. Submitting the work and polling for it fixes all three.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    """Where a job is. Terminal states are `succeeded`, `failed` and `cancelled`."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}


@dataclass(frozen=True)
class Job:
    """One unit of work, and everything needed to retry or explain it."""

    id: str
    #: The request, as submitted. Kept whole so a retry re-runs the same thing
    #: rather than something reconstructed from partial state.
    payload: dict[str, Any]
    state: JobState = JobState.QUEUED
    attempts: int = 0
    max_attempts: int = 3
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    #: When a worker may claim this. Set into the future by a retry backoff.
    available_at: float = field(default_factory=time.time)
    #: When the current claim expires. A worker that dies leaves this behind,
    #: and the reaper uses it to put the job back.
    claim_expires_at: float | None = None
    claimed_by: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    error_kind: str | None = None
    #: Supplied by the caller. Two submissions with the same key are the same
    #: job; see `IdempotencyConflict` for the case where they are not.
    idempotency_key: str | None = None
    #: Fingerprint of the payload, so a reused key with a different body is
    #: caught rather than silently answered with the first request's result.
    request_hash: str | None = None

    @staticmethod
    def new(payload: dict[str, Any], **kwargs: Any) -> Job:
        return Job(id=uuid.uuid4().hex, payload=payload, **kwargs)

    def touched(self, **changes: Any) -> Job:
        return replace(self, updated_at=time.time(), **changes)

    @property
    def exhausted(self) -> bool:
        return self.attempts >= self.max_attempts

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": str(self.state),
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "available_at": self.available_at,
            "claim_expires_at": self.claim_expires_at,
            "claimed_by": self.claimed_by,
            "result": self.result,
            "error": self.error,
            "error_kind": self.error_kind,
            "idempotency_key": self.idempotency_key,
            "request_hash": self.request_hash,
            "payload": self.payload,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Job:
        return Job(
            id=data["id"],
            payload=data["payload"],
            state=JobState(data["state"]),
            attempts=data["attempts"],
            max_attempts=data["max_attempts"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            available_at=data["available_at"],
            claim_expires_at=data.get("claim_expires_at"),
            claimed_by=data.get("claimed_by"),
            result=data.get("result"),
            error=data.get("error"),
            error_kind=data.get("error_kind"),
            idempotency_key=data.get("idempotency_key"),
            request_hash=data.get("request_hash"),
        )


class IdempotencyConflict(Exception):
    """The key has been seen before, attached to a different request.

    Returning the first request's answer would be wrong -- the caller asked
    something else -- and running it as a new job would defeat the key. A 409
    is the only honest response.
    """

    def __init__(self, key: str, existing_job_id: str) -> None:
        super().__init__(
            f"idempotency key {key!r} was already used for job {existing_job_id} "
            "with a different request body"
        )
        self.key = key
        self.existing_job_id = existing_job_id
