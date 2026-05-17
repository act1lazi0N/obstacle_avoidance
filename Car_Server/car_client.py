import threading
import time

import cv2
import numpy as np
import requests


class CarClient:
    def __init__(
        self,
        pi_ip,
        command_refresh_s=1.0,
        control_timeout_s=0.5,
        snapshot_timeout_s=1.0,
        distance_timeout_s=0.25,
    ):
        self.snapshot_url = f"http://{pi_ip}:5000/snapshot"
        self.control_url = f"http://{pi_ip}:5000/control"
        self.distance_url = f"http://{pi_ip}:5000/distance"
        self.command_refresh_s = command_refresh_s
        self.control_timeout_s = control_timeout_s
        self.snapshot_timeout_s = snapshot_timeout_s
        self.distance_timeout_s = distance_timeout_s
        self._command_lock = threading.Lock()
        self._last_command = None
        self._last_speed = None
        self._last_sent_at = 0.0

    @staticmethod
    def normalize_speed(speed):
        if speed is None:
            return None
        return max(0, min(100, int(round(float(speed)))))

    def send_command(self, cmd, speed=None, force=False):
        normalized_speed = self.normalize_speed(speed)
        now = time.time()

        with self._command_lock:
            is_duplicate = (
                not force
                and cmd == self._last_command
                and normalized_speed == self._last_speed
                and (now - self._last_sent_at) < self.command_refresh_s
            )
            if is_duplicate:
                return True, False

        params = {"cmd": cmd}
        if normalized_speed is not None and cmd != "stop":
            params["speed"] = normalized_speed

        try:
            response = requests.get(
                self.control_url,
                params=params,
                timeout=self.control_timeout_s,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            return False, False
        except Exception:
            return False, False

        with self._command_lock:
            self._last_command = cmd
            self._last_speed = normalized_speed
            self._last_sent_at = now
        return True, True

    def capture_frame(self):
        try:
            response = requests.get(self.snapshot_url, timeout=self.snapshot_timeout_s)
            response.raise_for_status()
            image = np.frombuffer(response.content, dtype=np.uint8)
            return cv2.imdecode(image, cv2.IMREAD_COLOR)
        except Exception:
            return None

    def get_distance(self, default=999.0):
        try:
            response = requests.get(self.distance_url, timeout=self.distance_timeout_s)
            response.raise_for_status()
            return float(response.text)
        except Exception:
            return default

