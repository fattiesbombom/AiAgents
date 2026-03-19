"""Backend configuration loaded from environment variables.

All values are sourced from env vars using pydantic-settings.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    INPUT_DB_URL: str
    OUTPUT_DB_URL: str

    # Supabase Auth (cloud)
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # AI Models (local via Ollama)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "qwen3.5"
    VISION_MODEL: str = "qwen3.5"
    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIMENSIONS: int = 768

    # YOLO
    YOLO_MODEL_PATH: str = "yolov8n.pt"
    YOLO_CONFIDENCE_THRESHOLD: float = 0.5
    YOLO_THREAT_LABELS: list[str] = Field(default_factory=lambda: ["person", "fire", "smoke", "weapon"])

    # Perception
    SNAPSHOT_STORAGE_PATH: str = "./data/snapshots"
    FRAME_SAMPLE_INTERVAL_SECONDS: int = 2
    TRIGGER_COOLDOWN_SECONDS: int = 30

    # FastAPI
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    ALLOWED_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # MCP
    MCP_INPUT_DB_PORT: int = 8001
    MCP_OUTPUT_DB_PORT: int = 8002
    MCP_AUTH_DB_PORT: int = 8003

    # Demo mode — Android IP Webcam
    PHONE_IP: str = ""
    PHONE_PORT: int = 8080
    DEMO_SNAPSHOT_PATH: str = "./data/demo_snapshots"
    DEMO_MANUAL_TRIGGER_KEY: str = "space"

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _parse_allowed_origins(cls, v: Any) -> Any:
        if v is None or v == "":
            return ["http://localhost:5173"]
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("YOLO_THREAT_LABELS", mode="before")
    @classmethod
    def _parse_threat_labels(cls, v: Any) -> Any:
        if v is None or v == "":
            return ["person", "fire", "smoke", "weapon"]
        if isinstance(v, str):
            return [s.strip().lower() for s in v.split(",") if s.strip()]
        return v


settings = Settings()
