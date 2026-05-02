# AutoCar — Xe tự hành tránh vật cản (Raspberry Pi + YOLOv5)

Dự án xe tự hành sử dụng kiến trúc điện toán phân tán. Toàn bộ xử lý AI nặng được thực hiện trên **Laptop/PC** — Raspberry Pi chỉ đóng vai trò điều khiển phần cứng và thu thập hình ảnh.

---

## Kiến trúc hệ thống

```
┌─────────────────────┐          HTTP/WiFi         ┌──────────────────────────┐
│  Raspberry Pi (Pi)  │  ◄─────────────────────►   │  Laptop / PC (AI Server) │
│                     │                             │                          │
│  • robot_server.py  │   /snapshot → ảnh JPEG      │  • ai_controller.py      │
│  • PiCamera         │   /control  ← lệnh (cmd)    │  • YOLOv5 + Sensor Fusion│
│  • Motor L298N      │   /distance → cm siêu âm    │  • Web GUI (port 8080)   │
│  • Cảm biến HC-SR04 │                             │                          │
└─────────────────────┘                             └──────────────────────────┘
```

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

### Nguồn điện

> **⚠️ Quan trọng:** Điều chỉnh mạch giảm áp (Buck Converter) về đúng **5.0V – 5.1V** cho Pi. Tuyệt đối không để vượt quá 5.2V. Nối GND chung giữa Pi và L298N.

---

## Cài đặt môi trường

### Trên Raspberry Pi

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-flask python3-opencv
```

```bash
cd ~
git clone <repo-url> obstacle_avoidance
cd obstacle_avoidance/Rasberry_pi
python3 robot_server.py
```

### Trên Laptop / PC

**1. Cài đặt thư viện:**

```bash
cd Car_Server
pip install -r requirement.txt
```

**2. Tạo file `.env` ở thư mục gốc dự án:**

```env
CAR_IP=<Địa chỉ IP của Raspberry Pi>
```
*(Ví dụ: `CAR_IP=192.168.1.105`)*

**3. Khởi chạy AI Controller:**

```bash
python ai_controller.py
```

**4. Mở trình duyệt và truy cập Web GUI:**

```
http://127.0.0.1:8080
```

---

## Hướng dẫn vận hành

### Bước 1 — Khởi động Pi

1. SSH vào Pi: `ssh pi@<địa_chỉ_ip_pi>`
2. Điều hướng vào thư mục dự án và chạy server:

```bash
cd ~/obstacle_avoidance/Rasberry_pi
python3 robot_server.py
```

3. Ghi lại địa chỉ IP của Pi (ví dụ: `192.168.1.105`).

### Bước 2 — Chạy AI trên Laptop

1. Điền IP của Pi vào file `.env`:

```env
CAR_IP=192.168.1.105
```

2. Nếu đã cắm cảm biến siêu âm, mở `ai_controller.py` và đặt:

```python
USE_ULTRASONIC = True
```

3. Chạy:

```bash
python ai_controller.py
```

4. Mở `http://127.0.0.1:8080` trên trình duyệt. Nhấn **START AI** để bắt đầu.

---

## Các tính năng an toàn

| Tính năng | Mô tả |
|---|---|
| **Watchdog Timer** | Pi tự dừng motor nếu không nhận lệnh trong 3 giây |
| **Phát hiện mù camera** | Dừng khẩn cấp khi ảnh quá tối (bị che hoặc trời tối) |
| **AEB (Phanh khẩn cấp tự động)** | Kích hoạt khi vật cản đột ngột lao nhanh vào camera |
| **Sensor Fusion** | Kết hợp YOLO + siêu âm để phát hiện vật trong suốt / quá gần |
| **Phục hồi ngõ cụt** | Xe tự lùi và rẽ thoát khi bị bao vây tứ phía |

---

## Cấu trúc thư mục

```
AutoCar/
├── Car_Server/
│   ├── ai_controller.py     # AI + Web GUI Flask (chạy trên Laptop)
│   ├── collect_data.py      # Thu thập ảnh để huấn luyện model
│   ├── requirement.txt      # Thư viện cần cài trên Laptop
│   ├── models/
│   │   └── best.pt          # Model YOLOv5 đã huấn luyện
│   └── templates/
│       └── index.html       # Giao diện Web GUI
├── Rasberry_pi/
│   ├── robot_server.py      # Flask server chạy trên Pi
│   ├── hardware_test.py     # Kiểm tra phần cứng từng bộ phận
│   └── requirement.txt      # Thư viện cần cài trên Pi
├── Stimulation/
│   └── mock_pi_server.py    # Giả lập Pi để test không cần phần cứng
├── LABELLING.md             # Hướng dẫn tạo dataset và huấn luyện YOLOv5
├── TESTFILE.md              # Hướng dẫn chạy thử với môi trường giả lập
├── .env                     # Biến môi trường (CAR_IP)
└── README.md
```

---

## Lưu ý quan trọng

- **Mạng Wi-Fi:** Dùng **Mobile Hotspot** từ điện thoại để Pi và Laptop kết nối trực tiếp, giảm độ trễ tối đa.
- **Camera NoIR (ảnh ám tím):** Nếu dùng Camera Pi NoIR, có thể chỉnh `Saturation = 0.0` trong `robot_server.py` để chuyển sang ảnh đen trắng giúp AI nhận diện tốt hơn.
- **Test trước khi thả xe:** Luôn chạy `hardware_test.py` trên Pi để kiểm tra motor, cảm biến và camera trước khi cho xe hoạt động tự động.