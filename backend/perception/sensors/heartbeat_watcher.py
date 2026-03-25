"""Poll wearable watch HTTP endpoints for officer BPM; fire /trigger on anomalies."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import httpx

from backend.config import settings

logger = logging.getLogger("security_ai.perception.heartbeat")


StatusKind = Literal["normal", "elevated", "no_signal", "flat_line", "no_reading"]


class HeartbeatWatcher:
    """Background poller for one officer's watch endpoint."""

    def __init__(
        self,
        device_poll_url: str,
        officer_id: str,
        poll_interval_seconds: float | None = None,
    ):
        self.device_poll_url = device_poll_url.strip()
        self.officer_id = officer_id.strip()
        self.poll_interval_seconds = float(
            poll_interval_seconds if poll_interval_seconds is not None else settings.HEARTBEAT_POLL_INTERVAL_SECONDS
        )
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: dict[str, Any] = {
            "bpm": None,
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "no_signal",
        }
        self._simulate_flatline = False

        self._consecutive_no_reading = 0
        self._consecutive_flat = 0
        self._elevated_since: float | None = None
        self._last_trigger_monotonic: float = 0.0

        self._no_signal_threshold = max(1, int(settings.HEARTBEAT_NO_SIGNAL_THRESHOLD))
        self._flat_threshold = max(1, int(settings.HEARTBEAT_FLAT_LINE_THRESHOLD))
        self._elevated_bpm = max(1, int(settings.HEARTBEAT_ELEVATED_BPM))
        self._elevated_duration = float(settings.HEARTBEAT_ELEVATED_DURATION_SECONDS)
        self._cooldown = float(settings.HEARTBEAT_TRIGGER_COOLDOWN_SECONDS)

    def simulate_flatline(self) -> None:
        """Demo: next poll treats BPM as 0 (no HTTP needed)."""
        with self._lock:
            self._simulate_flatline = True

    def _classify_heartbeat(self, bpm: int | None) -> StatusKind:
        if bpm is None:
            return "no_reading"
        if bpm == 0 or bpm < 40:
            return "flat_line"
        if bpm > self._elevated_bpm:
            return "elevated"
        return "normal"

    def get_latest_reading(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=f"HeartbeatWatcher-{self.officer_id[:8]}", daemon=True)
        self._thread.start()
        logger.info("Heartbeat watcher started officer_id=%s url=%s", self.officer_id, self.device_poll_url)

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=self.poll_interval_seconds + 2.0)
        self._thread = None
        logger.info("Heartbeat watcher stopped officer_id=%s", self.officer_id)

    def _fetch_reading(self, client: httpx.Client) -> tuple[int | None, str | None]:
        if self._simulate_flatline:
            with self._lock:
                self._simulate_flatline = False
            return 0, None

        try:
            r = client.get(self.device_poll_url, timeout=10.0)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.debug("Heartbeat poll failed: %s", e)
            return None, None

        bpm: int | None = None
        if isinstance(data, dict):
            for key in ("bpm", "heart_rate", "hr", "heartbeat"):
                if key in data and data[key] is not None:
                    try:
                        bpm = int(data[key])
                        break
                    except (TypeError, ValueError):
                        pass
            zone = data.get("zone") or data.get("location") or data.get("officer_last_seen_zone")
            z = str(zone).strip() if zone else None
            return bpm, z
        return None, None

    def _zone_from_state(self, zone: str | None) -> str:
        if zone and zone.strip():
            return zone.strip()
        with self._lock:
            z = self._latest.get("zone")
        if isinstance(z, str) and z.strip():
            return z.strip()
        return "Unknown zone"

    def _post_trigger(self, body: dict[str, Any]) -> None:
        url = f"{settings.TRIGGER_API_BASE_URL.rstrip('/')}/trigger"
        try:
            with httpx.Client(timeout=30.0) as c:
                r = c.post(url, json=body)
                r.raise_for_status()
            logger.warning("Heartbeat trigger posted: %s", body.get("incident_type_hint"))
        except Exception as e:
            logger.exception("Heartbeat trigger POST failed: %s", e)

    def _maybe_fire(
        self,
        *,
        incident_type_hint: str,
        heartbeat_status: str,
        bpm: int | None,
        zone: str,
        confidence: float,
    ) -> None:
        now_m = time.monotonic()
        if now_m - self._last_trigger_monotonic < self._cooldown:
            return
        self._last_trigger_monotonic = now_m

        ts = datetime.now(UTC).isoformat()
        source_id = f"watch-{self.officer_id}-{uuid4().hex[:8]}"
        body: dict[str, Any] = {
            "source_id": source_id,
            "feed_source": "live",
            "source_type": "watch_heartbeat",
            "incident_type_hint": incident_type_hint,
            "location": zone,
            "timestamp": ts,
            "evidence_refs": [],
            "confidence_score": confidence,
            "user_id": self.officer_id,
            "officer_id": self.officer_id,
            "bpm": bpm,
            "heartbeat_status": heartbeat_status,
            "officer_last_seen_zone": zone,
        }
        self._post_trigger(body)

    def _loop(self) -> None:
        last_zone: str | None = None
        with httpx.Client() as client:
            while not self._stop.is_set():
                bpm, z = self._fetch_reading(client)
                if z:
                    last_zone = z

                kind = self._classify_heartbeat(bpm)
                ts = datetime.now(UTC).isoformat()
                display_status: Literal["normal", "elevated", "no_signal", "flat_line"]
                if kind == "no_reading":
                    display_status = "no_signal"
                elif kind == "flat_line":
                    display_status = "flat_line"
                elif kind == "elevated":
                    display_status = "elevated"
                else:
                    display_status = "normal"

                with self._lock:
                    self._latest = {
                        "bpm": bpm,
                        "timestamp": ts,
                        "status": display_status,
                        "zone": last_zone,
                    }

                zone = self._zone_from_state(last_zone)

                if kind == "no_reading":
                    self._consecutive_no_reading += 1
                    self._consecutive_flat = 0
                    self._elevated_since = None
                    if self._consecutive_no_reading >= self._no_signal_threshold:
                        self._maybe_fire(
                            incident_type_hint="officer_down",
                            heartbeat_status="no_signal",
                            bpm=bpm,
                            zone=zone,
                            confidence=1.0,
                        )
                        self._consecutive_no_reading = 0
                elif kind == "flat_line":
                    self._consecutive_flat += 1
                    self._consecutive_no_reading = 0
                    self._elevated_since = None
                    if self._consecutive_flat >= self._flat_threshold:
                        self._maybe_fire(
                            incident_type_hint="officer_down",
                            heartbeat_status="flat_line",
                            bpm=bpm,
                            zone=zone,
                            confidence=1.0,
                        )
                        self._consecutive_flat = 0
                elif kind == "elevated":
                    self._consecutive_no_reading = 0
                    self._consecutive_flat = 0
                    now_m = time.monotonic()
                    if self._elevated_since is None:
                        self._elevated_since = now_m
                    elif now_m - self._elevated_since >= self._elevated_duration:
                        logger.info("Elevated BPM sustained >= %ss for officer %s", self._elevated_duration, self.officer_id)
                        self._maybe_fire(
                            incident_type_hint="officer_distress",
                            heartbeat_status="elevated",
                            bpm=bpm,
                            zone=zone,
                            confidence=0.9,
                        )
                        self._elevated_since = now_m
                else:
                    self._consecutive_no_reading = 0
                    self._consecutive_flat = 0
                    self._elevated_since = None

                self._stop.wait(self.poll_interval_seconds)
