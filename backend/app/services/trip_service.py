from __future__ import annotations

from datetime import date as DateType, timedelta
import logging
from time import perf_counter
from typing import Callable

from app.agents.trip_planner_agent import (
    collect_trip_context,
    generate_day_edit_draft,
    generate_planner_draft,
)
from app.config import ENABLE_AMAP_ENRICHMENT
from app.models.schemas import (
    BudgetBreakdown,
    DayPlan,
    HotelItem,
    Itinerary,
    ItineraryProvenance,
    MealItem,
    SpotItem,
    TokenUsage,
    TransportItem,
    TripEditRequest,
    TripRequest,
)
from app.services.map_service import enrich_itinerary_with_map_data


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str, int], None]


class TripGenerationCancelled(Exception):
    """Raised by a progress callback to stop generation between stages."""


def _report_progress(
    progress_callback: ProgressCallback | None,
    stage: str,
    progress: int,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(stage, progress)
    except TripGenerationCancelled:
        raise
    except Exception:
        logger.exception("trip_progress_callback_failed stage=%s", stage)


TECHNICAL_TIP_KEYWORDS = (
    "LLM",
    "RAG",
    "LangChain",
    "Chroma",
    "演示",
    "测试",
    "规则",
    "模型",
    "源码",
    "trip_service",
)

# 多景点时给每个景点排一个粗略时间段，超出就留空
_SPOT_TIME_SLOTS = [
    ("09:30", "11:30"),
    ("14:00", "16:00"),
    ("16:30", "18:00"),
]


def _clean_user_tips(tips: list[str], destination: str | None = None) -> list[str]:
    """过滤内部实现说明，只保留用户真正能用到的旅行建议。"""
    cleaned_tips: list[str] = []
    for tip in tips:
        normalized_tip = tip.strip()
        if not normalized_tip:
            continue
        if any(keyword in normalized_tip for keyword in TECHNICAL_TIP_KEYWORDS):
            continue
        if normalized_tip not in cleaned_tips:
            cleaned_tips.append(normalized_tip)

    if cleaned_tips:
        return cleaned_tips

    place_text = destination or "目的地"
    return [
        f"建议根据{place_text}当天实时天气准备雨具或薄外套，早晚和临水区域体感可能偏凉。",
        "当天如果步行游览较多，建议选择舒适防滑的鞋子，并根据体力灵活调整停留时间。",
        "热门景点建议错峰出发，给拍照、用餐和交通预留更从容的缓冲时间。",
    ]


def _spots_per_day(pace: str | None) -> int:
    """按节奏决定每天安排几个景点。"""
    return 3 if pace == "紧凑" else 2


def _build_demo_spot_pool(destination: str, rag_contexts: list[str], needed: int) -> list[str]:
    """从攻略片段里凑出 needed 个演示景点名（LLM 不可用时的兜底）。"""
    joined_context = "\n".join(rag_contexts)
    candidates: list[str] = []
    for name in ("大理古城", "喜洲古镇", "崇圣寺三塔", "洱海生态廊道", "双廊古镇"):
        if name in joined_context and name not in candidates:
            candidates.append(name)
    while len(candidates) < needed:
        candidates.append(f"{destination} 推荐景点 {len(candidates) + 1}")
    return candidates[:needed]


def _stable_bucket(text: str, modulo: int) -> int:
    """基于文本生成一个稳定桶值，用来做确定性的价格浮动。"""
    return sum(ord(char) for char in text) % modulo if modulo > 0 else 0


def _prorate_amounts(total: float, weights: list[float]) -> list[float]:
    """按权重拆分金额，同时保证拆分后的总和与原总额一致。"""
    if not weights:
        return []

    safe_weights = [max(weight, 0.01) for weight in weights]
    total_cents = max(int(round(total * 100)), 0)
    weight_sum = sum(safe_weights)
    raw_cents = [(total_cents * weight) / weight_sum for weight in safe_weights]
    base_cents = [int(value) for value in raw_cents]
    remainder = total_cents - sum(base_cents)

    ranked_indexes = sorted(
        range(len(raw_cents)),
        key=lambda index: (raw_cents[index] - base_cents[index], -index),
        reverse=True,
    )
    for index in ranked_indexes[:remainder]:
        base_cents[index] += 1

    return [round(value / 100, 2) for value in base_cents]


def _estimate_ticket_cost(spot_name: str, description: str | None = None) -> float:
    """根据景点关键词估算门票，更接近真实行程而不是固定数值。"""
    text = f"{spot_name} {description or ''}"
    bucket = _stable_bucket(text, 4)

    if any(keyword in text for keyword in ("古城", "古镇", "公园", "廊道", "村", "湿地", "街区")):
        return [0.0, 20.0, 30.0, 40.0][bucket]
    if any(keyword in text for keyword in ("寺", "三塔", "博物馆", "遗址", "山庄")):
        return round(60.0 + (bucket * 18.0), 2)
    if any(keyword in text for keyword in ("索道", "缆车", "游船", "演出", "雪山")):
        return round(120.0 + (bucket * 28.0), 2)
    return round(35.0 + (bucket * 12.0), 2)


def _build_hotel_weights(day_count: int, start_date: DateType) -> list[float]:
    """让住宿费用按周末、尾日等因素轻微浮动。"""
    weights: list[float] = []
    for index in range(day_count):
        current_date = start_date + timedelta(days=index)
        weight = 1.0
        if current_date.weekday() in (4, 5):
            weight += 0.18
        if index == day_count - 1:
            weight += 0.08
        if index % 2 == 1:
            weight += 0.05
        weights.append(weight)
    return weights


def _build_meal_weights(day_count: int, preferences: list[str]) -> list[float]:
    """让美食偏好的用户在部分天数获得更高餐饮预算。"""
    foodie_bonus = 0.12 if "美食" in preferences else 0.0
    return [
        1.0 + foodie_bonus + (0.08 if index == day_count // 2 else 0.0) + ((index % 3) * 0.04)
        for index in range(day_count)
    ]


def _build_transport_weights(day_count: int, pace: str | None) -> list[float]:
    """让交通预算随行程节奏和首尾日轻微浮动。"""
    pace_bonus = 0.12 if pace == "紧凑" else -0.04 if pace == "轻松" else 0.04
    return [
        1.0 + pace_bonus + (0.16 if index in (0, day_count - 1) else 0.0) + (index * 0.03)
        for index in range(day_count)
    ]


def _apply_route_based_transport_costs(itinerary: Itinerary) -> None:
    """在已有路线距离时，用路线信息修正交通花费和耗时。"""
    for day in itinerary.days:
        for transport in day.transport:
            if transport.estimated_minutes is not None:
                transport.duration = f"{transport.estimated_minutes} 分钟"

            if transport.distance_km is None:
                continue

            mode = transport.mode or ""
            if "公交" in mode:
                cost = max(2.0, 2.0 + (transport.distance_km * 0.25))
            elif "步行" in mode:
                cost = 0.0
            elif "包车" in mode:
                cost = 30.0 + (transport.distance_km * 3.8)
            else:
                cost = 10.0 + (transport.distance_km * 2.2)

            transport.estimated_cost = round(cost, 2)


def _refresh_budget_breakdown(itinerary: Itinerary, request_budget: float | None = None) -> Itinerary:
    """从具体条目回算预算汇总，避免预算明细显得过于模板化。"""
    _apply_route_based_transport_costs(itinerary)

    transport_total = round(
        sum(item.estimated_cost for day in itinerary.days for item in day.transport),
        2,
    )
    hotel_total = round(
        sum(day.hotel.estimated_cost for day in itinerary.days if day.hotel is not None),
        2,
    )
    meal_total = round(
        sum(item.estimated_cost for day in itinerary.days for item in day.meals),
        2,
    )
    ticket_total = round(
        sum(item.estimated_cost for day in itinerary.days for item in day.spots),
        2,
    )

    subtotal = transport_total + hotel_total + meal_total + ticket_total
    if request_budget is not None:
        other_total = round(max(0.0, min(request_budget * 0.12, request_budget - subtotal)), 2)
    else:
        other_total = round(max(subtotal * 0.06, 0.0), 2)

    total = round(subtotal + other_total, 2)
    itinerary.budget_breakdown = BudgetBreakdown(
        transport=transport_total,
        hotel=hotel_total,
        meals=meal_total,
        tickets=ticket_total,
        other=other_total,
        total=total,
    )
    itinerary.estimated_budget = total
    return itinerary


def _maybe_enrich_itinerary_with_map_data(
    itinerary: Itinerary,
    city: str | None = None,
    request_budget: float | None = None,
) -> Itinerary:
    """按开关补充地图信息，并在最后统一刷新预算。"""
    itinerary.provenance.map_total_spots = sum(
        len(day.spots) for day in itinerary.days
    )
    if ENABLE_AMAP_ENRICHMENT:
        started_at = perf_counter()
        try:
            itinerary = enrich_itinerary_with_map_data(itinerary, city=city)
            logger.info(
                "[4/4 地图补全] 完成 verified=%s/%s status=%s duration_ms=%.2f",
                itinerary.provenance.map_verified_spots,
                itinerary.provenance.map_total_spots,
                itinerary.provenance.map_status,
                (perf_counter() - started_at) * 1000,
            )
        except Exception as exc:
            itinerary.provenance.map_status = "unavailable"
            itinerary.provenance.map_verified_spots = 0
            logger.exception(
                "[4/4 地图补全] 失败 error_type=%s duration_ms=%.2f",
                type(exc).__name__,
                (perf_counter() - started_at) * 1000,
            )

    else:
        itinerary.provenance.map_status = "disabled"
        itinerary.provenance.map_verified_spots = 0
        logger.info("[4/4 地图补全] 已关闭，跳过")

    return _refresh_budget_breakdown(itinerary, request_budget=request_budget)


def generate_trip_itinerary(
    request: TripRequest,
    progress_callback: ProgressCallback | None = None,
) -> Itinerary:
    """生成完整 itinerary，支持每天多个景点 / 多个餐饮。"""
    total_started_at = perf_counter()
    _report_progress(progress_callback, "preparing", 5)
    day_count = (request.end_date - request.start_date).days + 1
    day_count = max(day_count, 1)
    logger.info(
        "[行程生成] 开始 destination=%s days=%s travelers=%s",
        request.destination,
        day_count,
        request.travelers,
    )

    rag_started_at = perf_counter()
    _report_progress(progress_callback, "retrieving_context", 15)
    logger.info("[1/4 RAG 检索] 开始检索本地知识库")
    rag_contexts, rewrite_usage, rerank_usage, embedding_usage = collect_trip_context(
        destination=request.destination,
        preferences=request.preferences,
        pace=request.pace,
        special_notes=request.special_notes,
    )
    logger.info(
        "[1/4 RAG 检索] 完成 contexts=%s duration_ms=%.2f "
        "tokens(rewrite=%s embedding=%s rerank=%s total=%s)",
        len(rag_contexts),
        (perf_counter() - rag_started_at) * 1000,
        rewrite_usage.get("prompt_tokens", 0) + rewrite_usage.get("completion_tokens", 0),
        embedding_usage.get("prompt_tokens", 0) + embedding_usage.get("completion_tokens", 0),
        rerank_usage.get("prompt_tokens", 0) + rerank_usage.get("completion_tokens", 0),
        sum(
            usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            for usage in (rewrite_usage, embedding_usage, rerank_usage)
        ),
    )
    _report_progress(progress_callback, "retrieving_context", 35)

    planner_started_at = perf_counter()
    _report_progress(progress_callback, "planning", 40)
    llm_draft, planner_usage = generate_planner_draft(request, rag_contexts, day_count)
    logger.info(
        "[2/4 LLM 规划] 阶段完成 fallback=%s duration_ms=%.2f",
        llm_draft is None,
        (perf_counter() - planner_started_at) * 1000,
    )
    _report_progress(progress_callback, "planning", 65)

    token_usage = TokenUsage(
        rewrite_prompt_tokens=rewrite_usage.get("prompt_tokens", 0),
        rewrite_completion_tokens=rewrite_usage.get("completion_tokens", 0),
        embedding_prompt_tokens=embedding_usage.get("prompt_tokens", 0),
        embedding_completion_tokens=embedding_usage.get("completion_tokens", 0),
        planner_prompt_tokens=planner_usage.get("prompt_tokens", 0),
        planner_completion_tokens=planner_usage.get("completion_tokens", 0),
        rerank_prompt_tokens=rerank_usage.get("prompt_tokens", 0),
        rerank_completion_tokens=rerank_usage.get("completion_tokens", 0),
    )
    logger.info(
        "[Token 汇总] QueryRewrite=%s Embedding=%s Rerank=%s Planner=%s | "
        "input=%s output=%s total=%s",
        token_usage.rewrite_prompt_tokens + token_usage.rewrite_completion_tokens,
        token_usage.embedding_prompt_tokens + token_usage.embedding_completion_tokens,
        token_usage.rerank_prompt_tokens + token_usage.rerank_completion_tokens,
        token_usage.planner_prompt_tokens + token_usage.planner_completion_tokens,
        token_usage.total_prompt_tokens,
        token_usage.total_completion_tokens,
        token_usage.total_tokens,
    )

    spots_per_day = _spots_per_day(request.pace)
    _report_progress(progress_callback, "assembling", 70)
    logger.info("[3/4 行程组装] 正在整理每日景点、餐饮、住宿与预算")
    fallback_pool = _build_demo_spot_pool(
        request.destination, rag_contexts, day_count * spots_per_day
    )

    raw_days: list[dict[str, object]] = []
    all_ticket_costs: list[float] = []

    for index in range(day_count):
        day_number = index + 1
        current_date = request.start_date + timedelta(days=index)

        llm_day = None
        if llm_draft is not None:
            llm_day = next(
                (item for item in llm_draft.days if item.day_index == day_number), None
            )

        # --- 景点：优先用 LLM 的多景点，否则用兜底池切片 ---
        if llm_day is not None and llm_day.spots:
            spot_drafts = [
                (s.name, s.description or "本地攻略推荐，适合慢慢游览。") for s in llm_day.spots
            ]
        else:
            day_slice = fallback_pool[index * spots_per_day : (index + 1) * spots_per_day]
            spot_drafts = [
                (name, "根据本地攻略和偏好安排，适合用半天慢慢游览。") for name in day_slice
            ]
        if not spot_drafts:
            spot_drafts = [(f"{request.destination} 推荐景点 {day_number}", "本地攻略推荐。")]

        # --- 餐饮：优先用 LLM 的多餐饮，否则给午/晚两餐 ---
        if llm_day is not None and llm_day.meals:
            meal_drafts = [
                (m.name, m.meal_type or "正餐", m.notes or "本地攻略推荐的餐饮。")
                for m in llm_day.meals
            ]
        else:
            meal_drafts = [
                (f"{request.destination} 特色午餐 {day_number}", "午餐", "本地攻略推荐的特色餐饮。"),
                (f"{request.destination} 特色晚餐 {day_number}", "晚餐", "本地攻略推荐的特色餐饮。"),
            ]

        theme = (
            llm_day.theme
            if llm_day is not None
            else f"{request.destination} 第 {day_number} 天行程"
        )
        daily_note = (
            llm_day.daily_note
            if llm_day is not None
            else "今天以轻松游览为主，建议根据体力和天气灵活调整停留时间。"
        )

        day_spots = [
            (name, desc, _estimate_ticket_cost(name, desc)) for name, desc in spot_drafts
        ]
        all_ticket_costs.extend(cost for _, _, cost in day_spots)

        raw_days.append(
            {
                "day_index": day_number,
                "date": current_date,
                "theme": theme,
                "spots": day_spots,    # list[(name, desc, ticket_cost)]
                "meals": meal_drafts,  # list[(name, meal_type, notes)]
                "daily_note": daily_note,
            }
        )

    ticket_total = round(sum(all_ticket_costs), 2)
    target_total = request.budget * (
        0.78 if request.pace == "轻松" else 0.92 if request.pace == "紧凑" else 0.85
    )
    other_budget = round(request.budget * (0.05 + min(day_count, 4) * 0.01), 2)
    allocatable_budget = max(target_total - ticket_total - other_budget, request.budget * 0.45)

    hotel_level = request.hotel_level or "舒适型"
    if "豪华" in hotel_level:
        hotel_ratio = 0.62
    elif "高档" in hotel_level or "高端" in hotel_level:
        hotel_ratio = 0.56
    elif "经济" in hotel_level:
        hotel_ratio = 0.40
    else:
        hotel_ratio = 0.50

    meal_ratio = 0.28 if "美食" in request.preferences else 0.22
    transport_ratio = max(0.12, 1 - hotel_ratio - meal_ratio)
    ratio_sum = hotel_ratio + meal_ratio + transport_ratio

    hotel_total = allocatable_budget * hotel_ratio / ratio_sum
    meal_total = allocatable_budget * meal_ratio / ratio_sum
    transport_total = allocatable_budget * transport_ratio / ratio_sum

    daily_hotel_costs = _prorate_amounts(
        hotel_total,
        _build_hotel_weights(day_count, request.start_date),
    )
    daily_meal_costs = _prorate_amounts(
        meal_total,
        _build_meal_weights(day_count, request.preferences),
    )
    daily_transport_costs = _prorate_amounts(
        transport_total,
        _build_transport_weights(day_count, request.pace),
    )

    days: list[DayPlan] = []
    for index, raw_day in enumerate(raw_days):
        spots_raw = raw_day["spots"]  # type: ignore[assignment]
        meals_raw = raw_day["meals"]  # type: ignore[assignment]

        spots: list[SpotItem] = []
        for i, (name, desc, ticket_cost) in enumerate(spots_raw):  # type: ignore[misc]
            slot = _SPOT_TIME_SLOTS[i] if i < len(_SPOT_TIME_SLOTS) else (None, None)
            spots.append(
                SpotItem(
                    name=name,
                    start_time=slot[0],
                    end_time=slot[1],
                    description=desc,
                    estimated_cost=float(ticket_cost),
                    location=request.destination,
                )
            )

        per_meal_cost = round(daily_meal_costs[index] / max(len(meals_raw), 1), 2)  # type: ignore[arg-type]
        meals = [
            MealItem(name=name, meal_type=meal_type, estimated_cost=per_meal_cost, notes=notes)
            for name, meal_type, notes in meals_raw  # type: ignore[misc]
        ]

        first_spot_name = spots[0].name if spots else request.destination

        days.append(
            DayPlan(
                day_index=int(raw_day["day_index"]),  # type: ignore[arg-type]
                date=raw_day["date"],  # type: ignore[arg-type]
                theme=str(raw_day["theme"]),
                spots=spots,
                meals=meals,
                hotel=HotelItem(
                    name=f"{request.destination} {hotel_level}住宿 {index + 1}",
                    level=hotel_level,
                    estimated_cost=daily_hotel_costs[index],
                    location=f"{request.destination} 市区",
                ),
                transport=[
                    TransportItem(
                        mode="打车",
                        from_place=f"{request.destination} 出发点",
                        to_place=first_spot_name,
                        estimated_cost=daily_transport_costs[index],
                        duration="30 分钟",
                    )
                ],
                notes=[
                    f"当前旅行节奏：{request.pace or '适中'}",
                    str(raw_day["daily_note"]),
                ],
            )
        )

    preference_text = "、".join(request.preferences) if request.preferences else "常规旅行体验"
    source_notes = [
        "Itinerary is assembled by trip_service.py and can optionally use LangChain structured output.",
    ]
    source_notes.extend(rag_contexts[:2])

    tips = (
        llm_draft.tips
        if llm_draft is not None and llm_draft.tips
        else [
            f"建议根据{request.destination}当天实时天气准备雨具或薄外套。",
            "当天如果步行游览较多，建议选择舒适防滑的鞋子，并根据体力灵活调整停留时间。",
        ]
    )
    if any("骑行" in context for context in rag_contexts):
        tips.append(
            f"本地攻略提到{request.destination}有适合骑行的路线，可根据天气和体力作为备选。"
        )
    tips = _clean_user_tips(tips, request.destination)

    summary = (
        llm_draft.summary
        if llm_draft is not None
        else f"这是一份为 {request.destination} 生成的 {day_count} 日行程，偏好重点为：{preference_text}。"
    )

    itinerary = Itinerary(
        trip_id=f"trip_{request.destination}_{request.start_date.isoformat()}",
        destination=request.destination,
        summary=summary,
        days=days,
        estimated_budget=0.0,
        budget_breakdown=BudgetBreakdown(),
        tips=tips,
        source_notes=source_notes,
        provenance=ItineraryProvenance(
            planning_source=(
                "llm_with_rag"
                if llm_draft is not None and rag_contexts
                else "llm_general_knowledge"
                if llm_draft is not None
                else "rule_fallback"
            ),
            rag_status="matched" if rag_contexts else "unavailable",
            rag_context_count=len(rag_contexts),
            map_status="pending" if ENABLE_AMAP_ENRICHMENT else "disabled",
            map_total_spots=sum(len(day.spots) for day in days),
            budget_is_estimate=True,
        ),
        token_usage=token_usage,
    )
    logger.info("[3/4 行程组装] 完成 days=%s", len(itinerary.days))
    _report_progress(progress_callback, "enriching_map", 85)
    logger.info("[4/4 地图补全] 开始 enabled=%s", ENABLE_AMAP_ENRICHMENT)
    itinerary = _maybe_enrich_itinerary_with_map_data(
        itinerary,
        city=request.destination,
        request_budget=request.budget,
    )
    _report_progress(progress_callback, "finalizing", 95)
    logger.info(
        "[行程生成] 全部完成 destination=%s days=%s duration_ms=%.2f total_tokens=%s",
        itinerary.destination,
        len(itinerary.days),
        (perf_counter() - total_started_at) * 1000,
        token_usage.total_tokens,
    )
    return itinerary


def edit_trip_itinerary(request: TripEditRequest) -> Itinerary:
    """优先使用 LLM 编辑单日行程，失败时回退到规则编辑。"""
    total_started_at = perf_counter()
    updated_itinerary = request.current_itinerary.model_copy(deep=True)

    target_day = updated_itinerary.days[0] if updated_itinerary.days else None
    if request.edit_scope and request.edit_scope.startswith("day_"):
        try:
            target_day_index = int(request.edit_scope.split("_")[1])
            matched_day = next(
                (day for day in updated_itinerary.days if day.day_index == target_day_index),
                None,
            )
            if matched_day is not None:
                target_day = matched_day
        except (IndexError, ValueError):
            pass

    llm_edit_applied = False
    edit_token_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    if target_day is not None:
        edit_started_at = perf_counter()
        day_edit_draft, edit_token_usage = generate_day_edit_draft(request, target_day)
        logger.info(
            "trip_stage_completed stage=day_edit trip_id=%s fallback=%s duration_ms=%.2f",
            request.trip_id,
            day_edit_draft is None,
            (perf_counter() - edit_started_at) * 1000,
        )
        if day_edit_draft is not None:
            target_day.theme = day_edit_draft.theme
            if target_day.spots:
                target_day.spots[0].name = day_edit_draft.spot_name
                target_day.spots[0].description = day_edit_draft.spot_description
                target_day.spots[0].estimated_cost = _estimate_ticket_cost(
                    day_edit_draft.spot_name,
                    day_edit_draft.spot_description,
                )
                target_day.spots[0].address = None
                target_day.spots[0].latitude = None
                target_day.spots[0].longitude = None
                target_day.spots[0].poi_id = None
            if target_day.meals:
                target_day.meals[0].name = day_edit_draft.meal_name
                target_day.meals[0].notes = day_edit_draft.meal_notes

            if target_day.notes:
                target_day.notes[-1] = day_edit_draft.daily_note
            else:
                target_day.notes.append(day_edit_draft.daily_note)

            llm_edit_applied = True
        else:
            if "轻松" in request.user_instruction:
                target_day.theme = f"{target_day.theme}（已调整为更轻松）"
                target_day.notes.append("已根据用户要求把节奏调整得更轻松。")

            if "不要安排" in request.user_instruction and target_day.spots:
                target_day.spots[0].name = "自由活动 / 弹性安排"
                target_day.spots[0].description = "根据用户要求，减少固定景点安排，保留更多自由活动时间。"
                target_day.spots[0].estimated_cost = 0.0
                target_day.spots[0].address = None
                target_day.spots[0].latitude = None
                target_day.spots[0].longitude = None
                target_day.spots[0].poi_id = None

    updated_itinerary.source_notes.append(
        f"已根据用户编辑指令更新行程：{request.user_instruction}"
    )
    updated_itinerary.tips = _clean_user_tips(
        updated_itinerary.tips,
        updated_itinerary.destination,
    )
    updated_itinerary.tips.append(
        "已根据你的修改要求更新目标日期，出发前建议再确认当天交通、天气和景点开放情况。"
    )

    updated_itinerary.token_usage = TokenUsage(
        rewrite_prompt_tokens=0,
        rewrite_completion_tokens=0,
        planner_prompt_tokens=edit_token_usage.get("prompt_tokens", 0),
        planner_completion_tokens=edit_token_usage.get("completion_tokens", 0),
    )

    reference_budget = (
        updated_itinerary.estimated_budget
        or updated_itinerary.budget_breakdown.total
        or None
    )
    updated_itinerary = _maybe_enrich_itinerary_with_map_data(
        updated_itinerary,
        city=updated_itinerary.destination,
        request_budget=reference_budget,
    )
    logger.info(
        "trip_edit_completed trip_id=%s llm_applied=%s duration_ms=%.2f",
        request.trip_id,
        llm_edit_applied,
        (perf_counter() - total_started_at) * 1000,
    )
    return updated_itinerary
