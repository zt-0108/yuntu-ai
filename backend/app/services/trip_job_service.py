from __future__ import annotations

import logging
from hashlib import sha256
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import uuid4

from app.models.schemas import (
    TripGenerationJobCreated,
    TripGenerationJobStatus,
    TripRequest,
)
from app.services.trip_service import TripGenerationCancelled, generate_trip_itinerary


logger = logging.getLogger(__name__)
_jobs: dict[str, TripGenerationJobStatus] = {}
_job_fingerprints: dict[str, str] = {}
_jobs_lock = Lock()
_completed_job_ttl = timedelta(hours=1)
_max_jobs = 100


def _now() -> datetime:
    return datetime.now(UTC)


def _cleanup_jobs_locked(now: datetime) -> None:
    expired_ids = [
        job_id
        for job_id, job in _jobs.items()
        if job.status in {"cancelled", "completed", "failed"}
        and now - job.updated_at > _completed_job_ttl
    ]
    for job_id in expired_ids:
        _jobs.pop(job_id, None)
        _job_fingerprints.pop(job_id, None)

    if len(_jobs) <= _max_jobs:
        return

    oldest_finished_jobs = sorted(
        (
            job
            for job in _jobs.values()
            if job.status in {"cancelled", "completed", "failed"}
        ),
        key=lambda job: job.updated_at,
    )
    for job in oldest_finished_jobs:
        if len(_jobs) <= _max_jobs:
            break
        _jobs.pop(job.job_id, None)
        _job_fingerprints.pop(job.job_id, None)


def _request_fingerprint(request: TripRequest) -> str:
    return sha256(request.model_dump_json().encode("utf-8")).hexdigest()


def create_trip_generation_job(
    request: TripRequest,
) -> tuple[TripGenerationJobCreated, bool]:
    now = _now()
    fingerprint = _request_fingerprint(request)
    job_id = uuid4().hex
    job = TripGenerationJobStatus(
        job_id=job_id,
        status="queued",
        stage="queued",
        progress=0,
        created_at=now,
        updated_at=now,
    )
    with _jobs_lock:
        _cleanup_jobs_locked(now)
        for existing_job_id, existing_job in _jobs.items():
            if (
                _job_fingerprints.get(existing_job_id) == fingerprint
                and existing_job.status in {"queued", "running"}
            ):
                return (
                    TripGenerationJobCreated(
                        job_id=existing_job_id,
                        status=existing_job.status,
                        reused=True,
                    ),
                    False,
                )
        _jobs[job_id] = job
        _job_fingerprints[job_id] = fingerprint
    return TripGenerationJobCreated(job_id=job_id), True


def get_trip_generation_job(job_id: str) -> TripGenerationJobStatus | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return job.model_copy(deep=True) if job is not None else None


def _update_job(job_id: str, **changes) -> None:
    with _jobs_lock:
        current = _jobs.get(job_id)
        if current is None:
            return
        _jobs[job_id] = current.model_copy(
            update={**changes, "updated_at": _now()},
            deep=True,
        )


def cancel_trip_generation_job(job_id: str) -> TripGenerationJobStatus | None:
    with _jobs_lock:
        current = _jobs.get(job_id)
        if current is None:
            return None
        if current.status == "queued":
            current = current.model_copy(
                update={
                    "status": "cancelled",
                    "stage": "cancelled",
                    "updated_at": _now(),
                },
                deep=True,
            )
            _jobs[job_id] = current
        elif current.status == "running":
            current = current.model_copy(
                update={
                    "status": "cancelling",
                    "stage": "cancelling",
                    "updated_at": _now(),
                },
                deep=True,
            )
            _jobs[job_id] = current
        return current.model_copy(deep=True)


def run_trip_generation_job(job_id: str, request: TripRequest) -> None:
    """Run one generation task in FastAPI's background thread pool."""
    current = get_trip_generation_job(job_id)
    if current is None or current.status == "cancelled":
        return
    _update_job(job_id, status="running", stage="preparing", progress=5)

    def report_progress(stage: str, progress: int) -> None:
        current_job = get_trip_generation_job(job_id)
        if current_job is None or current_job.status in {"cancelling", "cancelled"}:
            raise TripGenerationCancelled()
        _update_job(
            job_id,
            status="running",
            stage=stage,
            progress=max(0, min(progress, 99)),
        )

    try:
        itinerary = generate_trip_itinerary(request, progress_callback=report_progress)
    except TripGenerationCancelled:
        _update_job(
            job_id,
            status="cancelled",
            stage="cancelled",
            error_message=None,
        )
        logger.info("trip_job_cancelled job_id=%s", job_id)
        return
    except Exception as exc:
        logger.exception(
            "trip_job_failed job_id=%s error_type=%s",
            job_id,
            type(exc).__name__,
        )
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            progress=100,
            error_message="行程生成失败，请稍后重试。",
        )
        return

    current = get_trip_generation_job(job_id)
    if current is None or current.status in {"cancelling", "cancelled"}:
        _update_job(job_id, status="cancelled", stage="cancelled")
        logger.info("trip_job_cancelled job_id=%s", job_id)
        return

    _update_job(
        job_id,
        status="completed",
        stage="completed",
        progress=100,
        itinerary=itinerary,
    )
    logger.info("trip_job_completed job_id=%s trip_id=%s", job_id, itinerary.trip_id)
