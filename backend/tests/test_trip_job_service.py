from __future__ import annotations

from datetime import date

import app.services.trip_job_service as trip_job_service
from app.models.schemas import TripRequest


def build_trip_request() -> TripRequest:
    return TripRequest(
        destination="大理",
        start_date="2026-04-10",
        end_date="2026-04-12",
        travelers=2,
        budget=3200,
        preferences=["自然风景", "拍照"],
        pace="轻松",
    )


def test_trip_job_reports_failure_without_exposing_exception(monkeypatch) -> None:
    request = build_trip_request()
    job, should_start = trip_job_service.create_trip_generation_job(request)
    assert should_start is True

    def fail_generation(request, progress_callback=None):
        raise RuntimeError("private-provider-error")

    monkeypatch.setattr(
        trip_job_service,
        "generate_trip_itinerary",
        fail_generation,
    )

    trip_job_service.run_trip_generation_job(job.job_id, request)
    failed_job = trip_job_service.get_trip_generation_job(job.job_id)

    assert failed_job is not None
    assert failed_job.status == "failed"
    assert failed_job.progress == 100
    assert failed_job.error_message == "行程生成失败，请稍后重试。"
    assert "private-provider-error" not in failed_job.error_message


def test_duplicate_active_request_reuses_existing_job() -> None:
    request = build_trip_request().model_copy(update={"start_date": date(2026, 5, 1)})

    first, first_should_start = trip_job_service.create_trip_generation_job(request)
    second, second_should_start = trip_job_service.create_trip_generation_job(request)

    assert first_should_start is True
    assert second_should_start is False
    assert second.reused is True
    assert second.job_id == first.job_id

    trip_job_service.cancel_trip_generation_job(first.job_id)


def test_queued_job_can_be_cancelled_before_start() -> None:
    request = build_trip_request().model_copy(update={"start_date": date(2026, 6, 1)})
    job, _ = trip_job_service.create_trip_generation_job(request)

    cancelled = trip_job_service.cancel_trip_generation_job(job.job_id)
    trip_job_service.run_trip_generation_job(job.job_id, request)
    stored = trip_job_service.get_trip_generation_job(job.job_id)

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert stored is not None
    assert stored.status == "cancelled"
