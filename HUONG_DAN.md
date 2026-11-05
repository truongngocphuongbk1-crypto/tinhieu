# Hướng dẫn cài Bot tín hiệu cổ phiếu (miễn phí)

Sau khi cài xong, Sếp sẽ có:

- **Kênh Telegram**: tự nhận tin MUA/BÁN và tin tổng kết cuối phiên. Ai có link kênh đều tham gia được.
- **Trang web**: bảng tín hiệu giống bảng cũ, ai có link đều xem được, tự cập nhật.

Thời gian cài: khoảng 20–30 phút. Làm lần lượt từng phần, không bỏ bước.

---

## PHẦN 1 – Tạo bot Telegram (5 phút)

1. Mở Telegram, ô tìm kiếm gõ **BotFather** (có tích xanh) → bấm **Start**.
2. Gõ `/newbot` rồi gửi.
3. BotFather hỏi tên bot → gõ ví dụ `Tin hieu co phieu` rồi gửi.
4. BotFather hỏi username → gõ tên **kết thúc bằng `bot`**, ví dụ `tinhieu_phuong_bot`.
5. BotFather trả về một dòng dài dạng `123456789:AAH...` → đây là **TOKEN**. Lưu lại vào ghi chú.
   ⚠️ Không gửi TOKEN cho ai, kể cả dán vào chat.

## PHẦN 2 – Tạo kênh Telegram để chia sẻ (5 phút)

1. Trong Telegram: bấm biểu tượng bút ✏️ → **New Channel** (Kênh mới).
2. Đặt tên kênh, ví dụ `Tín hiệu cổ phiếu`.
3. Chọn **Public** (Công khai) và đặt link, ví dụ `t.me/tinhieu_phuong`.
   → Phần sau `t.me/` chính là **tên kênh**: `@tinhieu_phuong`
4. Vào kênh → bấm tên kênh → **Administrators** (Quản trị viên) → **Add Admin** → tìm username bot ở Phần 1 → cho phép **Post Messages** → Lưu.

## PHẦN 3 – Tạo tài khoản GitHub và kho code (10 phút)

1. Vào trang sau và đăng ký tài khoản (miễn phí):
   ```
   https://github.com/signup
   ```
2. Đăng nhập xong, vào trang tạo kho:
   ```
   https://github.com/new
   ```
3. **Repository name**: gõ `tinhieu` → chọn **Public** → bấm **Create repository**.
   (Phải là Public thì GitHub mới cho chạy và làm trang web miễn phí. TOKEN vẫn được giấu an toàn ở Phần 4.)
4. Ở trang kho vừa tạo, bấm dòng chữ **uploading an existing file**.
5. Giải nén file `signalbot.zip` trên máy. Mở thư mục `signalbot`, **chọn tất cả** bên trong
   (gồm `bot.py`, `state.json`, `HUONG_DAN.md`, thư mục `web` và thư mục `.github`) rồi **kéo thả** vào trang GitHub.
   - Trên Windows nếu không thấy thư mục `.github`: trong File Explorer chọn **View → Show → Hidden items**.
6. Đợi tải xong → bấm nút xanh **Commit changes**.
7. Kiểm tra: trong kho phải thấy `.github/workflows/bot.yml`. Nếu thiếu, xem mục "Gặp lỗi" ở cuối.

## PHẦN 4 – Cất TOKEN vào két bảo mật của GitHub (3 phút)

1. Trong kho, bấm **Settings** (tab trên cùng bên phải).
2. Menu trái: **Secrets and variables** → **Actions**.
3. Tab **Secrets** → **New repository secret**:
   - Name: `TELEGRAM_TOKEN` · Secret: dán TOKEN ở Phần 1 → **Add secret**
4. **New repository secret** lần nữa:
   - Name: `TELEGRAM_CHAT_ID` · Secret: tên kênh, ví dụ `@tinhieu_phuong` → **Add secret**
5. Chuyển sang tab **Variables** → **New repository variable**:
   - Name: `TELEGRAM_LINK` · Value: link kênh, ví dụ `https://t.me/tinhieu_phuong` → **Add variable**
   (Trang web sẽ hiện nút "Nhận tín hiệu qua Telegram" dẫn tới link này.)

## PHẦN 5 – Bật trang web (1 phút)

1. Vẫn trong **Settings** → menu trái bấm **Pages**.
2. Mục **Source** chọn **GitHub Actions**. Xong (không cần bấm Save).

## PHẦN 6 – Chạy thử lần đầu (3 phút)

1. Bấm tab **Actions** trên cùng. Nếu GitHub hỏi, bấm nút xanh cho phép chạy workflow.
2. Menu trái bấm **Bot tin hieu co phieu** → bên phải bấm **Run workflow** → **Run workflow**.
3. Đợi 1–3 phút đến khi hiện dấu ✅ xanh.
4. Bấm vào lần chạy đó → bấm **run** → mở bước **Chay bot** để xem bot báo gì, ví dụ:
   `Lấy được 215/217 mã. Nguồn: ['DNSE']` → **thành công**.
5. Link trang web nằm ở ô **deploy** trong trang lần chạy, có dạng:
   ```
   https://TEN-TAI-KHOAN.github.io/tinhieu/
   ```
   Gửi link này và link kênh Telegram cho người khác là xong.

Từ giờ bot **tự chạy mỗi 5 phút**, từ 9h00 đến 15h05, thứ 2 đến thứ 6. Sếp không cần bật máy.

---

## Gặp lỗi?

| Hiện tượng | Cách xử lý |
|---|---|
| Bước "Chay bot" báo `KHÔNG lấy được mã nào` | Nguồn giá đang chặn hoặc lỗi. Chụp màn hình log gửi Claude để đổi nguồn. |
| Không có tin Telegram | Kiểm tra bot đã là Admin của kênh chưa; tên kênh trong `TELEGRAM_CHAT_ID` có dấu `@` chưa. Chỉ có tin khi **có tín hiệu mới trong hôm nay**. |
| Bước "Dang trang web" lỗi | Làm lại Phần 5 (Source = GitHub Actions). |
| Không thấy `.github/workflows/bot.yml` | Bấm **Add file → Create new file**, ô tên gõ `.github/workflows/bot.yml`, mở file `bot.yml` trên máy bằng Notepad, copy toàn bộ dán vào → **Commit changes**. |
| Bot chạy trễ vài phút | Bình thường. Lịch miễn phí của GitHub hay trễ 3–15 phút lúc đông. |

## Muốn sửa?

Mở `bot.py` trên GitHub → bấm biểu tượng bút ✏️ → sửa phần **CẤU HÌNH** ở đầu file → **Commit changes**:

- `DANH_SACH_MA`: thêm/bớt mã (cách nhau bằng dấu cách)
- `TARGET`: % chốt lời Target 1 / Target 2
- `CHO_MUA_CACH`: giá cách điểm mua bao nhiêu % thì vào danh sách Chờ mua

## Lưu ý

- Tín hiệu trong phiên có thể **xuất hiện rồi mất** nếu giá đảo chiều trước giờ đóng cửa. Tin **Tổng kết phiên** lúc 15h là danh sách chốt.
- Đây là công cụ tính toán theo công thức, **không phải khuyến nghị đầu tư**.
