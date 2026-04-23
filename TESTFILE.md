# Hướng dẫn test hệ thống bằng môi trường giả lập (`mock_pi_server.py`)

Môi trường giả lập (Mock Server) là công cụ giúp bạn kiểm tra toàn bộ logic của bộ não AI (mô hình YOLOv5, logic rẽ trái/phải, giao tiếp mạng) ngay trên máy tính mà không cần bật Raspberry Pi hay tiêu tốn pin của xe thật.

## Bước 1: Khởi động Mock Server trên máy tính

* Bạn không cần dùng đến Raspberry Pi. Tất cả mọi thứ đều làm trên Laptop.
* Mở một cửa sổ Terminal hoặc Command Prompt.
* Di chuyển vào thư mục Stimulation (nơi chứa file mock).
* Chạy lệnh:

```Bash
python mock_pi_server.py
```
Lúc này, Laptop của bạn sẽ mở cổng `5000` và tự động giả vờ làm một chiếc Raspberry Pi đang đợi lệnh.

## Bước 2: Chuyển hướng kết nối của AI về "Localhost"

Mở file ai_controller.py trên máy tính lên. Tìm đến dòng khai báo IP. Bạn cần chuyển IP về địa chỉ nội bộ của máy tính (`127.0.0.1`).

Chỉnh sửa code thành như sau:

```Python
PI_IP = "127.0.0.1"
# PI_IP = "192.168.82.250"
```
Nhớ lưu lại file sau khi sửa. Bước này rất quan trọng để AI không đi tìm chiếc xe thật ngoài đời nữa, mà tìm chiếc xe giả lập ngay bên trong máy tính.

## Bước 3: Chạy AI và kiểm tra kết quả

* Mở thêm một cửa sổ Terminal hoặc Command Prompt thứ hai.
* Chạy file AI bằng lệnh:

```Bash
python ai_controller.py
```
Chuyện gì sẽ xảy ra:

* AI sẽ gửi yêu cầu vào cổng `5000`. Mock server sẽ trả về một bức ảnh màu (hoặc ảnh trống) thay vì ảnh từ camera thật.
* AI phân tích bức ảnh giả lập này và đưa ra quyết định (ví dụ: rẽ trái).
* AI gửi lệnh left sang Mock Server.
* Trên màn hình của Mock Server, bạn sẽ thấy in ra dòng chữ: "Giả vờ đang rẽ trái..." hoặc "Đã nhận lệnh: `left`".

***Lưu ý đặc biệt quan trọng:***
Môi trường mock chỉ giúp bạn biết AI đã ghép nối thành công và thư viện hoạt động tốt, không bị lỗi cú pháp. Giao diện OpenCV vẫn sẽ hiện lên nhưng chỉ là khung hình tĩnh hoặc màn hình đen, xe sẽ không có phản xạ tự nhiên vì không có phần cứng di chuyển.

Sau khi test xong và muốn cho xe thật chạy, bạn BẮT BUỘC phải vào lại file `ai_controller.py` để đổi IP ngược lại:

```Python
# PI_IP = "127.0.0.1"
PI_IP = "192.168.82.250"
```
Nếu quên bước này, xe thật sẽ nằm bất động và màn hình báo mất kết nối!