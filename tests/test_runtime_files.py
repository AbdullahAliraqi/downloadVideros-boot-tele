from pathlib import Path


def test_runtime_files_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "app/config.py",
        "app/media_tools.py",
        "app/telegram_api.py",
        "app/polling.py",
        "app/download_engine.py",
        "app/video_service.py",
        "Dockerfile",
        "docker-compose.yml",
    ):
        assert (root / relative).is_file()
