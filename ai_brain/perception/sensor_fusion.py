"""
AutoCar — Sensor Fusion

Merges camera-based object detection with ultrasonic distance data
to produce a unified FusedPerception for the Behavior Tree.

This is the single source of truth for the AI brain's understanding
of the environment.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from shared.config import (
    DANGER_AREA_THRESHOLD,
    DEAD_END_AREA_THRESHOLD,
    TTC_EXPANSION_THRESHOLD,
    ULTRASONIC_EMERGENCY_CM,
    ULTRASONIC_DEAD_END_CM,
    ULTRASONIC_DANGER_CM,
    CAMERA_WIDTH,
)
from ai_brain.perception.detector import DetectionResult
from ai_brain.perception.brightness import analyze_brightness

logger = logging.getLogger(__name__)


@dataclass
class FusedPerception:
    """
    Unified perception output from sensor fusion.

    danger_level: 0.0 (clear) → 1.0 (collision imminent)
    """
    # Overall threat assessment
    danger_level: float = 0.0           # 0.0 = clear, 1.0 = critical
    is_dead_end: bool = False           # Blocked in all directions
    is_blind: bool = False              # Camera failure or too dark
    is_collision_imminent: bool = False  # TTC < threshold

    # Spatial analysis (for steering decisions)
    obstacle_region: str = "none"       # "left", "center", "right", "none"
    steer_suggestion: float = 0.0       # -1.0 left, 0.0 straight, +1.0 right
    free_direction: str = "center"      # Where to steer toward

    # Raw sensor data (for logging/dashboard)
    ultrasonic_cm: float = 999.0
    camera_max_area: int = 0
    camera_obstacle_count: int = 0
    brightness: float = 100.0

    # TTC (time-to-collision estimation)
    area_expansion_rate: float = 0.0     # px²/frame (positive = approaching)

    timestamp: float = field(default_factory=time.time)


class SensorFusion:
    """
    Fuses camera (DetectionResult) + ultrasonic (distance_cm) into
    a FusedPerception. Tracks temporal information like TTC.
    """

    def __init__(self):
        self._prev_max_area = 0
        self._prev_time = time.time()

    def fuse(
        self,
        detection: DetectionResult,
        frame,
        ultrasonic_cm: float = 999.0,
    ) -> FusedPerception:
        """
        Produce a fused perception from latest sensor data.

        Args:
            detection:     DetectionResult from obstacle detector
            frame:         Raw BGR frame for brightness analysis
            ultrasonic_cm: Latest ultrasonic distance in cm

        Returns:
            FusedPerception with all threat assessments
        """
        # Brightness
        brightness, is_blind = analyze_brightness(frame)

        # TTC — area expansion rate
        now = time.time()
        dt = now - self._prev_time
        if dt > 0:
            area_rate = (detection.max_area - self._prev_max_area) / dt
        else:
            area_rate = 0.0
        self._prev_max_area = detection.max_area
        self._prev_time = now

        is_collision_imminent = area_rate > TTC_EXPANSION_THRESHOLD

        # ── Danger level calculation (0.0 → 1.0) ─────────────────
        # Camera-based danger
        if detection.max_area >= DEAD_END_AREA_THRESHOLD:
            camera_danger = 1.0
        elif detection.max_area >= DANGER_AREA_THRESHOLD:
            camera_danger = detection.max_area / DEAD_END_AREA_THRESHOLD
        else:
            camera_danger = detection.max_area / DANGER_AREA_THRESHOLD * 0.3

        # Ultrasonic-based danger
        if ultrasonic_cm <= ULTRASONIC_EMERGENCY_CM:
            sonic_danger = 1.0
        elif ultrasonic_cm <= ULTRASONIC_DEAD_END_CM:
            sonic_danger = 0.9
        elif ultrasonic_cm <= ULTRASONIC_DANGER_CM:
            sonic_danger = (ULTRASONIC_DANGER_CM - ultrasonic_cm) / (
                ULTRASONIC_DANGER_CM - ULTRASONIC_DEAD_END_CM
            ) * 0.5 + 0.3
        else:
            sonic_danger = 0.0

        # TTC boost
        ttc_boost = 0.2 if is_collision_imminent else 0.0

        # Merge: take max + TTC bonus
        danger_level = min(1.0, max(camera_danger, sonic_danger) + ttc_boost)

        # ── Dead-end detection ────────────────────────────────────
        is_dead_end = (
            detection.max_area >= DEAD_END_AREA_THRESHOLD
            or ultrasonic_cm <= ULTRASONIC_DEAD_END_CM
        )

        # ── Steering suggestion ───────────────────────────────────
        steer_suggestion, free_direction = self._compute_steering(
            detection, ultrasonic_cm
        )

        return FusedPerception(
            danger_level=round(danger_level, 3),
            is_dead_end=is_dead_end,
            is_blind=is_blind,
            is_collision_imminent=is_collision_imminent,
            obstacle_region=detection.dominant_region if detection.has_obstacles else "none",
            steer_suggestion=round(steer_suggestion, 3),
            free_direction=free_direction,
            ultrasonic_cm=round(ultrasonic_cm, 1),
            camera_max_area=detection.max_area,
            camera_obstacle_count=detection.obstacle_count,
            brightness=round(brightness, 1),
            area_expansion_rate=round(area_rate, 1),
        )

    def _compute_steering(
        self,
        detection: DetectionResult,
        ultrasonic_cm: float,
    ) -> tuple[float, str]:
        """
        Compute steering suggestion based on obstacle distribution.

        Returns:
            (steer_value, free_direction)

        Logic:
            - Obstacle on left → steer right (+)
            - Obstacle on right → steer left (-)
            - Obstacle in center → steer toward side with less area
            - No obstacle → straight (0.0)
        """
        if not detection.has_obstacles:
            return 0.0, "center"

        # Compute total area per region
        left_area = sum(
            d.area for d in detection.detections if d.region == "left"
        )
        center_area = sum(
            d.area for d in detection.detections if d.region == "center"
        )
        right_area = sum(
            d.area for d in detection.detections if d.region == "right"
        )

        # If obstacle mainly in center, choose less blocked side
        if center_area >= left_area and center_area >= right_area:
            if left_area <= right_area:
                return -0.7, "left"
            else:
                return 0.7, "right"

        # Obstacle mainly on left → steer right
        if left_area > right_area:
            intensity = min(1.0, left_area / DANGER_AREA_THRESHOLD)
            return intensity * 0.8, "right"

        # Obstacle mainly on right → steer left
        intensity = min(1.0, right_area / DANGER_AREA_THRESHOLD)
        return -intensity * 0.8, "left"
