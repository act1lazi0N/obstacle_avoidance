# Hướng dẫn test hệ thống với môi trường giả lập

`mock_pi_server.py` giúp bạn kiểm tra toàn bộ logic AI — mô hình YOLOv5, quyết định rẽ, kết nối mạng — **ngay trên máy tính, không cần Raspberry Pi, không tốn pin xe thật.**

Nếu laptop có **webcam**, bạn sẽ thấy video thật trên Web GUI giống như xem camera từ xe.

---

## Cách hoạt động

```
Laptop (Terminal 1)              Laptop (Terminal 2)
┌─────────────────────┐          ┌──────────────────────────┐
│  mock_pi_server.py  │ ◄──────► │    ai_controller.py      │
│                     │          │                          │
│  Port :5000         │          │  Nhận ảnh từ :5000       │
│  Gửi ảnh webcam     │          │  Phân tích YOLOv5        │
│  (hoặc ảnh giả)     │          │  Hiện video lên Web GUI  │
│  In lệnh ra console │          │  Web GUI: :8080          │
└─────────────────────┘          └──────────────────────────┘
```

---

## Bước 1 — Cấu hình IP về Localhost

Mở (hoặc tạo) file `.env` ở **thư mục gốc dự án** (`AutoCar/.env`):

```env
CAR_IP=127.0.0.1
```

Điều này đảm bảo AI Controller gửi request đến Mock Server thay vì xe thật.

---

## Bước 2 — Khởi động Mock Server

Mở **Terminal 1**, chạy:

```bash
cd Stimulation
python mock_pi_server.py
```

Server sẽ tự động:
- Nếu có **webcam** → dùng webcam làm camera (giống camera trên xe thật).
- Nếu **không có webcam** → tạo ảnh giả (gradient xám + timestamp).

Khi thấy dòng `MOCK PI SERVER RUNNING` là đã sẵn sàng.

---

## Bước 3 — Khởi động AI Controller

Mở **Terminal 2**, chạy:

```bash
cd Car_Server
python ai_controller.py
```

**Hai trường hợp có thể xảy ra:**

| Trường hợp | Điều kiện | Kết quả trên Web GUI |
|---|---|---|
| **Chế độ AI đầy đủ** | Có file `models/best.pt` | Video webcam + bounding box nhận diện vật cản |
| **Chế độ Passthrough** | Không có file `best.pt` hoặc model lỗi | Video webcam gốc hiện nguyên xi (có chữ "PASSTHROUGH") |

> **💡 Lưu ý:** Dù chưa có model AI, bạn **vẫn xem được webcam** trên Web GUI nhờ chế độ Passthrough. Không cần phải có file `best.pt` mới thấy video.

---

## Bước 4 — Mở Web GUI trên trình duyệt

Truy cập:

```
http://127.0.0.1:8080
```

**Các trang trên Web GUI:**

| Trang | Nội dung |
|---|---|
| **Dashboard** | Video preview nhỏ + nút điều khiển + telemetry + log |
| **Video Feed** | Xem video toàn màn hình |
| **Settings** | Thông số kết nối và cấu hình AI |

---

## Bước 5 — Quan sát kết quả

| Nơi quan sát | Nội dung |
|---|---|
| **Web GUI (`:8080`)** | Video từ webcam, trạng thái xe, nút START/STOP AI |
| **Terminal 1 (Mock)** | In lệnh nhận được: `[MOTOR] Đi THẲNG`, `[MOTOR] Rẽ PHẢI`... |
| **Terminal 2 (AI)** | Log phân tích YOLO, kết nối, cảnh báo |

Nhấn **START AI** trên Web GUI để AI bắt đầu phân tích và ra lệnh cho xe (mock).

---

## Quay lại xe thật

Khi test xong, đổi IP trong file `.env`:

```env
CAR_IP=192.168.1.105
```

*(Thay bằng IP thực tế của Raspberry Pi)*

> **⚠️ Quan trọng:** Nếu quên đổi IP, xe thật sẽ bất động và Web GUI báo `Disconnected`.

---

## Giới hạn của môi trường giả lập

- Mock chỉ kiểm tra **logic phần mềm**, không kiểm tra motor/cảm biến thực.
- Chế độ Passthrough (không model) chỉ hiện video, **không phát hiện vật cản**.
- Để test YOLO detect đúng, cần có file `models/best.pt` + đưa đồ vật trước webcam.
- Trước khi chạy xe thật, hãy chạy `hardware_test.py` trên Pi để kiểm tra phần cứng.