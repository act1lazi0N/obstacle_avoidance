# AutoCar

Xe tự hành tránh vật cản dùng Raspberry Pi, camera Pi, cảm biến siêu âm HC-SR04 và YOLOv5. Hệ thống được tách làm 2 phần:

- Raspberry Pi chạy API phần cứng để đọc camera, đọc khoảng cách và điều khiển motor.
- Laptop/PC chạy AI controller để phân tích ảnh, lập kế hoạch di chuyển và hiển thị dashboard web.

## Kiến trúc hiện tại

```text
Raspberry Pi                                    Laptop / PC
-----------------------------                  -----------------------------------
Rasberry_pi/robot_server.py   <--- HTTP --->   Car_Server/ai_controller.py
- PiCamera2                                      - Flask dashboard (:8080)
- L298N motor driver                             - YOLOv5 inference
- HC-SR04                                        - Corridor scoring
- /snapshot                                      - FSM planner
- /distance                                      - Command deduplication
- /control?cmd=...&speed=...                    - State/log telemetry
```

Luồng điều khiển chính:

1. `robot_server.py` chụp ảnh JPEG qua `/snapshot`.
2. `ai_controller.py` lấy ảnh và khoảng cách từ Pi.
3. `perception.py` chạy YOLO, chấm điểm hành lang trái/giữa/phải.
4. `fsm_planner.py` quyết định trạng thái lái.
5. `car_client.py` gửi lệnh HTTP đến Pi và tránh gửi lệnh trùng lặp liên tục.

## Tính năng nổi bật

- Tránh vật cản bằng YOLOv5 kết hợp cảm biến siêu âm.
- HC-SR04 là lớp an toàn phía trước ưu tiên cao hơn camera.
- FSM rõ ràng với các trạng thái: `IDLE`, `FORWARD`, `BRAKE`, `REVERSE`, `TURN`, `STUCK`.
- Hysteresis cho ngưỡng khoảng cách để tránh giật trạng thái khi số đo dao động.
- Chọn hướng rẽ theo `left_score` và `right_score`, không chỉ theo box lớn nhất.
- Phát hiện kẹt với `stuck_count` và thoát kẹt bằng quay đầu luân phiên trái/phải.
- Không spam cùng một lệnh motor ở mọi frame.
- Ghi log mọi lần chuyển trạng thái với khoảng cách, điểm ảnh và lệnh gửi đi.
- Pi có watchdog tự dừng nếu mất lệnh điều khiển quá lâu.

## Cấu trúc thư mục

```text
AutoCar/
├── Car_Server/
│   ├── ai_controller.py
│   ├── car_client.py
│   ├── perception.py
│   ├── fsm_planner.py
│   ├── collect_data.py
│   ├── requirement.txt
│   ├── models/
│   │   └── best.pt
│   └── templates/
│       └── index.html
├── Rasberry_pi/
│   ├── robot_server.py
│   ├── hardware_test.py
│   └── requirement.txt
├── Stimulation/
│   └── mock_pi_server.py
├── LABELLING.md
├── TESTFILE.md
└── README.md
```

Ghi chú:

- `Car_Server/` và `Rasberry_pi/` là đường chạy HTTP đang dùng trực tiếp.

## Yêu cầu phần cứng

- Raspberry Pi có camera tương thích `picamera2`
- Driver motor L298N
- 2 motor DC
- HC-SR04
- Nguồn ổn định cho Pi và motor
- Laptop/PC để chạy AI controller

## Sơ đồ chân GPIO

### L298N

| Chân  | GPIO BCM | Vai trò          |
| ----- | -------: | ---------------- |
| `ENA` |       25 | PWM motor trái   |
| `IN1` |       24 | Chiều motor trái |
| `IN2` |       23 | Chiều motor trái |
| `ENB` |       17 | PWM motor phải   |
| `IN3` |       27 | Chiều motor phải |
| `IN4` |       22 | Chiều motor phải |

### HC-SR04

| Chân   | GPIO BCM | Ghi chú                           |
| ------ | -------: | --------------------------------- |
| `TRIG` |        5 | Output                            |
| `ECHO` |        6 | Input, cần hạ áp từ 5V xuống 3.3V |

## Chuẩn bị môi trường

### 1. Trên Raspberry Pi

Cài gói hệ thống:

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-flask python3-opencv
```

Nếu cần, cài thêm các thư viện Python trong file requirements:

```bash
cd Rasberry_pi
pip3 install -r requirement.txt
```

### 2. Trên Laptop / PC

```bash
cd Car_Server
pip install -r requirement.txt
```

### 3. Tạo file `.env`

Tạo file `.env` ở thư mục gốc repo:

```env
CAR_IP=192.168.1.105
```

Nếu chạy mô phỏng trên chính máy tính:

```env
CAR_IP=127.0.0.1
```

## Chạy với Raspberry Pi thật

### Bước 1. Khởi động server phần cứng trên Pi

```bash
cd Rasberry_pi
python3 robot_server.py
```

Server mở ở `http://0.0.0.0:5000` với các API:

- `/snapshot`
- `/video_feed`
- `/distance`
- `/control?cmd=go|backward|stop|left|right&speed=50`

### Bước 2. Khởi động AI controller trên Laptop / PC

```bash
cd Car_Server
python ai_controller.py
```

Mở dashboard:

```text
http://127.0.0.1:8080
```

### Bước 3. Bật AI trên dashboard

- Mở trình duyệt tới `:8080`
- Kiểm tra camera feed, trạng thái kết nối và log
- Nhấn nút start để cho xe chạy tự động

## Chạy mô phỏng không cần Raspberry Pi

Đây là cách nhanh nhất để kiểm tra pipeline AI và giao diện web.

### Bước 1. Trỏ `.env` về localhost

```env
CAR_IP=127.0.0.1
```

### Bước 2. Chạy mock Pi server

```bash
cd Stimulation
python mock_pi_server.py
```

Mock server sẽ:

- Dùng webcam laptop nếu có
- Nếu không có webcam thì tự sinh ảnh giả
- In lệnh motor ra console thay vì điều khiển GPIO thật

### Bước 3. Chạy AI controller

```bash
cd Car_Server
python ai_controller.py
```

### Bước 4. Mở dashboard

```text
http://127.0.0.1:8080
```

## Thu thập dữ liệu ảnh

Script `Car_Server/collect_data.py` dùng để chụp liên tục ảnh từ endpoint `/snapshot` và lưu vào `dataset_images/`.

Chạy:

```bash
cd Car_Server
python collect_data.py
```

Nhấn `q` để dừng.

## Logic điều hướng

### Perception

`Car_Server/perception.py` hiện làm các việc sau:

- Đo độ sáng để phát hiện camera bị che hoặc quá tối
- Chạy YOLOv5 với `models/best.pt`
- Chia ảnh thành 3 hành lang `left`, `center`, `right`
- Tính `left_score`, `center_score`, `right_score` từ vùng box chồng lấp, độ tin cậy và vị trí dọc ảnh
- Tạo cờ `visual_danger`, `visual_dead_end`, `aeb_triggered`

### Planning

`Car_Server/fsm_planner.py` hiện dùng:

- Khoảng cách siêu âm làm lớp ưu tiên cao cho `BRAKE`, `REVERSE`, `TURN`
- Hysteresis để tránh nhảy trạng thái do nhiễu
- `stuck_count` để phát hiện bị lặp né vật cản mà không thoát được
- Hướng quay dựa trên hành lang thoáng hơn

### Command transport

`Car_Server/car_client.py`:

- Gửi lệnh `cmd` và `speed` sang Pi
- Bỏ qua lệnh trùng liên tiếp trong thời gian ngắn
- Lấy ảnh và khoảng cách từ API Pi

## Các endpoint quan trọng

### Raspberry Pi server

| Endpoint                         | Mô tả                          |
| -------------------------------- | ------------------------------ |
| `GET /snapshot`                  | Ảnh JPEG hiện tại              |
| `GET /video_feed`                | MJPEG stream                   |
| `GET /distance`                  | Khoảng cách HC-SR04, đơn vị cm |
| `GET /control?cmd=...&speed=...` | Điều khiển xe                  |

Các lệnh `cmd` hợp lệ:

- `go`
- `backward`
- `stop`
- `left`
- `right`

`speed` nhận giá trị trong khoảng `0..100`. Nếu không truyền, Pi dùng `DEFAULT_SPEED = 50`.

### Dashboard AI

| Endpoint                   | Mô tả               |
| -------------------------- | ------------------- |
| `GET /`                    | Giao diện dashboard |
| `GET /video_feed`          | Video có overlay AI |
| `GET /api/status`          | Telemetry hiện tại  |
| `POST /api/toggle_ai`      | Bật/tắt AI          |
| `POST /api/emergency_stop` | Dừng khẩn cấp       |

## An toàn và lưu ý

- Luôn test `Rasberry_pi/hardware_test.py` trước khi cho xe chạy thật.
- Dùng chung mass giữa Pi, driver motor và nguồn ngoài.
- Với chân `ECHO` của HC-SR04, không đưa trực tiếp 5V vào GPIO Pi.
- Nếu camera bị giữ bởi process cũ, `robot_server.py` có cơ chế dọn pipeline trước khi mở lại.
- Pi sẽ tự dừng motor nếu quá `WATCHDOG_TIMEOUT` giây không nhận lệnh mới.
- Khi chạy thật, nên giảm rủi ro bằng cách thử ở mặt sàn trống, tốc độ thấp và có người giám sát.

## Tài liệu liên quan

- [LABELLING.md](LABELLING.md): ghi nhãn dữ liệu và huấn luyện
- [TESTFILE.md](TESTFILE.md): hướng dẫn test môi trường mô phỏng

## Trạng thái hiện tại

Bản README này mô tả đường chạy HTTP hiện tại của repo:

- `Rasberry_pi/robot_server.py`
- `Car_Server/ai_controller.py`
