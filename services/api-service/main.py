"""Main FastAPI application for api-service."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from routers.telegram import router as telegram_router

from packages.shared.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle management."""
    yield
    await close_redis()


def create_app() -> FastAPI:
    """Factory creating configured FastAPI instance."""
    app = FastAPI(
        title="Teemeto API Service",
        description="Core multi-tenant webhook and orchestration API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "api-service"}

    app.include_router(telegram_router)
    return app


app = create_app()
