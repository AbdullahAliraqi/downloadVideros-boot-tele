from unittest.mock import patch

from app.main import HELP_TEXT, START_MENU, START_MARKUP, START_TEXT, app


def test_root_returns_blitz_health_message():
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "Bot Service is Active"


def test_health_returns_ok():
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_webhook_rejects_invalid_secret():
    from app.config import settings

    with patch.object(settings, "webhook_secret", "secret"):
        client = app.test_client()
        response = client.post(
            "/webhook",
            json={"update_id": 1, "message": {}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
    assert response.status_code == 403


def test_webhook_queues_valid_update():
    from app.main import runtime

    with patch.object(runtime, "submit_update") as submit:
        client = app.test_client()
        response = client.post(
            "/webhook",
            json={
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "chat": {"id": 123, "type": "private"},
                    "text": "/start",
                },
            },
        )

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "OK"
    submit.assert_called_once()


def test_menu_matches_documented_buttons():
    flattened = [button for row in START_MENU for button in row]
    assert "🏠 Start" in flattened
    assert "🎬 تنزيل فيديو" in flattened
    assert "🌐 المنصات المدعومة" in flattened
    assert "ℹ️ طريقة الاستخدام" in flattened
    assert START_MARKUP.to_dict()["resize_keyboard"] is True


def test_help_text_mentions_50_mb_limit():
    assert "50 MB" in HELP_TEXT
    assert "1080p" in HELP_TEXT
    assert "720p" in HELP_TEXT
    assert "480p" in HELP_TEXT
    assert "Reddit" in START_TEXT
