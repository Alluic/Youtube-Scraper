from pathlib import Path

from youtube_digest.config import AppConfig, load_config, write_config


def test_config_round_trip(tmp_path: Path) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        telegram_chat_id="-12345",
        include_channels=("Macro Channel",),
        exclude_keywords=("sports",),
    )
    path = write_config(config)

    loaded = load_config(path)

    assert loaded.data_dir == tmp_path.resolve()
    assert loaded.telegram_chat_id == "-12345"
    assert loaded.include_channels == ("Macro Channel",)
    assert loaded.exclude_keywords == ("sports",)
    assert loaded.database_path == tmp_path / "digest.db"
