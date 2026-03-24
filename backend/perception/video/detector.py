"""YOLO object detector wrapper using ultralytics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from ultralytics import YOLO

from backend.config import settings


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    bbox: list[float]  # [x1, y1, x2, y2]


class YOLODetector:
    def __init__(self, model_path: str, confidence_threshold: float = 0.5):
        self.model_path = model_path
        self.confidence_threshold = float(confidence_threshold)
        self._model = YOLO(model_path)

        self.threat_labels = [
            s.strip().lower() for s in settings.YOLO_THREAT_LABELS.split(",") if s.strip()
        ]

    def detect(self, frame: np.ndarray) -> list[dict]:
        results = self._model.predict(frame, conf=self.confidence_threshold, verbose=False)
        if not results:
            return []

        r0 = results[0]
        names: dict[int, str] = getattr(r0, "names", {}) or {}
        boxes = getattr(r0, "boxes", None)
        if boxes is None:
            return []

        dets: list[dict[str, Any]] = []
        for b in boxes:
            conf = float(getattr(b, "conf", 0.0))
            if conf < self.confidence_threshold:
                continue
            cls = int(getattr(b, "cls", -1))
            label = names.get(cls, str(cls)).lower()
            xyxy = getattr(b, "xyxy", None)
            if xyxy is None:
                continue
            bbox = [float(v) for v in xyxy[0].tolist()]
            dets.append({"label": label, "confidence": conf, "bbox": bbox})

        return dets

    def is_threat_detected(self, detections: list[dict]) -> bool:
        for d in detections:
            label = str(d.get("label", "")).lower()
            if label in self.threat_labels:
                return True
        return False

