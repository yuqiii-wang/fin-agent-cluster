from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    ARK_API_KEY: str
    ARK_BASE_URL: str
    ARK_MODEL: str
    DATABASE_URL: str
    FASTAPI_PORT: int = 8432

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
