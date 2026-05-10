# Hướng dẫn test hệ thống với môi trường giả lập (Simulation)

Module `simulation/mock_pi_node.py` giúp bạn kiểm tra toàn bộ logic AI — mô hình YOLOv5, cây hành vi (Behavior Tree), kết nối MQTT, cảnh báo Dashboard — **ngay trên máy tính, không cần thiết bị Raspberry Pi, không tốn pin xe thật.**

Mock Pi Node sẽ mô phỏng việc gửi hình ảnh từ **webcam PC** (hoặc tạo ảnh synthetic), tạo số liệu giả từ cảm biến siêu âm, và in ra log console các lệnh điều khiển Motor nhận được từ AI.

---

## Cách hoạt động (Cấu trúc Microservices MQTT)

```
Laptop (Mock Pi Node)             Laptop (AI Brain)              Laptop (Web Dashboard)
┌───────────────────────┐         ┌────────────────────────┐     ┌────────────────────────┐
│ mock_pi_node.py       │ ◄─────► │ ai_brain.main          │ ◄─► │ web_dashboard.app      │
│                       │         │                        │     │                        │
│ - Dùng webcam PC      │         │ - Lấy ảnh từ MQTT      │     │ - Hiện Real-time state │
│ - Gửi ảnh lên MQTT    │ MQTT    │ - Phân tích YOLO + BT  │ MQTT│ - Nút điều khiển       │
│ - Mô phỏng HC-SR04    │         │ - Quyết định lái xe    │     │ - Video feed preview   │
│ - In lệnh motor       │         │ - Gửi lệnh qua MQTT    │     │ - Port 8081            │
└───────────────────────┘         └────────────────────────┘     └────────────────────────┘
```

---

## Bước 1 — Khởi động MQTT Broker

Toàn bộ hệ thống giao tiếp qua Mosquitto MQTT Broker.
Mở **Terminal 1**, chạy:

```bash
mosquitto -c mosquitto.conf
```

---

## Bước 2 — Khởi động Simulation (Mock Pi Node)

Mở **Terminal 2**, chạy:

```bash
python -m simulation.mock_pi_node
```

Server sẽ tự động:
- Nếu máy có **webcam** → dùng webcam truyền ảnh lên topic `autocar/camera/frame`.
- Nếu **không có webcam** → tạo ảnh đồ họa nền xám làm khung hình giả.
- Lắng nghe topic `autocar/command/motor` và in các lệnh rẽ, tiến, lùi ra Terminal.

---

## Bước 3 — Khởi động AI Brain

Mở **Terminal 3**, chạy:

```bash
python -m ai_brain.main
```

AI Brain sẽ nhận dữ liệu ảnh và cảm biến từ Mock Pi, chạy qua bộ Sensor Fusion và Behavior Tree, sau đó phát ra mệnh lệnh motor và trạng thái AI.

---

## Bước 4 — Mở Web Dashboard

Mở **Terminal 4**, chạy:

```bash
python -m web_dashboard.app
```

Truy cập trên trình duyệt:
```
http://127.0.0.1:8081
```

**Quan sát kết quả:**
- **Web Dashboard:** Hiển thị video webcam, mức độ nguy hiểm (Danger Level), các vật cản, và trạng thái FSM/BT hiện tại.
- **Terminal 2 (Mock Pi):** Bạn sẽ thấy các lệnh như `[MOCK] ⬆️ MOTOR: cruise speed=80 steer=0.00` xuất hiện khi AI ra quyết định.
- Bạn có thể thử đưa đồ vật (chai nước, người) ra trước Webcam máy tính để xem xe "phanh khẩn cấp" hoặc "đánh lái" như thế nào trên log màn hình.

---

## Quay lại xe thật

Khi bạn đã tinh chỉnh xong AI và muốn đưa code lên xe thật:
1. Đảm bảo file `.env` trên Pi trỏ `MQTT_BROKER_IP` đến máy tính Laptop (hoặc Pi chạy Broker).
2. Tắt `mock_pi_node.py` trên Laptop.
3. Chạy `python -m pi_node.main` trên mạch Raspberry Pi.
Hệ thống AI và Dashboard không cần phải thay đổi hay cấu hình lại gì thêm.