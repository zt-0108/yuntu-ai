from __future__ import annotations

from datetime import date as DateType, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TripRequest(BaseModel):
    """用于生成新行程的请求体。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    destination: str = Field(..., min_length=1, max_length=100, description="目的地，例如大理")
    start_date: DateType = Field(..., description="出行开始日期")
    end_date: DateType = Field(..., description="出行结束日期")
    travelers: int = Field(..., ge=1, le=20, description="出行人数")
    budget: float = Field(..., ge=0, le=10_000_000, description="总预算")
    preferences: list[str] = Field(default_factory=list, max_length=20, description="旅行偏好标签")
    pace: str | None = Field(default=None, max_length=20, description="旅行节奏，例如轻松、适中、紧凑")
    dietary_preferences: list[str] = Field(
        default_factory=list,
        description="饮食偏好或忌口",
    )
    hotel_level: str | None = Field(default=None, max_length=50, description="酒店档次偏好")
    special_notes: str | None = Field(default=None, max_length=2000, description="额外要求")
    departure_city: str | None = Field(default=None, max_length=100, description="铁路出发城市")
    preferred_departure_period: Literal["上午", "下午", "晚上"] | None = Field(
        default=None,
        description="偏好的列车出发时段",
    )
    preferred_train_types: list[Literal["G", "D", "C", "Z", "T", "K"]] = Field(
        default_factory=list,
        max_length=6,
        description="偏好的车次类型",
    )
    seat_preference: Literal[
        "商务座",
        "一等座",
        "二等座",
        "软卧",
        "硬卧",
        "硬座",
        "无座",
    ] | None = Field(default="二等座", description="偏好的席别")

    @model_validator(mode="after")
    def validate_travel_dates(self) -> "TripRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days + 1 > 30:
            raise ValueError("trip duration cannot exceed 30 days")
        return self


class TripEditRequest(BaseModel):
    """用于修改已有行程的请求体。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    trip_id: str = Field(..., min_length=1, max_length=100, description="需要编辑的行程 ID")
    current_itinerary: "Itinerary" = Field(..., description="当前完整 itinerary")
    user_instruction: str = Field(..., min_length=1, max_length=2000, description="用户新的修改要求")
    edit_scope: str | None = Field(default=None, max_length=100, description="编辑范围")
    preserve_constraints: list[str] = Field(
        default_factory=list,
        description="需要尽量保留的条件",
    )


class TripSaveRequest(BaseModel):
    """用于保存当前 itinerary 的请求体。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    trip_id: str = Field(..., min_length=1, max_length=100, description="需要保存的行程 ID")
    itinerary: "Itinerary" = Field(..., description="完整行程数据")
    user_id: str | None = Field(default=None, max_length=100, description="用户 ID，当前版本可留空")

    @model_validator(mode="after")
    def validate_trip_id_matches_itinerary(self) -> "TripSaveRequest":
        if self.trip_id != self.itinerary.trip_id:
            raise ValueError("trip_id must match itinerary.trip_id")
        return self


class SpotItem(BaseModel):
    """单个景点安排。"""

    name: str = Field(..., description="景点名称")
    start_time: str | None = Field(default=None, description="开始时间")
    end_time: str | None = Field(default=None, description="结束时间")
    description: str | None = Field(default=None, description="景点安排说明")
    estimated_cost: float = Field(default=0.0, ge=0, description="预估花费")
    location: str | None = Field(default=None, description="景点位置描述")
    image_url: str | None = Field(default=None, description="景点图片地址")
    address: str | None = Field(default=None, description="景点详细地址")
    latitude: float | None = Field(default=None, description="景点纬度")
    longitude: float | None = Field(default=None, description="景点经度")
    poi_id: str | None = Field(default=None, description="地图服务返回的 POI 标识")


class MealItem(BaseModel):
    """单个餐饮安排。"""

    name: str = Field(..., description="餐厅或餐饮建议名称")
    meal_type: str = Field(..., description="早餐、午餐、晚餐等")
    estimated_cost: float = Field(default=0.0, ge=0, description="预估花费")
    notes: str | None = Field(default=None, description="补充说明")


class HotelItem(BaseModel):
    """单个住宿安排。"""

    name: str = Field(..., description="酒店名称")
    level: str | None = Field(default=None, description="酒店档次")
    estimated_cost: float = Field(default=0.0, ge=0, description="预估花费")
    location: str | None = Field(default=None, description="酒店位置")
    address: str | None = Field(default=None, description="酒店详细地址")
    latitude: float | None = Field(default=None, description="酒店纬度")
    longitude: float | None = Field(default=None, description="酒店经度")


class TransportItem(BaseModel):
    """单段交通安排。"""

    mode: str = Field(..., description="交通方式，例如步行、打车、公交")
    from_place: str | None = Field(default=None, description="出发地")
    to_place: str | None = Field(default=None, description="目的地")
    estimated_cost: float = Field(default=0.0, ge=0, description="预估花费")
    duration: str | None = Field(default=None, description="预计耗时")
    distance_km: float | None = Field(default=None, ge=0, description="预计距离，单位公里")
    estimated_minutes: int | None = Field(default=None, ge=0, description="预计耗时，单位分钟")


class BudgetBreakdown(BaseModel):
    """预算拆分。"""

    transport: float = Field(default=0.0, ge=0, description="交通预算")
    hotel: float = Field(default=0.0, ge=0, description="住宿预算")
    meals: float = Field(default=0.0, ge=0, description="餐饮预算")
    tickets: float = Field(default=0.0, ge=0, description="门票预算")
    other: float = Field(default=0.0, ge=0, description="其他预算")
    total: float = Field(default=0.0, ge=0, description="预算总计")


class DayPlan(BaseModel):
    """单日行程安排。"""

    day_index: int = Field(..., ge=1, description="第几天")
    date: DateType | None = Field(default=None, description="当天日期")
    theme: str | None = Field(default=None, description="当天主题")
    spots: list[SpotItem] = Field(default_factory=list, description="景点安排")
    meals: list[MealItem] = Field(default_factory=list, description="餐饮安排")
    hotel: HotelItem | None = Field(default=None, description="住宿安排")
    transport: list[TransportItem] = Field(default_factory=list, description="交通安排")
    notes: list[str] = Field(default_factory=list, description="补充说明")


class TokenUsage(BaseModel):
    """LLM 调用的 token 消耗统计。"""

    rewrite_prompt_tokens: int = Field(default=0, ge=0, description="Query Rewrite 输入 token")
    rewrite_completion_tokens: int = Field(default=0, ge=0, description="Query Rewrite 输出 token")
    embedding_prompt_tokens: int = Field(default=0, ge=0, description="Query Embedding 输入 token")
    embedding_completion_tokens: int = Field(default=0, ge=0, description="Query Embedding 输出 token")
    planner_prompt_tokens: int = Field(default=0, ge=0, description="行程生成输入 token")
    planner_completion_tokens: int = Field(default=0, ge=0, description="行程生成输出 token")
    rerank_prompt_tokens: int = Field(default=0, ge=0, description="Rerank 输入 token")
    rerank_completion_tokens: int = Field(default=0, ge=0, description="Rerank 输出 token")

    @property
    def total_prompt_tokens(self) -> int:
        return (
            self.rewrite_prompt_tokens
            + self.embedding_prompt_tokens
            + self.planner_prompt_tokens
            + self.rerank_prompt_tokens
        )

    @property
    def total_completion_tokens(self) -> int:
        return (
            self.rewrite_completion_tokens
            + self.embedding_completion_tokens
            + self.planner_completion_tokens
            + self.rerank_completion_tokens
        )

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens


class RailTicketOption(BaseModel):
    """标准化后的候选车次。"""

    train_code: str
    travel_date: DateType
    departure_station: str
    arrival_station: str
    departure_time: str
    arrival_time: str
    duration: str
    duration_minutes: int | None = Field(default=None, ge=0)
    seats: dict[str, str] = Field(default_factory=dict)
    prices: dict[str, float] = Field(default_factory=dict)
    preferred_seat: str | None = None
    preferred_seat_availability: str | None = None
    preferred_seat_price: float | None = Field(default=None, ge=0)


class RailTicketPlan(BaseModel):
    """往返铁路查询结果；查询结果不代表预订。"""

    status: Literal["available", "unavailable", "error", "disabled"] = "disabled"
    departure_city: str | None = None
    destination: str | None = None
    outbound: list[RailTicketOption] = Field(default_factory=list)
    return_trip: list[RailTicketOption] = Field(default_factory=list)
    queried_at: datetime | None = None
    source_name: str = "12306 MCP（第三方开源服务）"
    source_url: str = "https://github.com/drfccv/mcp-server-12306"
    disclaimer: str = "余票与票价会实时变化，仅供行程规划参考，请以铁路12306官方渠道为准。"
    message: str | None = None


class ItineraryProvenance(BaseModel):
    """行程内容的数据来源与外部验证情况。"""

    planning_source: Literal[
        "llm_with_rag",
        "llm_general_knowledge",
        "rule_fallback",
        "unknown",
    ] = "unknown"
    rag_status: Literal["matched", "unavailable", "unknown"] = "unknown"
    rag_context_count: int = Field(default=0, ge=0)
    map_status: Literal[
        "pending",
        "verified",
        "partial",
        "unavailable",
        "disabled",
        "unknown",
    ] = "unknown"
    map_verified_spots: int = Field(default=0, ge=0)
    map_total_spots: int = Field(default=0, ge=0)
    rail_status: Literal[
        "available",
        "unavailable",
        "error",
        "disabled",
        "unknown",
    ] = "unknown"
    budget_is_estimate: bool = True


class Itinerary(BaseModel):
    """完整行程。"""

    trip_id: str = Field(..., description="行程唯一标识")
    destination: str = Field(..., description="目的地")
    summary: str = Field(..., description="整趟行程的概述")
    days: list[DayPlan] = Field(default_factory=list, description="逐日行程")
    estimated_budget: float = Field(default=0.0, ge=0, description="预算总计")
    budget_breakdown: BudgetBreakdown = Field(..., description="预算明细")
    tips: list[str] = Field(default_factory=list, description="旅行建议")
    source_notes: list[str] = Field(
        default_factory=list,
        description="RAG 或规则生成产生的补充说明",
    )
    provenance: ItineraryProvenance = Field(
        default_factory=ItineraryProvenance,
        description="行程规划、RAG 与地图验证的来源信息",
    )
    rail_tickets: RailTicketPlan = Field(
        default_factory=RailTicketPlan,
        description="往返铁路候选车次，仅用于查询与规划",
    )
    token_usage: TokenUsage | None = Field(default=None, description="LLM token 消耗统计")


class TripGenerationJobCreated(BaseModel):
    """异步行程生成任务创建结果。"""

    job_id: str
    status: Literal["queued", "running"] = "queued"
    reused: bool = False


class TripGenerationJobStatus(BaseModel):
    """异步行程生成任务当前状态。"""

    job_id: str
    status: Literal[
        "queued",
        "running",
        "cancelling",
        "cancelled",
        "completed",
        "failed",
    ]
    stage: str
    progress: int = Field(..., ge=0, le=100)
    itinerary: Itinerary | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class TripDetailResponse(BaseModel):
    """查询已保存行程时返回的响应体。"""

    trip_id: str = Field(..., description="行程 ID")
    itinerary: Itinerary = Field(..., description="已保存的完整行程")
    created_at: datetime | None = Field(default=None, description="创建时间")
    updated_at: datetime | None = Field(default=None, description="更新时间")


class TripSummaryItem(BaseModel):
    """已保存行程的摘要信息。"""

    trip_id: str = Field(..., description="行程 ID")
    destination: str = Field(..., description="目的地")
    summary: str = Field(..., description="行程概述")
    created_at: datetime | None = Field(default=None, description="创建时间")
    updated_at: datetime | None = Field(default=None, description="更新时间")


class TripListResponse(BaseModel):
    """行程列表接口的响应结构。"""

    total: int = Field(..., ge=0, description="列表总数")
    items: list[TripSummaryItem] = Field(default_factory=list, description="行程摘要列表")


class TripTokenStatsItem(BaseModel):
    """单个行程的 token 消耗。"""

    trip_id: str = Field(..., description="行程 ID")
    destination: str = Field(..., description="目的地")
    token_usage: TokenUsage = Field(..., description="token 消耗")


class TokenStatsResponse(BaseModel):
    """Token 消耗统计接口的响应结构。"""

    trip_count: int = Field(..., ge=0, description="统计行程数")
    total_prompt_tokens: int = Field(default=0, ge=0, description="总输入 token")
    total_completion_tokens: int = Field(default=0, ge=0, description="总输出 token")
    total_tokens: int = Field(default=0, ge=0, description="总 token")
    items: list[TripTokenStatsItem] = Field(default_factory=list, description="各行程 token 明细")
