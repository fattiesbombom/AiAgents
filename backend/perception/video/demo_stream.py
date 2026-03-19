"""Demo stream reader for Android IP Webcam app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np

from backend.config import settings
from backend.perception.video.stream_reader import VideoStreamReader


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    message: str


class DemoStreamReader(VideoStreamReader):
    def __init__(self, phone_ip: str, port: int = 8080):
        self.phone_ip = phone_ip
        self.port = int(port)
        stream_url = f"http://{self.phone_ip}:{self.port}/video"

        print(f"[DEMO] IP Webcam stream URL: {stream_url}")

        super().__init__(source_id="demo-body-worn", stream_url=stream_url, feed_source="live")

    def test_connection(self) -> ConnectionTestResult:
        shot_url = f"http://{self.phone_ip}:{self.port}/shot.jpg"
        try:
            r = httpx.get(shot_url, timeout=5.0)
            if r.status_code != 200:
                return ConnectionTestResult(
                    ok=False,
                    message=f"Phone reachable but returned HTTP {r.status_code} for shot URL: {shot_url}",
                )
            if not r.headers.get("content-type", "").lower().startswith("image/"):
                return ConnectionTestResult(
                    ok=False,
                    message=f"Shot URL did not return an image content-type: {r.headers.get('content-type')} ({shot_url})",
                )
            return ConnectionTestResult(ok=True, message=f"OK: reachable shot URL {shot_url}")
        except Exception as e:
            return ConnectionTestResult(
                ok=False,
                message=(
                    "Cannot reach phone IP Webcam server. "
                    f"Check phone+PC same WiFi, IP/port correct, and server started. Details: {e}"
                ),
            )

    def save_snapshot(self, frame: np.ndarray) -> str:
        # Save the standard snapshot first (used by the pipeline trigger event).
        path = super().save_snapshot(frame)

        # Also save a copy for demo review.
        demo_dir = Path(getattr(settings, "DEMO_SNAPSHOT_PATH", "./data/demo_snapshots"))
        demo_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        demo_path = demo_dir / f"demo_{ts}.jpg"

        # Reuse OpenCV writing from base class by delegating via numpy copy.
        # (We avoid importing cv2 here; base snapshot already exists on disk.)
        try:
            demo_path.write_bytes(Path(path).read_bytes())
        except Exception:
            # Best-effort; keep original snapshot.
            pass

        return path

