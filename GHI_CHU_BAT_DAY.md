# Ghi chú: Chiến lược BẮT ĐÁY (thêm ngày 09–10/11/2026)

## Luật (áp dụng cho cả Khung 1 ngày và Khung 1 giờ)
- **Kênh giá:** đường giữa = EMA 50; dải trên / dưới = đường giữa ± 2,5 × ATR 50.
- **Chấm cam dưới:** giá chạm dải dưới **và** RSI(14) ≤ 30 → mã vào **CHỜ MUA** ("Mua nếu > đỉnh phiên gần nhất").
- **Chấm cam trên:** giá chạm dải trên **và** RSI(14) ≥ 70 → mã vào **CHỜ BÁN** ("Bán nếu < đáy phiên gần nhất").
- Chờ tối đa **10 nến** kể từ chấm cam cuối cùng, quá hạn thì bỏ.
- **MUA (tam giác xanh):** đang chờ mua + nến tăng + đóng cửa vượt đỉnh nến trước (nến đó không phải chấm cam).
- **BÁN (tam giác đỏ):** đang chờ bán + nến giảm + đóng cửa thủng đáy nến trước.
- **Khi đang giữ (chỉ báo từ T+2, tính theo ngày giao dịch):**
  - Chạm đường giữa = **Target 1** → "Giữ 1/2"
  - Chạm dải trên = **Target 2** → bán hết
  - Đóng cửa thủng **đáy thấp nhất của vùng chấm cam** → cắt lỗ
  - Tam giác đỏ → bán
- Tam giác đỏ khi chưa giữ → vẫn báo BÁN (cảnh báo nếu đang cầm mã đó ở ngoài).

## Thông số (sửa ở mục `BAT_DAY` đầu file bot.py)
do_dai=50, atr=50, he_so=2.5, rsi=14, qua_mua=70, qua_ban=30, cho=10, t_min=2

## Khung 1 giờ
- Nến 1 giờ (9h, 10h, 11h, 13h, 14h) gộp từ nến 15 phút của DNSE.
- Lịch sử 1 giờ tải dần: tối đa 40 mã / 3 phút mỗi lượt (`TAI_1H_MOI_LUOT`, `TAI_1H_TOI_DA_GIAY`),
  nên khoảng 30 phút đầu mỗi sáng Khung 1 giờ mới đủ mã.

## Đã kiểm tra
- Khung ngày khớp TradingView (PNJ: dải dưới 20,28 · đường giữa 24,43 · MUA gần nhất 04/08/2026).

## Cập nhật 19/11/2026
- Chỉ còn 2 chiến lược: **SuperTrend** và **Bắt Đáy**, mỗi chiến lược có Khung 1 ngày + Khung 1 giờ (đã bỏ EMA 9/21, Lướt T+).
- Bộ lọc MUA chung (mục `LOC` đầu bot.py): giá trị giao dịch TB 20 phiên ≥ 1 tỷ; CHỈ SỐ ĐỀU (trung bình % tăng/giảm của mọi mã, mỗi mã như nhau, thay cho VNINDEX vốn bị nhóm Vin chi phối) đóng cửa trên EMA 50. **Đã TẮT ngày 19/11** (`ema_chi_so=0`): thị trường xấu vẫn báo Xanh/Hồng; chỉ số đều chỉ còn dùng cho Cơ hội/Rủi ro.
- Quản lý lệnh: cắt lỗ cứng 7%; chạm Target 1 thì dời cắt lỗ về giá mua.
- Bắt Đáy: quá 20 phiên chưa chạm Target 1 thì bán (`qua_han`).
- SuperTrend: Target 1/2 = giá mua + 2/4 lần ATR 14 (mục `SUPERTREND`); bảng hiện mức cắt lỗ = đường SuperTrend.
  HỒNG chỉ khi SuperTrend đảo xuống (`chi_dao_chieu=True`, bỏ cắt lỗ 7% và về vốn); màu mây theo đường SuperTrend.
- Khung 1 giờ: SuperTrend 1 giờ chỉ MUA khi SuperTrend ngày đang tăng; Bắt Đáy 1 giờ chỉ MUA khi giá ngày trên dải dưới (đã chọn phương án a).
- Backtest: tab Actions → **Backtest** → Run workflow → kết quả ở file `KET_QUA_BACKTEST.md`.

## Tab "Tài khoản ảo" (thêm 19/11/2026)
- **Tự giao dịch**: người xem tự tạo tài khoản (vốn 100 triệu – 5 tỷ), đặt lệnh Xanh/Hồng (mua/bán).
  Lưu trên trình duyệt của từng người (localStorage), không cần đăng nhập, chưa có bảng xếp hạng.
  - Lệnh thị trường: chỉ khớp 9:15–11:30, 13:00–14:30, theo giá bot cập nhật (~5 phút/lần).
  - Lệnh giá đặt: hiệu lực 1 phiên; đặt ngoài giờ thì chờ phiên tới (khớp nếu giá thấp nhất/cao nhất chạm giá đặt),
    đặt trong giờ thì khớp ngay khi giá chạm, hết phiên xét theo giá đóng cửa.
  - Phí 0,15%/lệnh, thuế bán 0,1%, lô 100, bán được từ T+2. Có bảng lãi/lỗ theo từng phiên.
- **Tài khoản bot tự động**: 2 tài khoản (SuperTrend, Bắt Đáy), mỗi tk 1 tỷ, tối đa 10 mã, bot tự mua/bán theo tín hiệu
  khung ngày sau 15h mỗi phiên (mục `TAI_KHOAN` đầu bot.py). Xem bằng mật khẩu = GitHub secret `TK_MAT_KHAU`.
