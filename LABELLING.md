# Hướng dẫn tạo Dataset và huấn luyện YOLOv5

Để xe tự hành nhận diện các vật cản cụ thể trong môi trường của bạn (dép, hộp, chai nước, ...), hãy thực hiện quy trình 3 bước: **Thu thập ảnh → Gán nhãn → Huấn luyện**.

---

## Bước 1 — Thu thập ảnh (`collect_data.py`)

Chúng ta sẽ dùng chính camera của Raspberry Pi để chụp ảnh, đảm bảo góc nhìn giống thực tế nhất khi xe đang chạy.

**Cách thực hiện:**

1. Khởi động Pi và chạy `robot_server.py`.
2. Trên Laptop, vào thư mục `Car_Server` và chạy:

```bash
python collect_data.py
```

3. Đưa đồ vật ra trước camera của xe, xoay nhiều góc, nhiều khoảng cách.
4. Nhấn **`q`** để dừng khi đã đủ ảnh.

> **💡 Mẹo:** Chụp tối thiểu **150 – 200 ảnh** cho mỗi loại vật cản. Càng nhiều góc độ và điều kiện ánh sáng khác nhau, AI sẽ càng chính xác.

Ảnh được lưu tự động vào thư mục `Car_Server/dataset_images/`.

---

## Bước 2 — Gán nhãn dữ liệu (Roboflow)

Sử dụng nền tảng [Roboflow](https://roboflow.com) để vẽ khung nhận diện (bounding box) cho từng đồ vật.

**Các bước thực hiện:**

1. **Tạo dự án mới:**
   - Chọn loại **Object Detection**.
   - Kéo thả toàn bộ ảnh trong `dataset_images/` lên Roboflow.

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

Dùng Google Colab để mượn GPU miễn phí.

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
   - Copy file này **đè lên** file cũ tại `Car_Server/models/best.pt`.

---

> Sau khi thay file `best.pt` mới, khởi động lại `ai_controller.py` là xe sẽ nhận diện đúng loại vật cản mới.