from pathlib import Path

from churnlens.config.settings import Settings, get_settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.environment == "dev"
    assert s.log_level == "INFO"
    assert s.churn_window_days == 90
    assert s.data_dir.name == "data"


def test_layer_dirs_derive_from_data_dir():
    s = Settings(_env_file=None, data_dir=Path("/tmp/cl"))
    assert s.bronze_dir == Path("/tmp/cl/bronze")
    assert s.silver_dir == Path("/tmp/cl/silver")
    assert s.gold_dir == Path("/tmp/cl/gold")


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("CHURNLENS_ENVIRONMENT", "test")
    monkeypatch.setenv("CHURNLENS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CHURNLENS_DATA_DIR", "/tmp/churnlens-data")
    s = Settings(_env_file=None)
    assert s.environment == "test"
    assert s.log_level == "DEBUG"
    assert s.data_dir == Path("/tmp/churnlens-data")


def test_get_settings_is_cached():
    assert get_settings() is get_settings()
