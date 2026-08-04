from contextlib import asynccontextmanager
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.export import router as export_router
from app.api.routes.trip import router as trip_router
from app.api.routes.weather import router as weather_router
from app.api.errors import install_exception_handlers
from app.config import CORS_ORIGINS, LOG_LEVEL
from app.observability import configure_logging, reset_request_id, set_request_id
from app.services.storage_service import init_db


configure_logging(LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("application_started")
    yield
    logger.info("application_stopped")


app = FastAPI(
    title="云途 AI 服务",
    description="云途智能旅行助手的行程生成、地图、天气与旅行收藏服务。",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
install_exception_handlers(app)


@app.middleware("http")
async def log_request(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    request_id_token = set_request_id(request_id)
    started_at = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration_ms = (perf_counter() - started_at) * 1000
        if status_code >= 400:
            logger.warning(
                "[HTTP] 请求失败 method=%s status=%s duration_ms=%.2f",
                request.method,
                status_code,
                duration_ms,
            )
        else:
            logger.debug(
                "[HTTP] 请求完成 method=%s status=%s duration_ms=%.2f",
                request.method,
                status_code,
                duration_ms,
            )
        reset_request_id(request_id_token)


@app.get("/")
def read_root() -> dict[str, str]:
    """根路径接口，用于确认后端服务已启动。"""
    return {"message": "云途 AI 服务运行正常。"}


@app.get("/health")
def health_check() -> dict[str, str]:
    """健康检查接口。"""
    return {"status": "ok"}


app.include_router(trip_router)
app.include_router(export_router)
app.include_router(weather_router)
