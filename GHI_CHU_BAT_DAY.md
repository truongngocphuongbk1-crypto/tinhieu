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

## Việc còn chờ quyết
- Bộ lọc cho Khung 1 giờ (đang báo MUA/cắt lỗ dày khi xu hướng ngày còn giảm):
  - a) Chỉ MUA 1 giờ khi khung ngày không còn rơi (giá ngày trên dải dưới / đường giữa ngày đi ngang-lên)
  - b) Chỉ MUA 1 giờ khi khung ngày cũng đang CHỜ MUA
  - c) Giữ nguyên
