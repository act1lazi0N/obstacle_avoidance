---
trigger: manual
---

1. Tính minh bạch và dễ hiểu (Clarity and Readability): Mọi đoạn code cung cấp phải được viết rõ ràng, tối ưu hóa và bắt buộc phải có chú thích (comments) giải thích chi tiết bằng tiếng Việt cho từng khối logic quan trọng.
2. Phân tách môi trường rõ ràng (Environment Separation): Với các dự án IoT phân tán, phải tách biệt rõ ràng đoạn code nào chạy trên thiết bị đầu cuối (Edge Device/Raspberry Pi/Arduino) và đoạn code nào chạy trên máy chủ (Local Server/Cloud). Sử dụng code block Markdown và ghi rõ tên file ở dòng đầu tiên (Ví dụ: # Tên file: robot_server.py).
3. An toàn và Xử lý ngoại lệ (Fail-safes & Error Handling): Code điều khiển phần cứng bắt buộc phải có các cơ chế tự bảo vệ. Ví dụ: tự động ngắt động cơ khi mất kết nối mạng, dừng khẩn cấp khi cảm biến lỗi, hoặc chống tràn bộ đệm (buffer overflow) khi truyền phát camera.
4. Thiết lập môi trường (Dependencies & Setup): Luôn cung cấp danh sách các thư viện cần thiết (file requirements.txt) và kèm theo các câu lệnh Terminal/Command Prompt cụ thể để người dùng dễ dàng cài đặt (Ví dụ: pip install flask opencv-python-headless).
5. Hỗ trợ Mô phỏng (Simulation Support): Khuyến khích cung cấp thêm các đoạn mã giả lập (Mock server/Mock sensor) để người dùng có thể kiểm thử logic phần mềm ngay trên máy tính cá nhân trước khi nạp vào phần cứng thật.
6. Tránh Icon AI (AI Icon Avoidance): Chỉ sử dụng thuần dạng văn bản (Text), cấm tuyệt đối sử dụng các ký hiệu, icon, hình ảnh.