from __future__ import annotations

from datetime import date

from app.models.schemas import TripRequest
from app.services import rail_service


def _request(**overrides) -> TripRequest:
    values = {
        "destination": "苏州",
        "departure_city": "上海",
        "start_date": date(2026, 9, 10),
        "end_date": date(2026, 9, 12),
        "travelers": 2,
        "budget": 3000,
        "preferred_departure_period": "上午",
        "preferred_train_types": ["G"],
        "seat_preference": "二等座",
    }
    values.update(overrides)
    return TripRequest(**values)


def test_rail_query_is_disabled_without_departure_city() -> None:
    plan = rail_service.query_round_trip_tickets(_request(departure_city=None))

    assert plan.status == "disabled"
    assert plan.outbound == []


def test_rail_query_normalizes_filters_and_limits(monkeypatch) -> None:
    rail_service.clear_rail_cache()
    monkeypatch.setattr(rail_service.config, "ENABLE_RAIL_MCP", True)
    monkeypatch.setattr(rail_service.config, "RAIL_MCP_MAX_RESULTS", 2)

    async def fake_query_rail_routes(**kwargs):
        assert len(kwargs["routes"]) == 2
        route_payload = {
            "tickets": {
                "success": True,
                "trains": [
                    {
                        "train_no": "G7012",
                        "from_station": "上海",
                        "to_station": "苏州",
                        "start_time": "09:10",
                        "arrive_time": "09:42",
                        "duration": "00:32",
                        "seats": {"second_class": "有", "first_class": "5"},
                    },
                    {
                        "train_no": "K999",
                        "from_station": "上海",
                        "to_station": "苏州",
                        "start_time": "10:00",
                        "arrive_time": "11:30",
                        "duration": "01:30",
                        "seats": {"hard_seat": "有"},
                    },
                ],
            },
            "prices": {
                "data": [
                    {"train_code": "G7012", "prices": {"二等座": "39.5", "一等座": "62.0"}},
                ]
            },
        }
        return [route_payload, route_payload]

    monkeypatch.setattr(rail_service, "query_rail_routes", fake_query_rail_routes)
    plan = rail_service.query_round_trip_tickets(_request())

    assert plan.status == "available"
    assert [item.train_code for item in plan.outbound] == ["G7012"]
    assert plan.outbound[0].preferred_seat_availability == "有"
    assert plan.outbound[0].preferred_seat_price == 39.5
    assert plan.return_trip[0].travel_date == date(2026, 9, 12)


def test_rail_query_failure_does_not_raise(monkeypatch) -> None:
    rail_service.clear_rail_cache()
    monkeypatch.setattr(rail_service.config, "ENABLE_RAIL_MCP", True)

    async def failing_query(**kwargs):
        raise TimeoutError("slow service")

    monkeypatch.setattr(rail_service, "query_rail_routes", failing_query)
    plan = rail_service.query_round_trip_tickets(_request())

    assert plan.status == "error"
    assert "正常生成" in (plan.message or "")
