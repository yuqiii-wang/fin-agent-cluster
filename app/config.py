from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    ARK_API_KEY: str
    ARK_BASE_URL: str
    ARK_MODEL: str
    DATABASE_URL: str
    FASTAPI_PORT: int = 8432

    # Financial Modeling Prep
    FMP_API_KEY: str = ""
    FMP_BASE_URL: str = "https://financialmodelingprep.com"

    # Debug mode — enable 1-hour external-resource cache for all quant API calls
    DEBUG: bool = False

    # LLM provider: "ark" | "openai" | "llamacpp"
    LLM_PROVIDER: str = "ark"
    LLAMACPP_MODEL_PATH: Optional[str] = None
    LLAMACPP_N_CTX: int = 4096
    LLAMACPP_N_GPU_LAYERS: int = -1

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
