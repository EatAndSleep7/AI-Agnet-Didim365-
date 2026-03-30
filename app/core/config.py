from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel, Field

class OpikSettings(BaseSettings):
    """Opik configuration."""

    URL_OVERRIDE: str | None = Field(default=None, description="Opik base URL")
    # Optional if you are using Opik Cloud:
    API_KEY: str | None = Field(default=None, description="opik cloud api key here")
    WORKSPACE: str | None = Field(default=None, description="your workspace name")
    PROJECT: str | None = Field(default=None, description="your project name")


class ElasticsearchSettings(BaseModel):
    URL: str = "https://elasticsearch-edu.didim365.app"
    USER: str = "elastic"
    PASSWORD: str = ""
    INDEX: str = "bestbanker-2025"
    CONTENT_FIELD: str = "text"
    TOP_K: int = 5


class Settings(BaseSettings):
    # API 설정
    API_V1_PREFIX: str

    CORS_ORIGINS: List[str] = ["*"]
    
    # IMP: LangChain 객체 및 LLM 연동에 사용되는 필수 설정값(API Key 등)
    # LangChain 설정
    OPENAI_API_KEY: str
    OPENAI_MODEL: str
    
    # Opik 설정 (선택사항)
    OPIK: OpikSettings | None = None
    ES: ElasticsearchSettings = ElasticsearchSettings()
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=True,
        extra="ignore",
    )

settings = Settings()

