import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import logging

# pyrefly: ignore [missing-import]
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


from app.providers.tts import cleanup_expired_media
from app.api.demo import router as demo_router
from app.api.health import router as health_router
from app.api.media import router as media_router
from app.api.webhook import router as webhook_router

logging.getLogger("app").setLevel(logging.INFO)


async def _media_cleanup_loop() -> None:
    """Remove expired generated replies while this app process is running."""
    while True:
        await cleanup_expired_media()
        await asyncio.sleep(60 * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(_media_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(lifespan=lifespan)
app.include_router(demo_router)
app.include_router(health_router)
app.include_router(media_router)
app.include_router(webhook_router)
app.mount(
    "/demo/audio",
    StaticFiles(directory=Path(__file__).resolve().parent / "demo" / "audio"),
    name="demo-audio",
)
