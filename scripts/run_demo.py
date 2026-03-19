"""Run the self-contained Android IP Webcam demo."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


def _load_dotenv() -> None:
    # Optional; project already depends on python-dotenv.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


def _ollama_tags(base_url: str) -> set[str]:
    url = base_url.rstrip("/") + "/api/tags"
    r = httpx.get(url, timeout=5.0)
    r.raise_for_status()
    data = r.json()
    models = set()
    for m in data.get("models", []) if isinstance(data, dict) else []:
        name = m.get("name")
        if isinstance(name, str):
            models.add(name.split(":")[0])
    return models


def main() -> int:
    _load_dotenv()

    phone_ip = os.getenv("PHONE_IP", "").strip()
    phone_port = int(os.getenv("PHONE_PORT", "8080"))
    if not phone_ip:
        print("[DEMO] PHONE_IP is required in your .env")
        return 2

    from backend.config import settings
    from backend.perception.video.demo_stream import DemoStreamReader
    from backend.perception.video.demo_pipeline import DemoPipeline

    # 2) Connection test
    ds = DemoStreamReader(phone_ip=phone_ip, port=phone_port)
    test = ds.test_connection()
    if not test.ok:
        print(f"[DEMO] Connection failed: {test.message}")
        return 2
    print(f"[DEMO] Connection OK: {test.message}")

    # 3) Ollama health check
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    required = {"qwen2.5", "qwen2.5vl", "nomic-embed-text"}
    try:
        present = _ollama_tags(base_url)
    except Exception as e:
        print(f"[DEMO] Ollama not reachable at {base_url}: {e}")
        return 2

    missing = sorted(required - present)
    if missing:
        print("[DEMO] Missing required Ollama models:")
        for m in missing:
            print(f"  - {m}  (run: ollama pull {m})")
        return 2
    print("[DEMO] Ollama models OK: qwen2.5, qwen2.5vl, nomic-embed-text")

    # 4) Start FastAPI backend
    env = os.environ.copy()
    env.setdefault("API_HOST", "127.0.0.1")
    env.setdefault("API_PORT", "8000")

    api_url = f"http://{env['API_HOST']}:{env['API_PORT']}"
    print(f"[DEMO] Starting FastAPI at {api_url}")

    backend_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.api.trigger:app",
            "--host",
            env["API_HOST"],
            "--port",
            env["API_PORT"],
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )

    try:
        # Wait for health endpoint
        for _ in range(40):
            try:
                r = httpx.get(api_url + "/health", timeout=1.0)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        else:
            print("[DEMO] FastAPI did not become healthy in time.")
            return 2

        # 5) Start demo pipeline
        pipe = DemoPipeline(phone_ip=phone_ip, port=phone_port)
        pipe.start(demo_overlay=True)

        # 6) Startup summary
        stream_url = f"http://{phone_ip}:{phone_port}/video"
        print("\n[DEMO] Startup summary")
        print(f"  Phone stream URL: {stream_url}")
        print(f"  FastAPI URL:      {api_url}")
        print("  Ollama models:    OK (qwen2.5, qwen2.5vl, nomic-embed-text)")
        print("  Controls:         spacebar = manually trigger incident, Q = quit\n")

        # Keep running until pipeline stops (Q)
        while True:
            if backend_proc.poll() is not None:
                print("[DEMO] FastAPI process exited.")
                return 2
            time.sleep(0.5)
    finally:
        try:
            backend_proc.terminate()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

