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
    uat_profile: str = Field(default="smoke", alias="UAT_PROFILE")
    uat_auto_run: bool = Field(default=False, alias="UAT_AUTO_RUN")
    uat_data_dir: Path = Field(default=Path("./data"), alias="UAT_DATA_DIR")
    uat_port: int = Field(default=18090, alias="UAT_PORT")
    uat_vision_model: str = Field(default="claude-sonnet-4-6", alias="UAT_VISION_MODEL")
    uat_vision_model_complex: str = Field(default="claude-opus-4-6", alias="UAT_VISION_MODEL_COMPLEX")
    uat_max_workers: int = Field(default=20, alias="UAT_MAX_WORKERS")
    uat_screenshot_quality: str = Field(default="png", alias="UAT_SCREENSHOT_QUALITY")
    uat_extension_url: str | None = Field(default=None, alias="UAT_EXTENSION_URL")
    uat_extension_roots: str = Field(
        default="/home/ec2-user/k8s/kamiwaza-extensions-*",
        alias="UAT_EXTENSION_ROOTS",
    )
    uat_guidance_max_files: int = Field(default=12, alias="UAT_GUIDANCE_MAX_FILES")
    uat_guidance_max_chars_per_file: int = Field(
        default=4000, alias="UAT_GUIDANCE_MAX_CHARS_PER_FILE"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
