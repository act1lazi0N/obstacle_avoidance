# Cách tự tạo Dataset và Huấn luyện YOLOv5 (Custom Object Detection)

Để chiếc xe tự hành có thể nhận diện chính xác các đồ vật cụ thể trong nhà của bạn (như dép, hộp carton, chai nước), bạn cần thực hiện quy trình 3 bước sau: Thu thập hình ảnh -> Gán nhãn -> Huấn luyện mô hình.

---

## Bước 1: Thu thập hình ảnh (Data Collection)

Thay vì tải ảnh trên mạng, chúng ta sẽ dùng chính camera của Raspberry Pi trên xe để chụp ảnh nhằm đảm bảo góc nhìn chân thực nhất cho AI.

1. **Cách sử dụng:** Khởi động xe, chạy file trên Laptop. Cầm đồ vật đưa ra trước camera của xe, xoay nhiều góc độ. Chụp khoảng 150 - 200 ảnh cho mỗi loại đồ vật rồi nhấn `q` để dừng.

---

## Bước 2: Gán nhãn dữ liệu (Data Labeling)

Sử dụng nền tảng [Roboflow](https://roboflow.com/) để vẽ khung nhận diện cho đồ vật.

1. **Tạo dự án & Tải ảnh:** * Tạo Project mới (Object Detection).
   * Kéo thả toàn bộ ảnh trong thư mục `dataset_images` lên Roboflow.
2. **Gán nhãn (Annotate):**
   * Dùng chuột vẽ khung hình chữ nhật **ôm sát mép** đồ vật.
   * Đặt tên (Class name) bằng tiếng Anh viết thường (VD: `box`, `shoe`). 
   * Nhấn phím `D` để chuyển ảnh và lặp lại cho đến hết.
3. **Tạo Dataset & Xuất file:**
   * Nhấn **Generate** (Giữ tỷ lệ mặc định 70/20/10).
   * Nhấn **Export Dataset** -> Bắt buộc chọn Format là **`YOLOv5 PyTorch`**.
   * Chọn `Show download code` và copy đoạn code cài đặt mà Roboflow cung cấp.

---

## Bước 3: Huấn luyện mô hình (Model Training)

Sử dụng Google Colab để mượn GPU miễn phí huấn luyện bộ não AI mới.

1. Truy cập [YOLOv5 Colab Notebook](https://colab.research.google.com/github/ultralytics/yolov5/blob/master/tutorial.ipynb).
2. Vào menu **Runtime** -> **Change runtime type** -> Chọn **T4 GPU**.
3. Chạy ô code đầu tiên (`Setup`) để cài đặt YOLOv5.
4. **Nạp dữ liệu:** Tạo một ô code mới, dán đoạn code tải dữ liệu của Roboflow (đã copy ở cuối Bước 2) vào và chạy.
5. **Huấn luyện:** Tạo một ô code mới và chạy dòng lệnh sau:
   ```bash
   !python train.py --img 320 --batch 16 --epochs 100 --data {dataset.location}/data.yaml --weights yolov5s.pt --cache
   ```
   *(Mẹo: Bạn có thể tăng `--epochs` lên 150 hoặc 200 nếu số lượng ảnh ít để AI học kỹ hơn).*
6. **Lấy thành quả:** * Đợi quá trình chạy hoàn tất (khoảng 15-30 phút).
   * Nhìn sang cột quản lý file bên trái Colab, tìm theo đường dẫn: `yolov5` -> `runs` -> `train` -> `exp` -> `weights`.
   * Tải file **`best.pt`** về máy tính.
   * Copy file này đè lên file cũ trong thư mục `models/` của dự án.

Hết.