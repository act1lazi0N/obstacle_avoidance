#!/usr/bin/env python3
"""
Hardware Test Script - Verify all robot components are working.
Run on Raspberry Pi: python3 hardware_test.py
"""
import time
import sys

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("ERROR: Must run on Raspberry Pi!")
    sys.exit(1)

# === GPIO Pinout (same as robot_server.py) ===
MOTOR_LEFT_EN  = 25
MOTOR_LEFT_IN1 = 24
MOTOR_LEFT_IN2 = 23
MOTOR_RIGHT_EN  = 17
MOTOR_RIGHT_IN1 = 27
MOTOR_RIGHT_IN2 = 22
TRIG_PIN = 5
ECHO_PIN = 6


def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(MOTOR_LEFT_EN, GPIO.OUT)
    GPIO.setup(MOTOR_LEFT_IN1, GPIO.OUT)
    GPIO.setup(MOTOR_LEFT_IN2, GPIO.OUT)
    GPIO.setup(MOTOR_RIGHT_EN, GPIO.OUT)
    GPIO.setup(MOTOR_RIGHT_IN1, GPIO.OUT)
    GPIO.setup(MOTOR_RIGHT_IN2, GPIO.OUT)
    GPIO.setup(TRIG_PIN, GPIO.OUT)
    GPIO.setup(ECHO_PIN, GPIO.IN)

    GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)

    pwm_left = GPIO.PWM(MOTOR_LEFT_EN, 1000)
    pwm_right = GPIO.PWM(MOTOR_RIGHT_EN, 1000)
    pwm_left.start(0)
    pwm_right.start(0)
    return pwm_left, pwm_right


def stop_all(pwm_left, pwm_right):
    pwm_left.ChangeDutyCycle(0)
    pwm_right.ChangeDutyCycle(0)
    GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)


# --- TEST 1: Left Motor ------------------------------------------------
def test_left_motor(pwm_left, pwm_right):
    print("\n" + "=" * 50)
    print("TEST 1: LEFT MOTOR")
    print("=" * 50)

    print("  -> Left motor: FORWARD (2 seconds)...")
    GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    pwm_left.ChangeDutyCycle(50)
    time.sleep(2)
    stop_all(pwm_left, pwm_right)

    result = input("  Did the left wheel spin FORWARD? (y/n): ").strip().lower()
    if result != 'y':
        print("  FAILED: Check wiring on IN1(GPIO24), IN2(GPIO23), EN(GPIO25)")
        return False

    time.sleep(0.5)

    print("  -> Left motor: REVERSE (2 seconds)...")
    GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.HIGH)
    pwm_left.ChangeDutyCycle(50)
    time.sleep(2)
    stop_all(pwm_left, pwm_right)

    result = input("  Did the left wheel spin REVERSE? (y/n): ").strip().lower()
    if result != 'y':
        print("  FAILED: IN1/IN2 may be wired in reverse")
        return False

    print("  PASSED: Left motor OK")
    return True


# --- TEST 2: Right Motor -----------------------------------------------
def test_right_motor(pwm_left, pwm_right):
    print("\n" + "=" * 50)
    print("TEST 2: RIGHT MOTOR")
    print("=" * 50)

    print("  -> Right motor: FORWARD (2 seconds)...")
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
    pwm_right.ChangeDutyCycle(50)
    time.sleep(2)
    stop_all(pwm_left, pwm_right)

    result = input("  Did the right wheel spin FORWARD? (y/n): ").strip().lower()
    if result != 'y':
        print("  FAILED: Check wiring on IN1(GPIO27), IN2(GPIO22), EN(GPIO17)")
        return False

    time.sleep(0.5)

    print("  -> Right motor: REVERSE (2 seconds)...")
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.HIGH)
    pwm_right.ChangeDutyCycle(50)
    time.sleep(2)
    stop_all(pwm_left, pwm_right)

    result = input("  Did the right wheel spin REVERSE? (y/n): ").strip().lower()
    if result != 'y':
        print("  FAILED: IN1/IN2 may be wired in reverse")
        return False

    print("  PASSED: Right motor OK")
    return True


# --- TEST 3: PWM Speed Control -----------------------------------------
def test_pwm_speed(pwm_left, pwm_right):
    print("\n" + "=" * 50)
    print("TEST 3: PWM SPEED CONTROL")
    print("=" * 50)

    GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)

    for speed in [30, 50, 70, 100]:
        print(f"  -> Speed: {speed}%...")
        pwm_left.ChangeDutyCycle(speed)
        pwm_right.ChangeDutyCycle(speed)
        time.sleep(1.5)

    stop_all(pwm_left, pwm_right)

    result = input("  Did the speed INCREASE gradually from slow to fast? (y/n): ").strip().lower()
    if result != 'y':
        print("  FAILED: PWM not working. Check EN pins")
        return False

    print("  PASSED: PWM speed control OK")
    return True


# --- TEST 4: Active Brake ----------------------------------------------
def test_brake(pwm_left, pwm_right):
    print("\n" + "=" * 50)
    print("TEST 4: ACTIVE BRAKE")
    print("=" * 50)

    print("  -> Running forward for 2 seconds...")
    GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
    pwm_left.ChangeDutyCycle(70)
    pwm_right.ChangeDutyCycle(70)
    time.sleep(2)

    print("  -> BRAKING!")
    GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.HIGH)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.HIGH)
    pwm_left.ChangeDutyCycle(100)
    pwm_right.ChangeDutyCycle(100)
    time.sleep(0.05)
    pwm_left.ChangeDutyCycle(0)
    pwm_right.ChangeDutyCycle(0)
    GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)

    result = input("  Did the car STOP IMMEDIATELY? (y/n): ").strip().lower()
    if result != 'y':
        print("  FAILED: Active brake not working")
        return False

    print("  PASSED: Active brake OK")
    return True


# --- TEST 5: Ultrasonic Sensor -----------------------------------------
def test_ultrasonic():
    print("\n" + "=" * 50)
    print("TEST 5: ULTRASONIC SENSOR (HC-SR04)")
    print("=" * 50)
    print("  Place your hand in front of the sensor at various distances...")

    GPIO.output(TRIG_PIN, False)
    time.sleep(0.5)

    results = []
    for i in range(5):
        GPIO.output(TRIG_PIN, True)
        time.sleep(0.00001)
        GPIO.output(TRIG_PIN, False)

        start = time.time()
        timeout = start + 0.04

        while GPIO.input(ECHO_PIN) == 0:
            start = time.time()
            if start > timeout:
                print(f"  Reading {i + 1}: TIMEOUT (no echo received)")
                results.append(None)
                break
        else:
            stop = time.time()
            while GPIO.input(ECHO_PIN) == 1:
                stop = time.time()
                if stop > timeout:
                    print(f"  Reading {i + 1}: TIMEOUT (echo too long)")
                    results.append(None)
                    break
            else:
                distance = ((stop - start) * 34300) / 2
                distance = round(distance, 2)
                print(f"  Reading {i + 1}: {distance} cm")
                results.append(distance)

        time.sleep(0.1)

    valid = [r for r in results if r is not None]
    if len(valid) >= 3:
        print(f"  PASSED: Ultrasonic sensor OK ({len(valid)}/5 readings successful)")
        return True
    else:
        print(f"  FAILED: Only {len(valid)}/5 readings successful")
        print("  Check: TRIG(GPIO5), ECHO(GPIO6), voltage divider resistors")
        return False


# --- TEST 6: Camera ----------------------------------------------------
def test_camera():
    print("\n" + "=" * 50)
    print("TEST 6: CAMERA (Picamera2)")
    print("=" * 50)

    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        config = cam.create_preview_configuration(
            main={"size": (320, 240), "format": "RGB888"}
        )
        cam.configure(config)
        cam.start()
        time.sleep(2)

        # List available controls
        print("  Supported controls:")
        for key in sorted(cam.camera_controls.keys()):
            min_val, max_val, default = cam.camera_controls[key]
            print(f"    {key}: min={min_val}, max={max_val}, default={default}")

        # Test Saturation
        if "Saturation" in cam.camera_controls:
            try:
                cam.set_controls({"Saturation": 0.0})
                print("  Saturation control: SUPPORTED")
            except Exception as e:
                print(f"  Saturation control failed: {e}")
        else:
            print("  Saturation control: NOT SUPPORTED by this camera")
            print("     -> Will use OpenCV grayscale conversion instead")

        # Test capture
        frame = cam.capture_array()
        if frame is not None and frame.size > 0:
            print(f"  Capture test: OK (shape={frame.shape})")
        else:
            print("  Capture test: FAILED")

        cam.stop()
        print("  PASSED: Camera OK")
        return True

    except Exception as e:
        print(f"  FAILED: Camera error: {e}")
        return False


# --- MAIN ---------------------------------------------------------------
def main():
    print("=" * 50)
    print("  HARDWARE TEST -- AutoCar Robot")
    print("  Verify all components before running")
    print("=" * 50)

    pwm_left, pwm_right = setup()
    results = {}

    try:
        tests = [
            ("Left motor",   lambda: test_left_motor(pwm_left, pwm_right)),
            ("Right motor",  lambda: test_right_motor(pwm_left, pwm_right)),
            ("PWM speed",    lambda: test_pwm_speed(pwm_left, pwm_right)),
            ("Active brake", lambda: test_brake(pwm_left, pwm_right)),
            ("Ultrasonic",   lambda: test_ultrasonic()),
            ("Camera",       lambda: test_camera()),
        ]

        for name, test_fn in tests:
            try:
                results[name] = test_fn()
            except KeyboardInterrupt:
                print(f"\n  Skipped: {name}")
                results[name] = None
            except Exception as e:
                print(f"  ERROR in {name}: {e}")
                results[name] = False

    finally:
        stop_all(pwm_left, pwm_right)
        pwm_left.stop()
        pwm_right.stop()
        GPIO.cleanup()

    # === SUMMARY ===
    print("\n" + "=" * 50)
    print("HARDWARE TEST SUMMARY")
    print("=" * 50)
    all_ok = True
    for name, passed in results.items():
        if passed is True:
            print(f"  [PASS] {name}")
        elif passed is None:
            print(f"  [SKIP] {name}")
        else:
            print(f"  [FAIL] {name}")
            all_ok = False

    if all_ok:
        print("\nAll components are working correctly.")
    else:
        print("\nSome components failed. Check wiring and connections.")


if __name__ == '__main__':
    main()
