from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")
    database_url: str = "sqlite:///./questionnaire.db"
    upload_dir: Path = Path("./data/uploads")
    llm_provider: str = "mock"
    llm_model: str = "mock-grounded-v1"
    embedding_provider: str = "mock"
    embedding_model: str = "mock-hash-v1"
    temperature: float = 0.1
    max_tokens: int = 500
    cors_origins: str = "http://localhost:3000"
settings = Settings()

