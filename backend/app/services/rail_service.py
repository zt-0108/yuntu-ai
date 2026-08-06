from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import logging
from threading import Lock
from time import monotonic
from typing import Any

from app import config
from app.models.schemas import RailTicketOption, RailTicketPlan, TripRequest
from app.services.rail_mcp_client import query_rail_routes


logger = logging.getLogger(__name__)

_cache: dict[tuple[Any, ...], tuple[float, RailTicketPlan]] = {}
_cache_lock = Lock()

_SEAT_NAMES = {
    "business": "商务座",
    "business_seat": "商务座",
    "first_class": "一等座",
    "second_class": "二等座",
    "soft_sleeper": "软卧",
    "hard_sleeper": "硬卧",
    "hard_seat": "硬座",
    "no_seat": "无座",
}
_PERIODS = {"上午": (5 * 60, 12 * 60), "下午": (12 * 60, 18 * 60), "晚上": (18 * 60, 24 * 60)}


def clear_rail_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cache_key(request: TripRequest) -> tuple[Any, ...]:
    return (
        request.departure_city,
        request.destination,
        request.start_date.isoformat(),
        request.end_date.isoformat(),
        request.preferred_departure_period,
        tuple(request.preferred_train_types),
        request.seat_preference,
    )


def _extract_list(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    current: Any = payload
    if isinstance(current.get("data"), dict):
        current = current["data"]
    for key in keys:
        value = current.get(key) if isinstance(current, dict) else None
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if isinstance(current, dict) and isinstance(current.get("data"), list):
        return [item for item in current["data"] if isinstance(item, dict)]
    return []


def _clock_minutes(value: str) -> int | None:
    try:
        hours, minutes = value.split(":", 1)
        return int(hours) * 60 + int(minutes)
    except (AttributeError, TypeError, ValueError):
        return None


def _duration_minutes(value: str) -> int | None:
    text = str(value or "").strip()
    if ":" in text:
        return _clock_minutes(text)
    return None


def _price_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return max(float(value), 0.0)
    text = str(value or "").replace("¥", "").replace("￥", "").strip()
    try:
        return max(float(text), 0.0)
    except ValueError:
        return None


def _normalize_seats(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    seats: dict[str, str] = {}
    for key, value in raw.items():
        name = _SEAT_NAMES.get(str(key), str(key))
        text = str(value).strip() if value is not None else ""
        if name and text:
            seats[name] = text
    return seats


def _normalize_prices(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    prices: dict[str, float] = {}
    for key, value in raw.items():
        number = _price_number(value)
        if number is not None:
            prices[_SEAT_NAMES.get(str(key), str(key))] = number
    return prices


def _train_code(item: dict[str, Any]) -> str:
    return str(
        item.get("station_train_code")
        or item.get("train_code")
        or item.get("train_no")
        or ""
    ).strip()


def _matches_preferences(item: dict[str, Any], request: TripRequest) -> bool:
    code = _train_code(item).upper()
    if request.preferred_train_types and not any(code.startswith(kind) for kind in request.preferred_train_types):
        return False
    if request.preferred_departure_period:
        minutes = _clock_minutes(str(item.get("start_time") or ""))
        start, end = _PERIODS[request.preferred_departure_period]
        if minutes is None or not start <= minutes < end:
            return False
    return True


def _normalize_options(
    response: dict[str, Any],
    *,
    travel_date: date,
    request: TripRequest,
) -> list[RailTicketOption]:
    trains = _extract_list(response.get("tickets", {}), "trains", "tickets")
    price_items = _extract_list(response.get("prices", {}), "prices", "trains")
    prices_by_train: dict[str, dict[str, float]] = {}
    for item in price_items:
        normalized = _normalize_prices(item.get("prices"))
        for raw_code in (
            item.get("station_train_code"),
            item.get("train_code"),
            item.get("train_no"),
        ):
            code = str(raw_code or "").strip()
            if code:
                prices_by_train[code] = normalized

    options: list[RailTicketOption] = []
    for item in trains:
        if not _matches_preferences(item, request):
            continue
        code = _train_code(item)
        if not code:
            continue
        seats = _normalize_seats(item.get("seats"))
        prices = prices_by_train.get(code, {})
        preferred = request.seat_preference
        options.append(
            RailTicketOption(
                train_code=code,
                travel_date=travel_date,
                departure_station=str(item.get("from_station") or request.departure_city or ""),
                arrival_station=str(item.get("to_station") or request.destination),
                departure_time=str(item.get("start_time") or "--:--"),
                arrival_time=str(item.get("arrive_time") or "--:--"),
                duration=str(item.get("duration") or "未知"),
                duration_minutes=_duration_minutes(str(item.get("duration") or "")),
                seats=seats,
                prices=prices,
                preferred_seat=preferred,
                preferred_seat_availability=seats.get(preferred) if preferred else None,
                preferred_seat_price=prices.get(preferred) if preferred else None,
            )
        )
    options.sort(key=lambda option: (option.departure_time, option.duration_minutes or 10_000))
    return options[: config.RAIL_MCP_MAX_RESULTS]


def query_round_trip_tickets(request: TripRequest) -> RailTicketPlan:
    if not request.departure_city:
        return RailTicketPlan(status="disabled", message="填写出发城市后可查询往返车次。")
    if not config.ENABLE_RAIL_MCP:
        return RailTicketPlan(
            status="disabled",
            departure_city=request.departure_city,
            destination=request.destination,
            message="铁路查询服务尚未启用。",
        )

    key = _cache_key(request)
    now = monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1].model_copy(deep=True)

    routes = [
        {"from_station": request.departure_city, "to_station": request.destination, "train_date": request.start_date.isoformat()},
        {"from_station": request.destination, "to_station": request.departure_city, "train_date": request.end_date.isoformat()},
    ]
    try:
        responses = asyncio.run(
            query_rail_routes(
                url=config.RAIL_MCP_URL,
                timeout_seconds=config.RAIL_MCP_TIMEOUT_SECONDS,
                routes=routes,
            )
        )
        outbound = _normalize_options(responses[0], travel_date=request.start_date, request=request)
        return_trip = _normalize_options(responses[1], travel_date=request.end_date, request=request)
        status = "available" if outbound or return_trip else "unavailable"
        plan = RailTicketPlan(
            status=status,
            departure_city=request.departure_city,
            destination=request.destination,
            outbound=outbound,
            return_trip=return_trip,
            queried_at=datetime.now(timezone.utc),
            message=None if status == "available" else "没有找到符合当前偏好的候选车次，可放宽筛选条件后重试。",
        )
    except Exception as exc:
        logger.warning("rail_mcp_query_failed route=%s-%s error=%s", request.departure_city, request.destination, exc)
        plan = RailTicketPlan(
            status="error",
            departure_city=request.departure_city,
            destination=request.destination,
            queried_at=datetime.now(timezone.utc),
            message="铁路查询暂时不可用，原行程已正常生成。",
        )

    with _cache_lock:
        if len(_cache) >= 128:
            oldest_key = min(_cache, key=lambda item: _cache[item][0])
            _cache.pop(oldest_key, None)
        _cache[key] = (now + config.RAIL_MCP_CACHE_TTL_SECONDS, plan.model_copy(deep=True))
    return plan
