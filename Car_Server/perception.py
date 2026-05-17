import pathlib
from dataclasses import dataclass

import cv2
import numpy as np
import torch.hub


@dataclass
class VisualObservation:
    annotated_frame: np.ndarray
    is_blind: bool
    brightness: float
    left_score: float
    center_score: float
    right_score: float
    turn_direction: str
    visual_danger: bool
    visual_dead_end: bool
    aeb_triggered: bool
    current_max_area: int
    area_expansion: int
    detection_count: int


class VisionPerception:
    def __init__(
        self,
        model_path=None,
        model_confidence=0.6,
        brightness_threshold=15.0,
        ttc_expansion_threshold=8000,
        center_danger_threshold=0.16,
        side_danger_threshold=0.22,
        dead_end_center_threshold=0.20,
        dead_end_side_threshold=0.16,
    ):
        self.model_path = model_path or str(pathlib.Path(__file__).resolve().parent / "models" / "best.pt")
        self.model_confidence = model_confidence
        self.brightness_threshold = brightness_threshold
        self.ttc_expansion_threshold = ttc_expansion_threshold
        self.center_danger_threshold = center_danger_threshold
        self.side_danger_threshold = side_danger_threshold
        self.dead_end_center_threshold = dead_end_center_threshold
        self.dead_end_side_threshold = dead_end_side_threshold

    def load_model(self):
        temp = pathlib.PosixPath
        try:
            pathlib.PosixPath = pathlib.WindowsPath
            model = torch.hub.load(
                "ultralytics/yolov5",
                "custom",
                path=self.model_path,
                force_reload=True,
            )
            model.conf = self.model_confidence
            return model
        finally:
            pathlib.PosixPath = temp

    def analyze(self, model, frame, prev_max_area):
        annotated = frame.copy()
        brightness = float(np.mean(frame))
        is_blind = brightness < self.brightness_threshold

        left_score = 0.0
        center_score = 0.0
        right_score = 0.0
        turn_direction = "right"
        current_max_area = 0
        detection_count = 0

        if model is not None and not is_blind:
            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = model(img_rgb)
            df = results.pandas().xyxy[0]

            if not df.empty:
                height, width = frame.shape[:2]
                roi_top = int(height * 0.25)
                corridor_bounds = [
                    ("left", 0, width // 3),
                    ("center", width // 3, (2 * width) // 3),
                    ("right", (2 * width) // 3, width),
                ]
                corridor_area = max(1, (width // 3) * (height - roi_top))
                corridor_scores = {"left": 0.0, "center": 0.0, "right": 0.0}

                for _, row in df.iterrows():
                    x1 = max(0, int(row["xmin"]))
                    y1 = max(0, int(row["ymin"]))
                    x2 = min(width, int(row["xmax"]))
                    y2 = min(height, int(row["ymax"]))
                    if x2 <= x1 or y2 <= y1:
                        continue

                    label = row["name"]
                    confidence = float(row["confidence"])
                    area = int((x2 - x1) * (y2 - y1))
                    current_max_area = max(current_max_area, area)
                    detection_count += 1

                    vertical_bias = 0.65 + 0.9 * ((y2 / max(1, height)) ** 2)
                    confidence_bias = 0.5 + confidence

                    for corridor_name, start_x, end_x in corridor_bounds:
                        overlap_w = max(0, min(x2, end_x) - max(x1, start_x))
                        overlap_h = max(0, min(y2, height) - max(y1, roi_top))
                        if overlap_w == 0 or overlap_h == 0:
                            continue
                        overlap_area = overlap_w * overlap_h
                        contribution = (
                            (overlap_area / corridor_area)
                            * vertical_bias
                            * confidence_bias
                        )
                        if corridor_name == "center":
                            contribution *= 1.15
                        corridor_scores[corridor_name] += contribution

                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(
                        annotated,
                        f"{label} {confidence:.0%} A:{area}",
                        (x1, min(height - 8, y2 + 15)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        (0, 255, 0),
                        1,
                    )

                left_score = min(corridor_scores["left"], 1.5)
                center_score = min(corridor_scores["center"], 1.5)
                right_score = min(corridor_scores["right"], 1.5)

                free_left = max(0.0, 1.0 - left_score)
                free_right = max(0.0, 1.0 - right_score)
                turn_direction = "left" if free_left > free_right else "right"

                for name, start_x, end_x in corridor_bounds:
                    color = (80, 80, 80)
                    if name == "left":
                        color = (255, 200, 0)
                    elif name == "center":
                        color = (0, 200, 255)
                    elif name == "right":
                        color = (255, 0, 255)
                    cv2.line(annotated, (start_x, roi_top), (start_x, height), color, 1)
                    cv2.line(annotated, (end_x, roi_top), (end_x, height), color, 1)

                cv2.putText(
                    annotated,
                    f"L:{left_score:.2f} C:{center_score:.2f} R:{right_score:.2f}",
                    (10, height - 12),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 255, 255),
                    2,
                )

        area_expansion = current_max_area - prev_max_area
        visual_danger = (
            center_score >= self.center_danger_threshold
            or max(left_score, right_score) >= self.side_danger_threshold
        )
        visual_dead_end = (
            center_score >= self.dead_end_center_threshold
            and min(left_score, right_score) >= self.dead_end_side_threshold
        )
        aeb_triggered = (
            prev_max_area > 0
            and area_expansion > self.ttc_expansion_threshold
            and center_score >= self.center_danger_threshold
        )

        if is_blind:
            cv2.putText(
                annotated,
                "CAMERA BLIND",
                (40, 90),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 255),
                2,
            )

        return VisualObservation(
            annotated_frame=annotated,
            is_blind=is_blind,
            brightness=brightness,
            left_score=left_score,
            center_score=center_score,
            right_score=right_score,
            turn_direction=turn_direction,
            visual_danger=visual_danger,
            visual_dead_end=visual_dead_end,
            aeb_triggered=aeb_triggered,
            current_max_area=current_max_area,
            area_expansion=area_expansion,
            detection_count=detection_count,
        )
