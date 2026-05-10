# AutoCar — Xe tự hành tránh vật cản thông minh (MQTT + Behavior Tree + YOLOv5)

Dự án xe tự hành sử dụng kiến trúc điện toán phân tán (Microservices) qua giao thức MQTT. Toàn bộ xử lý AI phức tạp và ra quyết định được thực hiện trên **Laptop/PC (AI Brain)** — trong khi **Raspberry Pi (Pi Node)** chỉ đóng vai trò điều khiển phần cứng cấp thấp (FSM) và truyền phát dữ liệu cảm biến.

---

## Kiến trúc hệ thống

Hệ thống được chia thành 4 node hoạt động độc lập, giao tiếp realtime qua MQTT Broker.

```
┌─────────────────────┐       MQTT (Port 1883)      ┌───────────────────────────┐
│  Raspberry Pi Node  │  ◄───────────────────────►  │  Laptop / PC (AI Brain)   │
│                     │       Topic: autocar/#      │                           │
│  • HAL (Motor/Cam)  │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │  • YOLOv5 Detector        │
│  • Motor FSM        │       MQTT Broker           │  • Sensor Fusion          │
│  • MQTT Bridge      │      (Mosquitto)            │  • py_trees Behavior Tree │
└─────────────────────┘             ▲               └───────────────────────────┘
                                    │
                                    ▼
                        ┌───────────────────────────┐
                        │   Web Dashboard (Flask)   │
                        │   • Real-time State       │
                        │   • Port: 8081            │
                        └───────────────────────────┘
```

---

## Tính năng nổi bật

- **Kiến trúc MQTT:** Low latency, phân tách hoàn toàn các thành phần (decoupled).
- **Behavior Tree (Cây hành vi):** Phân chia 7 mức độ ưu tiên từ P0 (Camera hỏng) đến P6 (Đi tự do).
- **Proportional Steering:** Điều khiển vi sai (differential drive) rẽ mềm mại thay vì quay tại chỗ cứng ngắc.
- **Sensor Fusion:** Kết hợp YOLOv5 (Camera) và HC-SR04 (Siêu âm) để tính toán độ nguy hiểm (Danger Level 0.0 → 1.0).
- **Dự đoán va chạm (TTC):** Phanh khẩn cấp (AEB) khi vật cản tiến lại quá nhanh.
- **Thoát ngõ cụt (Escape Maneuver):** Tự động lùi lại, xoay xe và quét tìm đường thoát khi bị chặn hoàn toàn.

---

## Sơ đồ đấu nối phần cứng (GPIO BCM)

### Driver động cơ L298N

| Tên chân | GPIO Pi | Mô tả |
|---|---|---|
| ENA (Motor trái) | GPIO 25 | PWM tốc độ |
| IN1 | GPIO 24 | Chiều quay trái 1 |
| IN2 | GPIO 23 | Chiều quay trái 2 |
| ENB (Motor phải) | GPIO 17 | PWM tốc độ |
| IN3 | GPIO 27 | Chiều quay phải 1 |
| IN4 | GPIO 22 | Chiều quay phải 2 |

### Cảm biến siêu âm HC-SR04

| Chân | GPIO Pi | Lưu ý |
|---|---|---|
| TRIG | GPIO 5 | OUTPUT |
| ECHO | GPIO 6 | INPUT — cần cầu phân áp 5V → 3.3V |

> **⚠️ Quan trọng:** Điều chỉnh mạch giảm áp (Buck Converter) về đúng **5.0V – 5.1V** cho Pi. Tuyệt đối không để vượt quá 5.2V. Nối GND chung giữa Pi và L298N.

---

## Cài đặt môi trường

### 1. Trên Laptop / PC (AI Brain + Broker)

**Cài đặt MQTT Broker (Mosquitto):**
Tải và cài đặt [Mosquitto Broker](https://mosquitto.org/download/).

**Cài đặt thư viện Python:**
Mở Terminal tại thư mục gốc của dự án:
```bash
# Cài đặt thư viện dùng chung
pip install -r requirements.txt

# Cài đặt thư viện cho AI Brain (YOLO, py_trees, torch, v.v.)
pip install -r ai_brain/requirements.txt

# Cài đặt thư viện cho Dashboard
pip install -r web_dashboard/requirements.txt
```

**Cấu hình file `.env` (tạo từ thư mục gốc):**
```env
MQTT_BROKER_IP=127.0.0.1
MQTT_BROKER_PORT=1883
CAR_IP=<IP_của_Raspberry_Pi>
```

### 2. Trên Raspberry Pi (Pi Node)

Cài đặt thư viện:
```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv
pip install -r pi_node/requirements.txt
```

Đảm bảo Pi có kết nối chung mạng WiFi với Laptop và thay đổi `MQTT_BROKER_IP` trong `.env` trên Pi trỏ về IP của Laptop.

---

## Hướng dẫn vận hành

### Bước 1: Khởi động MQTT Broker
Khởi chạy Mosquitto trên Laptop với cấu hình chuẩn của dự án:
```bash
mosquitto -c mosquitto.conf
```

### Bước 2: Khởi động Raspberry Pi Node
SSH vào Pi, điều hướng vào dự án và chạy:
```bash
python -m pi_node.main
```

### Bước 3: Khởi động AI Brain (Laptop)
Mở Terminal mới trên Laptop và chạy:
```bash
python -m ai_brain.main
```

### Bước 4: Khởi động Web Dashboard (Laptop)
Mở Terminal mới trên Laptop và chạy:
```bash
python -m web_dashboard.app
```
Truy cập **http://localhost:8081** để xem giao diện giám sát Real-time.

---

## Mô phỏng (Simulation) - Test không cần xe thật
Dự án có sẵn môi trường Mock MQTT để kiểm thử AI Brain mà không cần dùng phần cứng Pi:
```bash
# Mở Terminal 1 - Khởi chạy Broker
mosquitto -c mosquitto.conf

# Mở Terminal 2 - Khởi chạy Mock Pi (Dùng Webcam PC)
python -m simulation.mock_pi_node

# Mở Terminal 3 - Khởi chạy AI
python -m ai_brain.main

# Mở Terminal 4 - Khởi chạy Dashboard
python -m web_dashboard.app
```
*Xem thêm [TESTFILE.md](TESTFILE.md) để biết chi tiết.*

---

## Cấu trúc thư mục mới

```
AutoCar/
├── shared/             # Cấu hình chung, constants, MQTT wrapper
├── pi_node/            # Lớp phần cứng cấp thấp (HAL) & Motor FSM (chạy trên Pi)
├── ai_brain/           # Lớp nhận thức (YOLO, Sensor Fusion) & Behavior Tree
├── web_dashboard/      # Giao diện giám sát Web (Flask + MQTT Listeners)
├── simulation/         # Mock MQTT Pi cho việc debug và test không phần cứng
├── mosquitto.conf      # Cấu hình cho MQTT Broker
├── requirements.txt    # Các file requirements.txt ở từng node
├── LABELLING.md        # Hướng dẫn tạo dataset và huấn luyện YOLOv5
├── TESTFILE.md         # Hướng dẫn chạy thử với môi trường giả lập (Mock)
├── .env                # Biến môi trường
└── README.md
```