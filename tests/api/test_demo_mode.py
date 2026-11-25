"""Tests for Yauwa AI Demo Mode routing, playback sequence, reset, and static audio."""

import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from app.api.webhook import _process_incoming_message
from app.core.config import TwilioSettings
from app.schemas.webhook import TwilioWebhookPayload
from app.services.demo import get_demo_step, reset_demo_state
from main import app

DEMO_PHONE = "+2348099999999"
OTHER_PHONE = "+2348011111111"
PUBLIC_BASE_URL = "https://demo.yauwa.test"
RESET_KEY = "yauwa-demo-2024"


def _make_settings(*, demo_phone: str = DEMO_PHONE) -> Mock:
    settings = Mock()
    settings.demo_phone_number = demo_phone
    settings.demo_reset_key = RESET_KEY
    settings.public_base_url = PUBLIC_BASE_URL
    settings.twilio_account_sid = "AC11111111111111111111111111111111"
    settings.twilio_auth_token.get_secret_value.return_value = "test-auth-token"
    settings.twilio_whatsapp_number = "+14155238886"
    return settings


def _make_twilio_settings() -> TwilioSettings:
    return TwilioSettings(
        twilio_account_sid="AC11111111111111111111111111111111",
        twilio_auth_token="test-auth-token",
        twilio_webhook_url=f"{PUBLIC_BASE_URL}/api/v1/webhook",
    )


def _make_payload(sender: str, sid: str = "SM-demo-1") -> TwilioWebhookPayload:
    return TwilioWebhookPayload.model_validate(
        {
            "From": f"whatsapp:{sender}" if not sender.startswith("whatsapp:") else sender,
            "MessageSid": sid,
            "MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/AC11111111111111111111111111111111/Messages/MM1/Media/ME1",
            "MediaContentType0": "audio/ogg",
        }
    )


class DemoModeRoutingAndSequenceTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_demo_state()
        self.twilio_settings = _make_twilio_settings()

    def tearDown(self) -> None:
        reset_demo_state()

    async def test_demo_number_routes_to_demo_mode_without_onboarding_or_extraction(
        self,
    ) -> None:
        settings = _make_settings(demo_phone=f"whatsapp:{DEMO_PHONE}")
        payload = _make_payload(DEMO_PHONE)

        with (
            patch("app.api.webhook.get_settings", return_value=settings),
            patch("app.api.webhook.Session") as session_cls,
            patch("app.api.webhook.onboard_trader", new=AsyncMock()) as onboard,
            patch("app.api.webhook.process_trader_audio", new=AsyncMock()) as process_audio,
            patch("app.services.demo._send_twilio_message", return_value="SM-out-1") as send_msg,
        ):
            result = await _process_incoming_message(payload, self.twilio_settings)

        self.assertEqual(result, "demo step 1")
        session_cls.assert_not_called()
        onboard.assert_not_awaited()
        process_audio.assert_not_awaited()
        send_msg.assert_called_once_with(
            settings,
            DEMO_PHONE,
            media_url=f"{PUBLIC_BASE_URL}/demo/audio/yauwa_r01_stock_ack.mp3",
        )

    async def test_steps_1_through_5_play_exact_7_clips_and_reset_after_step_5(
        self,
    ) -> None:
        settings = _make_settings()
        sent_urls: list[str] = []

        def record_send(_settings, _phone, *, body=None, media_url=None):
            if media_url is not None:
                sent_urls.append(media_url)
            return f"SM-{len(sent_urls)}"

        with (
            patch("app.api.webhook.get_settings", return_value=settings),
            patch("app.services.demo._send_twilio_message", side_effect=record_send),
            patch("app.services.demo.asyncio.sleep", new=AsyncMock()) as sleep_mock,
        ):
            # Step 1
            res1 = await _process_incoming_message(_make_payload(DEMO_PHONE, "SM-1"), self.twilio_settings)
            self.assertEqual(res1, "demo step 1")
            self.assertEqual(get_demo_step(DEMO_PHONE), 1)
            self.assertEqual(sent_urls, [f"{PUBLIC_BASE_URL}/demo/audio/yauwa_r01_stock_ack.mp3"])

            # Step 2
            res2 = await _process_incoming_message(_make_payload(DEMO_PHONE, "SM-2"), self.twilio_settings)
            self.assertEqual(res2, "demo step 2")
            self.assertEqual(get_demo_step(DEMO_PHONE), 2)
            self.assertEqual(
                sent_urls[1:],
                [f"{PUBLIC_BASE_URL}/demo/audio/yauwa_r02_confirm.mp3"],
            )

            # Step 3: 2 sequential messages with 1.0s sleep
            res3 = await _process_incoming_message(_make_payload(DEMO_PHONE, "SM-3"), self.twilio_settings)
            self.assertEqual(res3, "demo step 3")
            self.assertEqual(get_demo_step(DEMO_PHONE), 3)
            self.assertEqual(
                sent_urls[2:],
                [
                    f"{PUBLIC_BASE_URL}/demo/audio/yauwa_r03_recorded.mp3",
                    f"{PUBLIC_BASE_URL}/demo/audio/yauwa_r04_lowstock.mp3",
                ],
            )
            sleep_mock.assert_awaited_once_with(1.0)

            # Step 4: 2 sequential messages with 1.0s sleep
            res4 = await _process_incoming_message(_make_payload(DEMO_PHONE, "SM-4"), self.twilio_settings)
            self.assertEqual(res4, "demo step 4")
            self.assertEqual(get_demo_step(DEMO_PHONE), 4)
            self.assertEqual(
                sent_urls[4:],
                [
                    f"{PUBLIC_BASE_URL}/demo/audio/yauwa_r05_market_milk.mp3",
                    f"{PUBLIC_BASE_URL}/demo/audio/yauwa_r06_market_bread.mp3",
                ],
            )
            self.assertEqual(sleep_mock.await_count, 2)

            # Step 5: final clip and auto-reset to 0
            res5 = await _process_incoming_message(_make_payload(DEMO_PHONE, "SM-5"), self.twilio_settings)
            self.assertEqual(res5, "demo complete")
            self.assertEqual(get_demo_step(DEMO_PHONE), 0)
            self.assertEqual(
                sent_urls[6:],
                [f"{PUBLIC_BASE_URL}/demo/audio/yauwa_r07_done.mp3"],
            )

            # Next message starts cleanly from step 1 again
            res6 = await _process_incoming_message(_make_payload(DEMO_PHONE, "SM-6"), self.twilio_settings)
            self.assertEqual(res6, "demo step 1")
            self.assertEqual(get_demo_step(DEMO_PHONE), 1)
            self.assertEqual(
                sent_urls[7:],
                [f"{PUBLIC_BASE_URL}/demo/audio/yauwa_r01_stock_ack.mp3"],
            )

    async def test_non_demo_number_uses_normal_webhook_processing(self) -> None:
        settings = _make_settings()
        payload = _make_payload(OTHER_PHONE)

        with (
            patch("app.api.webhook.get_settings", return_value=settings),
            patch("app.api.webhook.Session"),
            patch("app.api.webhook.get_engine"),
            patch("app.api.webhook.onboarding_complete", return_value=True),
            patch(
                "app.api.webhook._download_audio",
                new=AsyncMock(return_value="/tmp/other.ogg"),
            ),
            patch(
                "app.api.webhook.process_trader_audio",
                new=AsyncMock(return_value={"intent": "sale"}),
            ) as process_audio,
            patch("app.api.webhook._remove_file", new=AsyncMock()),
            patch("app.services.demo._send_twilio_message") as demo_send,
            patch("builtins.print"),
        ):
            result = await _process_incoming_message(payload, self.twilio_settings)

        self.assertEqual(result, "extraction processed")
        process_audio.assert_awaited_once()
        demo_send.assert_not_called()


class DemoResetAndStaticAudioTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_demo_state()
        self.settings = _make_settings()

    def tearDown(self) -> None:
        reset_demo_state()

    async def test_demo_reset_endpoint_resets_step_with_valid_key(self) -> None:
        with (
            patch("app.api.webhook.get_settings", return_value=self.settings),
            patch("app.api.demo.get_settings", return_value=self.settings),
            patch("app.services.demo._send_twilio_message", return_value="SM-1"),
        ):
            await _process_incoming_message(
                _make_payload(DEMO_PHONE, "SM-before-reset"),
                _make_twilio_settings(),
            )
            self.assertEqual(get_demo_step(DEMO_PHONE), 1)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/demo/reset",
                    headers={"X-Demo-Reset-Key": RESET_KEY},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "message": "Demo reset complete"},
        )
        self.assertEqual(get_demo_step(DEMO_PHONE), 0)

    async def test_demo_reset_rejects_missing_or_wrong_key_with_403(self) -> None:
        with patch("app.api.demo.get_settings", return_value=self.settings):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                missing_resp = await client.post("/demo/reset")
                wrong_resp = await client.post(
                    "/demo/reset",
                    headers={"X-Demo-Reset-Key": "wrong-key"},
                )

        self.assertEqual(missing_resp.status_code, 403)
        self.assertEqual(wrong_resp.status_code, 403)

    async def test_static_demo_audio_files_are_served(self) -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/demo/audio/yauwa_r01_stock_ack.mp3")

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 0)


if __name__ == "__main__":
    unittest.main()
