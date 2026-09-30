"""Environment-backed settings; secrets are never embedded in source."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    dart_api_key: SecretStr | None = None
    fsc_api_key: SecretStr | None = None
    kind_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

@lru_cache
def get_settings() -> Settings:
    return Settings()
