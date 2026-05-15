"""
AutoCar — Obstacle Detector (YOLOv5)

Wraps YOLOv5 inference to detect obstacles in camera frames.
Produces structured detection results with bounding boxes, areas,
and spatial classification (left/center/right).
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
import torch

from shared.config import (
    MODEL_CONFIDENCE,
    CAMERA_WIDTH,
    CAMERA_HEIGHT,
)

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Single object detection result."""
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    class_name: str
    area: int = 0
    region: str = "center"  # "left", "center", "right"

    def __post_init__(self):
        self.area = (self.x2 - self.x1) * (self.y2 - self.y1)
        # Determine region based on x center
        cx = (self.x1 + self.x2) / 2
        third = CAMERA_WIDTH / 3
        if cx < third:
            self.region = "left"
        elif cx > 2 * third:
            self.region = "right"
        else:
            self.region = "center"


@dataclass
class DetectionResult:
    """Aggregated detection results for a single frame."""
    detections: list[Detection] = field(default_factory=list)
    max_area: int = 0
    dominant_region: str = "center"
    obstacle_count: int = 0
    total_area: int = 0
    annotated_frame: Optional[np.ndarray] = None

    @property
    def has_obstacles(self) -> bool:
        return self.obstacle_count > 0


class ObstacleDetector:
    """
    YOLOv5-based obstacle detector.

    Loads a local YOLOv5 model and runs inference on grayscale frames.
    Produces DetectionResult with spatial analysis.
    """

    def __init__(self, model_path: str = "yolov5s.pt"):
        self._model = None
        self._model_path = model_path
        self._initialized = False

    def setup(self) -> None:
        """Load the YOLOv5 model."""
        import pathlib
        import platform

        if (
            not os.path.exists(self._model_path)
            or os.path.getsize(self._model_path) == 0
        ):
            logger.warning(
                "[DETECTOR] Model weights missing or empty: %s. "
                "Using empty detections.",
                self._model_path,
            )
            return

        is_windows = platform.system() == "Windows"
        if is_windows:
            temp = pathlib.PosixPath
            pathlib.PosixPath = pathlib.WindowsPath

        try:
            self._model = torch.hub.load(
                "ultralytics/yolov5", "custom",
                path=self._model_path,
                force_reload=False,
            )
            self._model.conf = MODEL_CONFIDENCE
            self._model.iou = 0.45
            self._initialized = True
            logger.info(f"[DETECTOR] YOLOv5 loaded from {self._model_path}")
        except Exception as e:
            logger.error(f"[DETECTOR] Failed to load model: {e}")
            raise
        finally:
            if is_windows:
                pathlib.PosixPath = temp

    def detect(self, frame: np.ndarray) -> DetectionResult:
        """
        Run obstacle detection on a BGR frame.

        Args:
            frame: BGR numpy array (H x W x 3)

        Returns:
            DetectionResult with all detections and analysis.
        """
        if not self._initialized or self._model is None:
            return DetectionResult()

        results = self._model(frame)
        df = results.pandas().xyxy[0]

        detections = []
        for _, row in df.iterrows():
            det = Detection(
                x1=int(row["xmin"]),
                y1=int(row["ymin"]),
                x2=int(row["xmax"]),
                y2=int(row["ymax"]),
                confidence=float(row["confidence"]),
                class_name=str(row["name"]),
            )
            detections.append(det)

        # Aggregation
        result = DetectionResult(
            detections=detections,
            obstacle_count=len(detections),
        )

        if detections:
            result.max_area = max(d.area for d in detections)
            result.total_area = sum(d.area for d in detections)

            # Dominant region = region of largest obstacle
            largest = max(detections, key=lambda d: d.area)
            result.dominant_region = largest.region

        # Annotate frame for debugging/dashboard
        annotated = frame.copy()
        for det in detections:
            color = (0, 0, 255) if det.area > 5000 else (0, 255, 255)
            cv2.rectangle(
                annotated, (det.x1, det.y1), (det.x2, det.y2),
                color, 2,
            )
            label = f"{det.class_name} {det.confidence:.1%}"
            cv2.putText(
                annotated, label, (det.x1, det.y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1,
            )
        result.annotated_frame = annotated

        return result

    @property
    def is_ready(self) -> bool:
        return self._initialized
