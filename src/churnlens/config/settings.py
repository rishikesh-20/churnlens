"""Runtime configuration for all ChurnLens components (D16).

Every entrypoint reads configuration exclusively through ``get_settings()``;
no other module reads environment variables. Precedence: process env >
``.env`` file > coded defaults. All variables use the ``CHURNLENS_`` prefix.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root when running from a checkout — the only supported layout until
# Phase 17 containerizes; containers override paths via CHURNLENS_* env vars.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHURNLENS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    data_dir: Path = _REPO_ROOT / "data"
    reports_dir: Path = _REPO_ROOT / "reports"

    # D2: a customer is churned if no purchase occurs within this window
    # after the snapshot date.
    churn_window_days: int = 90

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def duckdb_path(self) -> Path:
        # D20: one warehouse file, one SQL schema per medallion layer.
        return self.data_dir / "warehouse.duckdb"

    @property
    def bronze_dir(self) -> Path:
        return self.data_dir / "bronze"

    @property
    def silver_dir(self) -> Path:
        return self.data_dir / "silver"

    @property
    def gold_dir(self) -> Path:
        return self.data_dir / "gold"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
