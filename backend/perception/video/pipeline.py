"""Video pipeline tying together stream reading, YOLO detection, and triggering."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from backend.config import settings
from backend.perception.video.detector import YOLODetector
from backend.perception.video.stream_reader import VideoStreamReader


class VideoPipeline:
    def __init__(
        self,
        source_id: str,
        stream_url: str,
        feed_source: Literal["live", "remote"],
        location: str,
        yolo_model_path: str,
        sample_interval_seconds: float | None = None,
        cooldown_seconds: float | None = None,
        confidence_threshold: float = 0.5,
    ):
        self.source_id = source_id
        self.stream_url = stream_url
        self.feed_source = feed_source
        self.location = location

        self.sample_interval_seconds = float(sample_interval_seconds or settings.FRAME_SAMPLE_INTERVAL_SECONDS)
        self.cooldown_seconds = float(cooldown_seconds or settings.TRIGGER_COOLDOWN_SECONDS)

        self.reader = VideoStreamReader(source_id=source_id, stream_url=stream_url, feed_source=feed_source)
        self.detector = YOLODetector(model_path=yolo_model_path, confidence_threshold=confidence_threshold)

        self._running = False
        self._thread: threading.Thread | None = None
        self._last_trigger_at: float = 0.0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.reader.start()
        self._thread = threading.Thread(target=self._loop, name=f"VideoPipeline[{self.source_id}]", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._thread = None
        self.reader.stop()

    def _cooldown_active(self) -> bool:
        return (time.time() - self._last_trigger_at) < self.cooldown_seconds

    def _loop(self) -> None:
        client = httpx.Client(timeout=10.0)
        try:
            while self._running:
                if self._cooldown_active():
                    time.sleep(0.25)
                    continue

                frame = self.reader.sample_frame()
                if frame is None:
                    time.sleep(0.2)
                    continue

                detections = self.detector.detect(frame)
                if not detections or not self.detector.is_threat_detected(detections):
                    time.sleep(self.sample_interval_seconds)
                    continue

                max_conf = max((float(d.get("confidence", 0.0)) for d in detections), default=0.0)
                if max_conf < self.detector.confidence_threshold:
                    time.sleep(self.sample_interval_seconds)
                    continue

                snapshot_path = self.reader.save_snapshot(frame)

                trigger_event: dict[str, Any] = {
                    "source_id": self.source_id,
                    "feed_source": self.feed_source,
                    "source_type": "video",
                    "incident_type_hint": None,
                    "location": self.location,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "evidence_refs": [snapshot_path],
                    "confidence_score": max_conf,
                }

                try:
                    client.post(f"http://{settings.API_HOST}:{settings.API_PORT}/trigger", json=trigger_event)
                    self._last_trigger_at = time.time()
                except Exception:
                    # Best-effort; pipeline continues.
                    pass

                time.sleep(self.sample_interval_seconds)
        finally:
            client.close()

