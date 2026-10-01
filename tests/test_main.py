from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import HELP_TEXT, START_MENU, START_TEXT, app


def test_supported_url_is_acknowledged_without_waiting_for_analysis():
    payload = {
        "message": {
            "chat": {"id": 123},
            "text": "https://www.youtube.com/watch?v=abc",
        }
    }

    with patch("app.main.settings.bot_token", "token", create=True), patch(
        "app.main.settings.webhook_secret", ""
    ), patch("app.main.send_message", new_callable=AsyncMock) as send_message, patch(
        "app.main.process_download_and_send", new_callable=AsyncMock
    ) as process_task:
        client = TestClient(app)
        response = client.post("/webhook", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert send_message.await_count >= 1
    process_task.assert_awaited_once()


def test_start_keyboard_contains_home_start_button():
    assert any(
        button.get("text") == "🏠 Start"
        for row in START_MENU["keyboard"]
        for button in row
    )


def test_handle_update_home_start_sends_start_menu():
    import asyncio

    from app.main import handle_update

    update = {"message": {"chat": {"id": 123}, "text": "🏠 Start"}}
    with patch("app.main.send_message", new_callable=AsyncMock) as send_message:
        asyncio.run(handle_update(update))

    send_message.assert_awaited_once_with(123, START_TEXT, reply_markup=START_MENU)


def test_handle_update_start_sends_start_menu():
    import asyncio

    from app.main import handle_update

    update = {"message": {"chat": {"id": 123}, "text": "/start"}}
    with patch("app.main.send_message", new_callable=AsyncMock) as send_message:
        asyncio.run(handle_update(update))

    send_message.assert_awaited_once_with(123, START_TEXT, reply_markup=START_MENU)


def test_help_button_sends_help_text():
    import asyncio

    from app.main import handle_update

    update = {"message": {"chat": {"id": 123}, "text": "ℹ️ طريقة الاستخدام"}}
    with patch("app.main.send_message", new_callable=AsyncMock) as send_message:
        asyncio.run(handle_update(update))

    send_message.assert_awaited_once_with(123, HELP_TEXT, reply_markup=START_MENU)


def test_process_download_reports_configured_limit(tmp_path):
    import asyncio
    from pathlib import Path
    from unittest.mock import Mock, patch
    from app.download_engine import DownloadResult
    from app.media_tools import MediaProbeResult
    from app.telegram_api import TelegramFileTooLargeError
    from app.main import process_download_and_send

    video = tmp_path / "too-large.mp4"
    video.write_bytes(b"x")
    result = DownloadResult(
        job_id="job-1", file_path=video, target_height=480, selected_format="398+140",
        estimated_size=None, actual_size=2100 * 1024 * 1024, exceeds_planning_limit=True,
        probe=MediaProbeResult(video, 2100 * 1024 * 1024, 10.0),
    )
    with patch("app.main.settings.download_root", str(tmp_path)), patch(
        "app.main.send_message", new_callable=AsyncMock
    ) as send_message, patch(
        "app.main.coordinator.download", new=Mock(return_value=Mock(result=result, fallback_count=1, attempted_heights=(1080,480), available_heights=(1080,480)))
    ), patch(
        "app.main.send_video", new=AsyncMock(side_effect=TelegramFileTooLargeError(video, 2100 * 1024 * 1024, 2000 * 1024 * 1024))
    ), patch("app.main.settings.telegram_local_mode", True), patch(
        "app.main.settings.telegram_max_upload_mb", 2000
    ):
        asyncio.run(process_download_and_send(123, "https://example.com/video", "job-1"))

    texts = [call.args[1] for call in send_message.await_args_list if len(call.args) > 1]
    assert any("2000 MB" in text for text in texts)
