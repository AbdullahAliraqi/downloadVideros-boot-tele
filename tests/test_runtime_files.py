from pathlib import Path


def test_lightweight_runtime_files_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "app/config.py",
        "app/main.py",
        "app/media_tools.py",
        "app/download_engine.py",
        "app/download_coordinator.py",
        "app/video_analyzer.py",
        "app/video_service.py",
        "wsgi.py",
        "Dockerfile",
        "nixpacks.toml",
        "cookies.txt",
        "docker-compose.yml",
    ):
        assert (root / relative).is_file()
