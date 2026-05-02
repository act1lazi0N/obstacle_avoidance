# Hướng dẫn test hệ thống với môi trường giả lập

`mock_pi_server.py` giúp bạn kiểm tra toàn bộ logic AI — mô hình YOLOv5, quyết định rẽ, kết nối mạng — **ngay trên máy tính, không cần Raspberry Pi, không tốn pin xe thật.**

---

## Cách hoạt động

```
Laptop (Terminal 1)              Laptop (Terminal 2)
┌─────────────────────┐          ┌──────────────────────────┐
│  mock_pi_server.py  │ ◄──────► │    ai_controller.py      │
│                     │          │                          │
│  Port :5000         │          │  Gửi request snapshot    │
│  Trả về ảnh webcam  │          │  Phân tích YOLOv5        │
│  (hoặc ảnh giả)     │          │  Gửi lệnh điều khiển     │
│  In lệnh ra console │          │  Web GUI: :8080          │
└─────────────────────┘          └──────────────────────────┘
```

---

## Bước 1 — Khởi động Mock Server

Mở **Terminal 1**, chạy:

```bash
cd Stimulation
python mock_pi_server.py
```

Server sẽ khởi động tại `http://127.0.0.1:5000` và giả lập Raspberry Pi.

- Nếu có **webcam** → dùng ảnh từ webcam.
- Nếu **không có webcam** → tự tạo ảnh giả (gradient xám + timestamp) để test logic AI.

---

## Bước 2 — Đảm bảo AI trỏ về Localhost

Kiểm tra file `.env` ở thư mục gốc:

```env
CAR_IP=127.0.0.1
```

Hoặc nếu chưa có file `.env`, tạo mới với nội dung trên. Điều này đảm bảo AI tìm đến Mock Server thay vì xe thật.

---

## Bước 3 — Chạy AI và quan sát

Mở **Terminal 2**, chạy:

```bash
cd Car_Server
python ai_controller.py
```

Sau đó mở trình duyệt và truy cập **Web GUI**:

```
http://127.0.0.1:8080
```

**Nhấn START AI** để bắt đầu. Kết quả bạn sẽ thấy:

| Nơi quan sát | Nội dung |
|---|---|
| **Web GUI (`:8080`)** | Video feed từ webcam/ảnh giả, trạng thái hành động |
| **Terminal 1 (Mock)** | In lệnh nhận được: `[MOTOR] Rẽ PHẢI`, `[MOTOR] Đi THẲNG`... |
| **Terminal 2 (AI)** | Log phân tích YOLO, kết nối, cảnh báo |

---

## Bước 4 — Chạy xe thật

Khi đã test xong, đổi lại IP trong file `.env`:

```env
CAR_IP=192.168.1.105
```

*(Thay bằng IP thực tế của Raspberry Pi của bạn)*

> **⚠️ Lưu ý:** Nếu quên đổi IP, xe thật sẽ bất động và Web GUI báo `DISCONNECTED`.

---

## Giới hạn của môi trường giả lập

- Mock chỉ kiểm tra **logic phần mềm**, không kiểm tra phần cứng thực.
- Ảnh giả lập (gradient xám) **sẽ không kích hoạt** cảnh báo vật cản của YOLO vì không có object thật.
- Để test YOLO detect đúng, bạn cần có **webcam** và đặt đồ vật trước ống kính.
- Trước khi thả xe chạy thật, hãy chạy `hardware_test.py` trên Pi để xác nhận motor và cảm biến hoạt động.