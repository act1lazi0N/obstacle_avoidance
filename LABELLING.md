# Hướng dẫn tạo Dataset và huấn luyện YOLOv5

Để xe tự hành (ở module `ai_brain`) nhận diện các vật cản cụ thể trong môi trường của bạn (dép, hộp, chai nước, ...), hãy thực hiện quy trình 3 bước: **Thu thập ảnh → Gán nhãn → Huấn luyện**.

---

## Bước 1 — Thu thập ảnh

Chúng ta sẽ dùng luồng video từ hệ thống MQTT để chụp ảnh, đảm bảo góc nhìn giống thực tế nhất khi xe đang chạy. Bạn có thể tự viết một script nhỏ subscribe vào topic `autocar/camera/frame` để lưu ảnh.

**Cách thực hiện (Nếu dùng camera thật trên Pi):**
1. Khởi chạy Broker: `mosquitto -c mosquitto.conf`
2. Trên Pi chạy Pi Node: `python -m pi_node.main`
3. Trên Laptop, viết script lưu frame MQTT hoặc dùng công cụ ghi hình từ Dashboard.
4. Đưa đồ vật ra trước camera của xe, xoay nhiều góc, nhiều khoảng cách.

> **💡 Mẹo:** Chụp tối thiểu **150 – 200 ảnh** cho mỗi loại vật cản. Càng nhiều góc độ và điều kiện ánh sáng khác nhau, AI sẽ càng chính xác.

---

## Bước 2 — Gán nhãn dữ liệu (Roboflow)

Sử dụng nền tảng [Roboflow](https://roboflow.com) để vẽ khung nhận diện (bounding box) cho từng đồ vật.

**Các bước thực hiện:**

1. **Tạo dự án mới:**
   - Chọn loại **Object Detection**.
   - Kéo thả toàn bộ ảnh đã thu thập lên Roboflow.

2. **Gán nhãn (Annotate):**
   - Vẽ khung hình chữ nhật **ôm sát mép** đồ vật.
   - Đặt tên class bằng tiếng Anh, viết thường (ví dụ: `box`, `shoe`, `bottle`).
   - Nhấn phím **`D`** để chuyển sang ảnh tiếp theo.

3. **Xuất dataset:**
   - Nhấn **Generate** (giữ tỷ lệ mặc định 70 / 20 / 10).
   - Nhấn **Export Dataset** → chọn format **`YOLOv5 PyTorch`**.
   - Chọn **Show download code** và copy đoạn lệnh được cung cấp.

---

## Bước 3 — Huấn luyện mô hình (Google Colab)

Dùng Google Colab để mượn GPU miễn phí huấn luyện model.

**Các bước thực hiện:**

1. Mở [YOLOv5 Colab Notebook](https://colab.research.google.com/github/ultralytics/yolov5/blob/master/tutorial.ipynb).

2. Đổi runtime: **Runtime → Change runtime type → T4 GPU**.

3. Chạy ô **Setup** để cài đặt YOLOv5.

4. Tạo ô code mới, dán đoạn lệnh tải dataset từ Roboflow vào và chạy.

5. Tạo ô code mới, huấn luyện với lệnh:

```bash
!python train.py \
  --img 320 \
  --batch 16 \
  --epochs 100 \
  --data {dataset.location}/data.yaml \
  --weights yolov5s.pt \
  --cache
```

> **💡 Mẹo:** Tăng `--epochs` lên 150 hoặc 200 nếu số ảnh ít (dưới 200 ảnh/class) để AI học kỹ hơn.

6. **Lấy file model sau khi huấn luyện xong:**
   - Vào thư mục `yolov5/runs/train/exp/weights/` trong Colab.
   - Tải file **`best.pt`** về máy tính.
   - Đặt file này vào thư mục của bạn (ví dụ `yolov5s.pt` ở root directory hoặc sửa đường dẫn load model trong `ai_brain/perception/detector.py`).

---

> Sau khi thay file `.pt` mới, hãy chạy lại `ai_brain`: `python -m ai_brain.main` là xe sẽ nhận diện đúng loại vật cản mới qua YOLOv5.