"""OpenCV video stream reader with background sampling."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

from backend.config import settings


class VideoStreamReader:
    def __init__(self, source_id: str, stream_url: str, feed_source: Literal["live", "remote"]):
        self.source_id = source_id
        self.stream_url = stream_url
        self.feed_source = feed_source

        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._cap = cv2.VideoCapture(self.stream_url)
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=f"VideoStreamReader[{self.source_id}]", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._thread = None

        cap = self._cap
        self._cap = None
        if cap is not None:
            cap.release()

    def _loop(self) -> None:
        assert self._cap is not None
        cap = self._cap

        while self._running:
            ok, frame = cap.read()
            if ok and frame is not None:
                with self._lock:
                    self._latest_frame = frame
            else:
                time.sleep(0.05)

    def sample_frame(self) -> np.ndarray | None:
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def save_snapshot(self, frame: np.ndarray) -> str:
        out_dir = Path(settings.SNAPSHOT_STORAGE_PATH)
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"{self.source_id}_{ts}.jpg"
        path = out_dir / filename

        ok = cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            raise RuntimeError(f"Failed to write snapshot to {path}")
        return str(path)

