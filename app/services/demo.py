"""In-memory Demo Mode state machine for pre-recorded WhatsApp voice playback."""

import asyncio
import logging

from app.core.config import Settings
from app.providers.twilio import _send_twilio_message, normalize_phone_number

logger = logging.getLogger(__name__)

DEMO_CLIPS: dict[int, tuple[str, ...]] = {
    1: ("yauwa_r01_stock_ack.mp3",),
    2: ("yauwa_r02_confirm.mp3",),
    3: ("yauwa_r03_recorded.mp3", "yauwa_r04_lowstock.mp3"),
    4: ("yauwa_r05_market_milk.mp3", "yauwa_r06_market_bread.mp3"),
    5: ("yauwa_r07_done.mp3",),
}
INTER_CLIP_DELAY_SECONDS = 1.0

_demo_steps: dict[str, int] = {}
_demo_lock = asyncio.Lock()


def get_demo_step(phone_number: str) -> int:
    """Return the current step (0-4) for a demo phone number."""
    return _demo_steps.get(normalize_phone_number(phone_number), 0)


def reset_demo_state(phone_number: str | None = None) -> None:
    """Reset the demo step counter to 0 for one session or all sessions."""
    if phone_number is None:
        _demo_steps.clear()
        return
    _demo_steps.pop(normalize_phone_number(phone_number), None)


def _demo_media_url(settings: Settings, filename: str) -> str:
    base_url = str(settings.public_base_url).rstrip("/")
    return f"{base_url}/demo/audio/{filename}"


async def handle_demo_message(phone_number: str, settings: Settings) -> str:
    """Advance the demo state machine and send the step's pre-recorded audio clip(s)."""
    normalized = normalize_phone_number(phone_number)
    async with _demo_lock:
        next_step = _demo_steps.get(normalized, 0) + 1
        if next_step > 5:
            next_step = 1
        _demo_steps[normalized] = 0 if next_step == 5 else next_step

    clips = DEMO_CLIPS[next_step]
    logger.info("Demo mode step %d for %s (%d clip(s))", next_step, normalized, len(clips))

    for index, filename in enumerate(clips):
        if index > 0:
            await asyncio.sleep(INTER_CLIP_DELAY_SECONDS)
        media_url = _demo_media_url(settings, filename)
        await asyncio.to_thread(
            _send_twilio_message,
            settings,
            normalized,
            media_url=media_url,
        )

    return "demo complete" if next_step == 5 else f"demo step {next_step}"
