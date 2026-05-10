"""
AutoCar — Brightness Analyzer

Analyzes frame brightness to detect camera failures or very dark environments.
"""

import logging
import numpy as np
import cv2

from shared.config import BRIGHTNESS_THRESHOLD

logger = logging.getLogger(__name__)


def analyze_brightness(frame: np.ndarray) -> tuple[float, bool]:
    """
    Compute mean brightness and check if camera is "blind".

    Args:
        frame: BGR numpy array

    Returns:
        (mean_brightness, is_too_dark) tuple
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_brightness = float(gray.mean())
    is_too_dark = mean_brightness < BRIGHTNESS_THRESHOLD
    return mean_brightness, is_too_dark
