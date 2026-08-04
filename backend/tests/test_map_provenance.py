from __future__ import annotations

from app.services import map_service
from app.services.trip_service import generate_trip_itinerary
from tests.test_services_trip import build_trip_request


def test_map_enrichment_records_partial_spot_verification(monkeypatch) -> None:
    itinerary = generate_trip_itinerary(build_trip_request())
    verified_names = {itinerary.days[0].spots[0].name, itinerary.days[1].spots[0].name}

    monkeypatch.setattr(
        map_service,
        "_enrich_spot",
        lambda spot, city=None: spot.name in verified_names,
    )
    monkeypatch.setattr(map_service, "_enrich_hotel", lambda hotel, city=None: False)
    monkeypatch.setattr(map_service, "_enrich_transport", lambda transport, city=None: False)

    result = map_service.enrich_itinerary_with_map_data(itinerary, city="大理")

    assert result.provenance.map_status == "partial"
    assert result.provenance.map_verified_spots == 2
    assert result.provenance.map_total_spots == 6


def test_map_enrichment_marks_all_spots_verified(monkeypatch) -> None:
    itinerary = generate_trip_itinerary(build_trip_request())
    monkeypatch.setattr(map_service, "_enrich_spot", lambda spot, city=None: True)
    monkeypatch.setattr(map_service, "_enrich_hotel", lambda hotel, city=None: False)
    monkeypatch.setattr(map_service, "_enrich_transport", lambda transport, city=None: False)

    result = map_service.enrich_itinerary_with_map_data(itinerary, city="大理")

    assert result.provenance.map_status == "verified"
    assert result.provenance.map_verified_spots == result.provenance.map_total_spots == 6
