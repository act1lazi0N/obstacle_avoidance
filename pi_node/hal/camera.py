"""
AutoCar — Camera HAL (PiCamera2 Wrapper)

Manages PiCamera2 lifecycle with automatic pipeline release,
retry logic, and JPEG encoding for MQTT transport.
"""

import os
import time
import signal
import subprocess
import threading
import logging

import cv2
import numpy as np

from shared.config import (
    CAMERA_WIDTH, CAMERA_HEIGHT, JPEG_QUALITY,
    CAMERA_MAX_RETRIES, CAMERA_RETRY_DELAY,
)

logger = logging.getLogger(__name__)

try:
    from picamera2 import Picamera2
    _HAS_PICAMERA = True
except ImportError:
    _HAS_PICAMERA = False
    logger.warning("picamera2 not available — camera will use mock frames.")


class PiCamera:
    """
    PiCamera2 wrapper with automatic pipeline cleanup and retry.

    On systems without picamera2 (PC), generates mock grayscale frames.
    """

    def __init__(self):
        self._camera = None
        self._lock = threading.Lock()
        self._initialized = False
        self._use_mock = not _HAS_PICAMERA

    def setup(self) -> None:
        """Initialize the camera. Retries on failure."""
        if self._use_mock:
            logger.info("[CAMERA] Mock mode — generating synthetic frames.")
            self._initialized = True
            return

        self._release_stale_pipelines()

        for attempt in range(1, CAMERA_MAX_RETRIES + 1):
            try:
                logger.info(
                    f"[CAMERA] Init attempt {attempt}/{CAMERA_MAX_RETRIES}..."
                )
                self._camera = Picamera2()
                config = self._camera.create_preview_configuration(
                    main={
                        "size": (CAMERA_WIDTH, CAMERA_HEIGHT),
                        "format": "RGB888",
                    }
                )
                self._camera.configure(config)
                self._camera.start()

                # Try grayscale mode via saturation control
                try:
                    self._camera.set_controls({"Saturation": 0.0})
                    logger.info("[CAMERA] Saturation set to 0.0 (grayscale)")
                except Exception as e:
                    logger.warning(
                        f"[CAMERA] Saturation control not available: {e}. "
                        "Will convert via OpenCV."
                    )

                time.sleep(2)  # Let camera stabilize
                self._initialized = True
                logger.info(
                    f"[CAMERA] Ready ({CAMERA_WIDTH}x{CAMERA_HEIGHT})"
                )
                return

            except Exception as e:
                logger.error(
                    f"[CAMERA] Init failed (attempt {attempt}): {e}"
                )
                try:
                    self._camera.close()
                except Exception:
                    pass
                if attempt < CAMERA_MAX_RETRIES:
                    logger.info(f"[CAMERA] Retrying in {CAMERA_RETRY_DELAY}s...")
                    time.sleep(CAMERA_RETRY_DELAY)
                else:
                    logger.critical("[CAMERA] All init attempts failed.")
                    raise

    def capture_frame(self) -> np.ndarray:
        """
        Capture a single frame as a BGR numpy array.

        Returns:
            numpy.ndarray: BGR image (CAMERA_HEIGHT x CAMERA_WIDTH x 3)
        """
        if self._use_mock:
            return self._generate_mock_frame()

        with self._lock:
            frame = self._camera.capture_array()

        # Convert RGB → grayscale → BGR for consistent output
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def capture_jpeg(self) -> bytes:
        """
        Capture a frame and encode as JPEG bytes.

        Returns:
            bytes: JPEG-encoded image data
        """
        frame = self.capture_frame()
        ret, buffer = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )
        if ret:
            return buffer.tobytes()
        logger.error("[CAMERA] JPEG encoding failed.")
        return b""

    def cleanup(self) -> None:
        """Stop and close the camera."""
        if self._camera is not None:
            try:
                self._camera.stop()
                self._camera.close()
                logger.info("[CAMERA] Stopped and closed.")
            except Exception as e:
                logger.warning(f"[CAMERA] Error during cleanup: {e}")
        self._initialized = False

    @property
    def is_ready(self) -> bool:
        return self._initialized

    # ── Private helpers ───────────────────────────────────────────

    def _release_stale_pipelines(self) -> None:
        """
        Kill stale processes holding the libcamera pipeline.
        Necessary when a previous server was killed abruptly.
        """
        my_pid = os.getpid()
        targets = ["libcamera-vid", "libcamera-still", "rpicam"]
        killed = []

        try:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if "PID" in line and "COMMAND" in line:
                    continue
                if any(t in line for t in targets):
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                            if pid != my_pid:
                                os.kill(pid, signal.SIGKILL)
                                killed.append(pid)
                        except (ValueError, ProcessLookupError, PermissionError):
                            pass
        except Exception as e:
            logger.warning(f"[CAMERA] Could not scan for stale processes: {e}")

        if killed:
            logger.info(f"[CAMERA] Killed stale camera processes: {killed}")
            time.sleep(2)  # Wait for kernel to release /dev/video*
        else:
            logger.info("[CAMERA] No stale camera processes found.")

    @staticmethod
    def _generate_mock_frame() -> np.ndarray:
        """Generate a synthetic frame for testing without a camera."""
        frame = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)

        # Gray gradient background (bright enough to pass brightness check)
        for y in range(CAMERA_HEIGHT):
            brightness = int(80 + (y / CAMERA_HEIGHT) * 100)
            frame[y, :] = [brightness, brightness, brightness]

        # Status text
        cv2.putText(
            frame, "MOCK CAMERA", (60, 100),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
        )
        timestamp = time.strftime("%H:%M:%S")
        cv2.putText(
            frame, timestamp, (110, 200),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2,
        )
        return frame
