from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    kamiwaza_url: str | None = Field(default=None, alias="KAMIWAZA_URL")
    kamiwaza_admin_user: str | None = Field(default=None, alias="KAMIWAZA_ADMIN_USER")
    kamiwaza_admin_password: str | None = Field(default=None, alias="KAMIWAZA_ADMIN_PASSWORD")
    kamiwaza_admin_token: str | None = Field(default=None, alias="KAMIWAZA_ADMIN_TOKEN")

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    stress_tester_profile: str = Field(default="smoke", alias="STRESS_TESTER_PROFILE")
    stress_tester_auto_run: bool = Field(default=False, alias="STRESS_TESTER_AUTO_RUN")
    stress_tester_data_dir: Path = Field(default=Path("./data"), alias="STRESS_TESTER_DATA_DIR")
    stress_tester_port: int = Field(default=18090, alias="STRESS_TESTER_PORT")
    stress_tester_vision_model: str = Field(default="claude-sonnet-4-6", alias="STRESS_TESTER_VISION_MODEL")
    stress_tester_vision_model_complex: str = Field(default="claude-opus-4-6", alias="STRESS_TESTER_VISION_MODEL_COMPLEX")
    stress_tester_max_workers: int = Field(default=20, alias="STRESS_TESTER_MAX_WORKERS")
    stress_tester_screenshot_quality: str = Field(default="png", alias="STRESS_TESTER_SCREENSHOT_QUALITY")
    stress_tester_extension_url: str | None = Field(default=None, alias="STRESS_TESTER_EXTENSION_URL")
    stress_tester_extension_roots: str = Field(
        default="/home/ec2-user/k8s/kamiwaza-extensions-*",
        alias="STRESS_TESTER_EXTENSION_ROOTS",
    )
    stress_tester_guidance_max_files: int = Field(default=12, alias="STRESS_TESTER_GUIDANCE_MAX_FILES")
    stress_tester_guidance_max_chars_per_file: int = Field(
        default=4000, alias="STRESS_TESTER_GUIDANCE_MAX_CHARS_PER_FILE"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
