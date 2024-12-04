import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OPENAI_KEY: str
    OPEN_AI_MODEL: str = "gpt-4o-mini"
    DEBUG: bool = False
    SENTRY_DSN: str
    ENVIRONMENT: str = "dev"

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }

settings = Settings()