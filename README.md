# Autonomous Obstacle Avoidance Car (Raspberry Pi + YOLOv5)

Dự án xe tự hành sử dụng kiến trúc điện toán phân tán (Distributed Computing). Toàn bộ quá trình xử lý AI nặng được thực hiện trên máy tính (Laptop/PC), trong khi Raspberry Pi đóng vai trò là "cánh tay nối dài" để điều khiển phần cứng và thu thập hình ảnh.

## 1. Kiến trúc hệ thống

* **Robot Server (Raspberry Pi):** Chạy Flask API để nhận lệnh điều khiển động cơ và truyền stream hình ảnh từ Camera.
* **AI Controller (Laptop/PC):** Sử dụng mô hình YOLOv5 để nhận diện vật cản từ hình ảnh truyền về, kết hợp dữ liệu siêu âm để ra quyết định và gửi lệnh ngược lại cho xe.

## 2. Sơ đồ đấu nối phần cứng (GPIO BCM)

### Mạch công suất L298N (Motor Driver)
* **Bánh trái:** ENA => GPIO 25, IN1 => GPIO 24, IN2 => GPIO 23.
* **Bánh phải:** ENB => GPIO 17, IN3 => GPIO 27, IN4 => GPIO 22.

### Cảm biến siêu âm HC-SR04
* **TRIG:** GPIO 5.
* **ECHO:** GPIO 6 (Cần qua cầu phân áp để hạ từ 5V xuống 3.3V trước khi vào Pi).

### Nguồn điện
* **Điện áp vào Pi:** Phải điều chỉnh mạch giảm áp (Buck) về mức **5.0V - 5.1V**. Tuyệt đối không để mức 5.5V trở lên để tránh hỏng mạch.
* **Chung Mass:** Phải nối dây GND từ Pi sang GND của mạch L298N.

## 3. Cài đặt môi trường

### Trên Raspberry Pi
Cài đặt các thư viện cần thiết:
```bash
sudo apt update
sudo apt install python3-picamera2 python3-flask python3-opencv
```
### Trên Laptop/PC
Yêu cầu Python 3.8+ và các thư viện:
```bash
pip install torch torchvision torchaudio requests opencv-python numpy pandas python-dotenv
```

Sau khi tải xong tất cả tạo file `.env` và thêm biến môi trường
```bash
CAR_IP = <Địa chỉ của Raspberrypi>
```

## 4. Hướng dẫn vận hành
**Bước 1: Khởi động Server trên Raspberry Pi**
1. Truy cập vào Pi qua SSH (`pi3@<tên_địa_chỉ_pi>`).
2. Kiểm tra file thư mục 
```bash
ls -a 
```
3. Nếu có file `obstacle_avoidance`, truy cập thu mục
```bash
cd ./obstacle_avoidance
```
4. Xóa file cũ và mở file server:
```bash
rm robot_server.py
nano robot_server.py
```
5. Copy/paste lại toàn bộ source code từ file `robot_server.py` vào file editor
6. Nhấn `Ctrl + O `(Chữ) và `Enter` để lưu
7. Nhấn `Ctrl + X` để thoát
8. Thực hiện chạy file
```bash
python3 robot_server.py 
```
9. Lưu ý địa chỉ IP mà Pi đang nhận (Ví dụ: 192.168.82.250).

**Bước 2: Cấu hình và chạy Trí tuệ nhân tạo trên Laptop**
1. Mở file `ai_controller.py`.
2. Thay đổi biến PI_IP thành địa chỉ IP thực tế của Pi.
3. Nếu đã cắm cảm biến siêu âm, đặt `USE_ULTRASONIC = True`.
4. Chạy bộ điều khiển:
```bash
python ai_controller.py
```

## 5. Các tính năng an toàn
* **Watchdog Timer:** Nếu xe mất kết nối với Laptop quá 3 giây, nó sẽ tự động dừng lại để tránh va chạm mất kiểm soát.
* **Phát hiện mù:** Nếu camera bị che khuất hoặc môi trường quá tối, xe sẽ dừng khẩn cấp.
* **Sensor Fusion:** Kết hợp giữa tầm nhìn máy tính (YOLO) và sóng siêu âm để phát hiện các vật cản trong suốt hoặc quá gần.

## 6. Lưu ý quan trọng
* **Mạng Wi-Fi:** Để hệ thống chạy mượt nhất (FPS cao), nên sử dụng Mobile Hotspot từ điện thoại để Laptop và Pi kết nối trực tiếp với nhau.
* **Độ bão hòa màu:** Nếu sử dụng Camera Pi NoIR (ảnh bị ám tím), có thể chỉnh Saturation về 0.0 trong `robot_server.py` để chuyển sang chế độ đen trắng giúp AI nhận diện chuẩn hơn.