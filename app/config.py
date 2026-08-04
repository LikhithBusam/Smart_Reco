from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    secret_key: str

    database_url: str
    redis_url: str
    chroma_persist_dir: str = "./data/chroma"

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30

    mesh_api_key: str
    mesh_base_url: str = "https://api.meshapi.ai/v1"
    mesh_chat_model: str = "openai/gpt-4o"
    mesh_embedding_model: str = "openai/text-embedding-3-small"

    trigger_event_threshold: int = 5
    recommendation_ttl_hours: int = 6
    outbox_poll_interval_seconds: int = 5
    event_consumer_poll_interval_seconds: int = 3

    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "smartreco"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    digest_send_hour_utc: int = 14


settings = Settings()
