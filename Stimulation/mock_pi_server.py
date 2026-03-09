from flask import Flask, Response, request
import cv2
import logging

app = Flask(__name__)

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

def go_forward():
    print("[MOTOR] Đang đi THẲNG (Bánh Trái: TIẾN | Bánh Phải: TIẾN)")

def stop_car():
    print("[MOTOR] Đã DỪNG LẠI")

def turn_left():
    print("[MOTOR] Rẽ TRÁI (Bánh Trái: LÙI | Bánh Phải: TIẾN)")

def turn_right():
    print("[MOTOR] Rẽ PHẢI (Bánh Trái: TIẾN | Bánh Phải: LÙI)")

camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

def generate_frames():
    while True:
        success, frame = camera.read()
        if not success: break
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/control', methods=['GET'])
def control():
    cmd = request.args.get('cmd')
    if cmd == 'go': go_forward()
    elif cmd == 'stop': stop_car()
    elif cmd == 'left': turn_left()
    elif cmd == 'right': turn_right()
    return "OK"

# Chụp ảnh nhanh để tránh bị delay
@app.route('/snapshot')
def snapshot():
    success, frame = camera.read()
    if success:
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        return Response(buffer.tobytes(), mimetype='image/jpeg')
    return "Lỗi Camera", 500

if __name__ == '__main__':
    print("MOCK PI SERVER ĐANG CHẠY. Đợi lệnh từ server...")
    app.run(host='127.0.0.1', port=5000, threaded=True)