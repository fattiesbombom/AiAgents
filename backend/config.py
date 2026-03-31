"""Backend configuration loaded from environment variables.

All values are sourced from env vars using pydantic-settings.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file_paths() -> tuple[str, ...]:
    """Resolve .env from cwd, then repo root (security-ai-system), then parent (e.g. certis/).

    Uvicorn is usually started from security-ai-system/, while .env may live one folder up.
    """
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        Path.cwd() / ".env",
        repo_root / ".env",
        repo_root.parent / ".env",
    ]
    seen: set[Path] = set()
    out: list[str] = []
    for p in candidates:
        resolved = p.resolve()
        if resolved.is_file() and resolved not in seen:
            seen.add(resolved)
            out.append(str(resolved))
    return tuple(out)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_file_paths() or (".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

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
    # Comma-separated in .env (not JSON) — avoids pydantic-settings JSON parse errors
    YOLO_THREAT_LABELS: str = "person,fire,smoke,weapon"

    # Perception
    SNAPSHOT_STORAGE_PATH: str = "./data/snapshots"
    FRAME_SAMPLE_INTERVAL_SECONDS: int = 2
    TRIGGER_COOLDOWN_SECONDS: int = 30

    # Input DB poller (discrete events → POST /trigger; see input_db_watcher)
    INPUT_DB_WATCHER_ENABLED: bool = False
    INPUT_DB_POLL_INTERVAL_SECONDS: float = 5.0
    # Comma-separated: alarm_events, mop_reports, access_logs, motion_events, c2_alerts
    INPUT_DB_TABLES: str = "alarm_events,mop_reports,access_logs"
    # Comma-separated severities to emit (case-insensitive); empty = all severities
    INPUT_DB_ALARM_SEVERITIES: str = ""
    # If true, skip alarm_events rows where acknowledged IS TRUE
    INPUT_DB_ALARM_SKIP_ACKNOWLEDGED: bool = True
    # Comma-separated attempt_result values that should fire a trigger (case-insensitive)
    INPUT_DB_ACCESS_TRIGGER_RESULTS: str = "denied,failed,tailgating,rejected"
    # Minimum motion_events.confidence to trigger when motion_events is enabled (0 = any)
    INPUT_DB_MOTION_MIN_CONFIDENCE: float = 0.0
    # Persist poll cursors to this JSON file; empty = in-memory only (lost on restart)
    INPUT_DB_CURSOR_FILE: str = "./data/input_db_watcher_cursors.json"
    INPUT_DB_POLL_BATCH_SIZE: int = 50

    # Wearable heartbeat watches (HeartbeatWatcher + start_perception_watchers)
    HEARTBEAT_POLL_INTERVAL_SECONDS: float = 5.0
    HEARTBEAT_NO_SIGNAL_THRESHOLD: int = 3
    HEARTBEAT_FLAT_LINE_THRESHOLD: int = 10
    HEARTBEAT_ELEVATED_BPM: int = 140
    HEARTBEAT_ELEVATED_DURATION_SECONDS: float = 60.0
    HEARTBEAT_TRIGGER_COOLDOWN_SECONDS: float = 120.0
    # Comma-separated officer_id|poll_url (e.g. uuid|http://127.0.0.1:9100/health)
    HEARTBEAT_WATCHERS: str = ""
    TRIGGER_API_BASE_URL: str = "http://127.0.0.1:8000"

    # FastAPI
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    # Comma-separated origins in .env (not JSON)
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    # MCP — streamable HTTP on each port (see FastMCP streamable_http_path="/" in *_db_server).
    MCP_INPUT_DB_PORT: int = 8001
    MCP_OUTPUT_DB_PORT: int = 8002
    MCP_AUTH_DB_PORT: int = 8003

    def mcp_input_http_url(self) -> str:
        return f"http://127.0.0.1:{self.MCP_INPUT_DB_PORT}"

    def mcp_output_http_url(self) -> str:
        return f"http://127.0.0.1:{self.MCP_OUTPUT_DB_PORT}"

    def mcp_auth_http_url(self) -> str:
        return f"http://127.0.0.1:{self.MCP_AUTH_DB_PORT}"

    # Demo mode — Android IP Webcam
    PHONE_IP: str = ""
    PHONE_PORT: int = 8080
    DEMO_SNAPSHOT_PATH: str = "./data/demo_snapshots"
    DEMO_MANUAL_TRIGGER_KEY: str = "space"

settings = Settings()
