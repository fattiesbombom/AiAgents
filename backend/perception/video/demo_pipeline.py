"""Demo pipeline for Android IP Webcam (phone-as-body-worn camera).

Features:
- Live YOLO detections printed to terminal (overlay mode)
- Manual trigger on spacebar
- Saves demo snapshots for every detected threat frame
"""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.config import settings
from backend.perception.video.demo_stream import DemoStreamReader
from backend.perception.video.detector import YOLODetector


class DemoPipeline:
    def __init__(self, phone_ip: str, port: int = 8080):
        self.phone_ip = phone_ip
        self.port = int(port)

        self.reader = DemoStreamReader(phone_ip=self.phone_ip, port=self.port)
        self.detector = YOLODetector(
            model_path=settings.YOLO_MODEL_PATH,
            confidence_threshold=settings.YOLO_CONFIDENCE_THRESHOLD,
        )

        self._running = False
        self._thread: threading.Thread | None = None
        self._key_thread: threading.Thread | None = None
        self._manual_trigger_requested = False
        self._last_trigger_at: float = 0.0

    def manual_trigger(self) -> None:
        self._manual_trigger_requested = True

    def _cooldown_active(self) -> bool:
        return (time.time() - self._last_trigger_at) < float(settings.TRIGGER_COOLDOWN_SECONDS)

    def start(self, demo_overlay: bool = True) -> None:
        test = self.reader.test_connection()
        if not test.ok:
            raise SystemExit(f"[DEMO] Connection failed: {test.message}")
        print(f"[DEMO] Connection OK: {test.message}")

        self._running = True
        self.reader.start()
        self._thread = threading.Thread(target=self._loop, args=(demo_overlay,), daemon=True)
        self._thread.start()
        self._key_thread = threading.Thread(target=self._key_loop, daemon=True)
        self._key_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._key_thread and self._key_thread.is_alive():
            self._key_thread.join(timeout=2.0)
        self.reader.stop()

    def _print_overlay(self, detections: list[dict]) -> None:
        parts = [f"{d.get('label')}:{float(d.get('confidence', 0.0)):.2f}" for d in detections[:10]]
        if parts:
            print("[DEMO][YOLO] " + ", ".join(parts))

    def _post_trigger(
        self,
        client: httpx.Client,
        evidence_path: str,
        confidence: float,
        incident_type_hint: str | None,
        *,
        manual: bool,
    ):
        st = "manual_trigger" if manual else "body_worn"
        label = "Demo manual trigger (mobility)" if manual else "Demo body-worn (IP Webcam)"
        trigger_event: dict[str, Any] = {
            "source_id": "demo-body-worn",
            "feed_source": "live",
            "source_type": st,
            "source_label": label,
            "incident_type_hint": incident_type_hint,
            "location": "demo",
            "timestamp": datetime.now(UTC).isoformat(),
            "evidence_refs": [evidence_path],
            "confidence_score": float(confidence),
        }
        client.post(f"http://{settings.API_HOST}:{settings.API_PORT}/trigger", json=trigger_event)

    def _loop(self, demo_overlay: bool) -> None:
        client = httpx.Client(timeout=10.0)
        try:
            while self._running:
                frame = self.reader.sample_frame()
                if frame is None:
                    time.sleep(0.2)
                    continue

                detections = self.detector.detect(frame)
                if demo_overlay:
                    self._print_overlay(detections)

                manual = self._manual_trigger_requested
                if manual:
                    self._manual_trigger_requested = False

                threat = bool(detections) and self.detector.is_threat_detected(detections)
                max_conf = max((float(d.get("confidence", 0.0)) for d in detections), default=0.0)

                should_trigger = manual or (threat and max_conf >= self.detector.confidence_threshold)
                if should_trigger and not self._cooldown_active():
                    # Save snapshot (DemoStreamReader also copies to demo folder)
                    snapshot_path = self.reader.save_snapshot(frame)

                    # Save every threat frame to demo snapshots (even if cooldown blocks trigger)
                    if threat:
                        try:
                            # Calling save_snapshot already writes to demo folder copy.
                            pass
                        except Exception:
                            pass

                    try:
                        hint = "manual" if manual else None
                        self._post_trigger(
                            client,
                            snapshot_path,
                            max_conf if not manual else 1.0,
                            hint,
                            manual=manual,
                        )
                        self._last_trigger_at = time.time()
                        print("[DEMO] Trigger fired" + (" (manual)" if manual else ""))
                    except Exception as e:
                        print(f"[DEMO] Trigger POST failed: {e}")

                time.sleep(float(settings.FRAME_SAMPLE_INTERVAL_SECONDS))
        finally:
            client.close()

    def _key_loop(self) -> None:
        # Cross-platform minimal key handling:
        # - Windows: msvcrt.getch
        # - Others: fall back to blocking stdin (still usable, just press Enter)
        key = (settings.DEMO_MANUAL_TRIGGER_KEY or "space").lower()

        if os.name == "nt":
            import msvcrt

            while self._running:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch in (b"q", b"Q"):
                        print("[DEMO] Quit requested")
                        self.stop()
                        return
                    if key == "space" and ch == b" ":
                        self.manual_trigger()
                time.sleep(0.05)
        else:
            # Best-effort: type 'space' then Enter, or 'q' then Enter.
            while self._running:
                try:
                    s = input().strip().lower()
                except EOFError:
                    return
                if s == "q":
                    print("[DEMO] Quit requested")
                    self.stop()
                    return
                if s == key:
                    self.manual_trigger()

