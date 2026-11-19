# -*- coding: utf-8 -*-
"""
BACKTEST: chạy thử 2 chiến lược (SuperTrend, Bắt Đáy) trên dữ liệu NGÀY khoảng 3 năm gần nhất,
so sánh "bản cũ" (không lọc, không quản lý lệnh) với từng thay đổi và "bản mới" (bật tất cả).

Kết quả ghi vào file KET_QUA_BACKTEST.md (mở trên GitHub là đọc được).
Chạy trên GitHub: tab Actions -> "Backtest" -> Run workflow.
Chạy trên máy:    python backtest.py           (hoặc  python backtest.py --test  để chỉ chạy 5 mã)

Giả định:
- MUA / BÁN tại giá đóng cửa của phiên có tín hiệu; chạm Target thì bán tại giá Target
  (nếu mở cửa đã vượt Target thì bán tại giá mở cửa).
- Trừ phí + thuế 0,4% cho mỗi lệnh (mua + bán).
- Mỗi lệnh tính như nhau (cùng số tiền), không tính lãi kép.
- Chỉ tính lệnh đã đóng. Khung 1 giờ không backtest được vì nguồn chỉ có khoảng 80 ngày nến giờ.
"""
import copy, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import bot

PHI = 0.4          # % phí + thuế cho 1 lệnh (mua + bán)
SO_NAM = 3


def tai_ngay(ma, la_chi_so=False):
    """Nến ngày khoảng SO_NAM năm từ DNSE (dự phòng: nguồn của bot)."""
    now = int(time.time())
    loai = "index" if la_chi_so else "stock"
    url = (f"https://services.entrade.com.vn/chart-api/v2/ohlcs/{loai}?symbol={ma}"
           f"&resolution=1D&from={now - 86400 * 365 * SO_NAM}&to={now + 86400}")
    for _ in range(3):
        try:
            j = bot.http_json(url)
            if j.get("t"):
                t = [datetime.fromtimestamp(x, bot.VN).strftime("%Y-%m-%d") for x in j["t"]]
                return dict(t=t, o=list(j["o"]), h=list(j["h"]), l=list(j["l"]), c=list(j["c"]), v=list(j["v"]))
        except Exception:
            time.sleep(1)
    return bot.lay_gia(ma, la_chi_so)


# Mỗi phương án = các thay đổi so với BẢN CŨ
TAT = dict(gtgd_min=0, ema_chi_so=0, lo_toi_da=100, ve_von=False, qua_han=0)
MOI = dict(gtgd_min=bot.LOC["gtgd_min"], ema_chi_so=bot.LOC["ema_chi_so"], lo_toi_da=bot.LOC["lo_toi_da"],
           ve_von=bot.LOC["ve_von"], qua_han=bot.BAT_DAY["qua_han"])
PHUONG_AN = [
    ("Bản cũ (không lọc, không quản lý lệnh)", {}),
    (f"+ Lọc thanh khoản ≥ {MOI['gtgd_min']} tỷ", dict(gtgd_min=MOI["gtgd_min"])),
    ("+ Lọc chỉ số đều trên EMA 50", dict(ema_chi_so=50)),
    (f"+ Cắt lỗ tối đa {MOI['lo_toi_da']}%", dict(lo_toi_da=MOI["lo_toi_da"])),
    ("+ Dời cắt lỗ về giá mua sau Target 1", dict(ve_von=True)),
    (f"+ Quá {MOI['qua_han']} phiên chưa tới T1 thì bán (Bắt Đáy)", dict(qua_han=MOI["qua_han"])),
    ("BẢN MỚI (bật tất cả)", MOI),
]


# Các cách đặt Target đem ra so sánh (dùng cấu hình bộ lọc / quản lý lệnh hiện tại của bot)
SO_TARGET = [
    ("Theo kênh (cách cũ)", dict(kieu="kenh")),
    ("ATR ngày 2/4, sàn 5/10%", dict(kieu="atr", t1_atr=2, t2_atr=4, t1_min=5, t2_min=10)),
    ("ATR ngày 3/6, sàn 5/10%", dict(kieu="atr", t1_atr=3, t2_atr=6, t1_min=5, t2_min=10)),
    ("R 1,5/3, sàn 5/10%", dict(kieu="r", t1_r=1.5, t2_r=3, t1_min=5, t2_min=10)),
    ("R 2/4, sàn 5/10%", dict(kieu="r", t1_r=2, t2_r=4, t1_min=5, t2_min=10)),
    ("ATR+R (lấy mức cao hơn), sàn 5/10%", dict(kieu="atr_r", t1_atr=2, t2_atr=4, t1_r=1.5, t2_r=3, t1_min=5, t2_min=10)),
    ("% cố định 7/15%", dict(kieu="atr", t1_atr=0, t2_atr=0, t1_min=7, t2_min=15)),
]


def so_sanh_target(data, gio):
    """Chạy từng cách đặt Target trên khung ngày và khung 1 giờ. Trả về {(tên, khung, chiến lược): thống kê}."""
    goc = copy.deepcopy(bot.TARGET)
    cs = bot.chi_so_deu(list(data.values()))
    kq = {}
    for ten, cau_hinh in SO_TARGET:
        bot.TARGET.clear(); bot.TARGET.update(goc); bot.TARGET.update(cau_hinh)
        vni = bot.thi_truong_ok(cs)
        lenh = {(k, cl): [] for k in ("ngay", "gio") for cl in ("supertrend", "bat_day")}
        for m, d in data.items():
            ok = bot.loc_mua_ngay(d, vni)
            ind = bot.tinh_chien_luoc(d, {"supertrend": ok, "bat_day": ok})
            lenh[("ngay", "supertrend")] += ind["stt"]["lenh"]; lenh[("ngay", "bat_day")] += ind["bd"]["lenh"]
            dg = gio.get(m)
            if dg and len(dg["c"]) > 60:
                ig = bot.tinh_chien_luoc(dg, bot.loc_mua_gio(dg, d, ok, ind), bot.atr_ngay_cho_gio(dg, d, bot.atr_ngay(d)), bot.TARGET)
                lenh[("gio", "supertrend")] += ig["stt"]["lenh"]; lenh[("gio", "bat_day")] += ig["bd"]["lenh"]
        for (k, cl), ds in lenh.items():
            kq[(ten, k, cl)] = thong_ke(ds)
        print("Xong Target:", ten)
    bot.TARGET.clear(); bot.TARGET.update(goc)
    return kq


# Các cách dùng khung 1 giờ đem ra so sánh (xem GIO trong bot.py)
SO_GIO = [
    ("A. Như cũ", dict(che_do="A")),
    ("B. Lọc chặt theo khung ngày", dict(che_do="B")),
    ("C. Khung ngày vừa XANH ≤ 5 phiên", dict(che_do="C", cua_so=5)),
    ("C. Khung ngày vừa XANH ≤ 10 phiên", dict(che_do="C", cua_so=10)),
    ("D. Vào theo giờ, ra theo ngày", dict(che_do="D")),
    ("B+D", dict(che_do="BD")),
    ("C+D (≤ 5 phiên)", dict(che_do="CD", cua_so=5)),
    ("C+D (≤ 10 phiên)", dict(che_do="CD", cua_so=10)),
]


def so_sanh_gio(data, gio):
    """Chạy từng cách dùng khung 1 giờ. Thêm dòng tham chiếu: khung ngày trong CÙNG khoảng thời gian."""
    goc = copy.deepcopy(bot.GIO)
    cs = bot.chi_so_deu(list(data.values()))
    vni = bot.thi_truong_ok(cs)
    tu = min(g["t"][0][:10] for g in gio.values())
    ngay = {m: (d, bot.loc_mua_ngay(d, vni)) for m, d in data.items()}
    ind_ngay = {m: bot.tinh_chien_luoc(d, {"supertrend": ok, "bat_day": ok}) for m, (d, ok) in ngay.items()}
    kq = {}
    for cl, nguon in (("supertrend", "stt"), ("bat_day", "bd")):
        ds = [x for m in data for x in ind_ngay[m][nguon]["lenh"] if x["ngay_mua"] >= tu and m in gio]
        kq[("Tham chiếu: khung NGÀY cùng thời gian", cl)] = thong_ke(ds)
    for ten, cau_hinh in SO_GIO:
        bot.GIO.clear(); bot.GIO.update(goc)
        bot.GIO.update(st=cau_hinh["che_do"], bd=cau_hinh["che_do"], cua_so=cau_hinh.get("cua_so", 5))
        lenh = {"supertrend": [], "bat_day": []}
        for m, dg in gio.items():
            if m not in ngay:
                continue
            d, ok = ngay[m]
            ig = bot.tinh_chien_luoc_gio(dg, d, ok, ind_ngay[m])
            lenh["supertrend"] += ig["stt"]["lenh"]; lenh["bat_day"] += ig["bd"]["lenh"]
        for cl in lenh:
            kq[(ten, cl)] = thong_ke(lenh[cl])
        print("Xong khung giờ:", ten)
    bot.GIO.clear(); bot.GIO.update(goc)
    return kq, tu


def dat_cau_hinh(thay_doi):
    cfg = dict(TAT, **thay_doi)
    bot.LOC.update(gtgd_min=cfg["gtgd_min"], ema_chi_so=cfg["ema_chi_so"],
                   lo_toi_da=cfg["lo_toi_da"], ve_von=cfg["ve_von"])
    bot.BAT_DAY["qua_han"] = cfg["qua_han"]


def thong_ke(lenh):
    if not lenh:
        return None
    lai = [x["lai"] - PHI for x in lenh]
    thang = [x for x in lai if x > 0]
    thua = [x for x in lai if x <= 0]
    return dict(
        so=len(lai),
        thang=100 * len(thang) / len(lai),
        tb=sum(lai) / len(lai),
        tb_thang=sum(thang) / len(thang) if thang else 0,
        tb_thua=sum(thua) / len(thua) if thua else 0,
        max_lo=min(lai),
        pf=(sum(thang) / -sum(thua)) if thua and sum(thua) < 0 else float("inf"),
        phien=sum(x["phien"] for x in lenh) / len(lenh),
    )


def so(x, d=2):
    return bot.so(x, d)


def main():
    ds = list(dict.fromkeys(bot.DANH_SACH_MA.split()))
    if "--test" in sys.argv:
        ds = ds[:5]
    print(f"Tải dữ liệu {len(ds)} mã...")
    with ThreadPoolExecutor(8) as ex:
        data = dict(zip(ds, ex.map(lambda m: bot._safe(tai_ngay, m), ds)))
    data = {m: d for m, d in data.items() if isinstance(d, dict) and len(d["c"]) > 120}
    print(f"Có dữ liệu {len(data)}/{len(ds)} mã")
    cs = bot.chi_so_deu(list(data.values()))
    tu = min(d["t"][0] for d in data.values())
    den = max(d["t"][-1] for d in data.values())

    goc_loc, goc_bd = copy.deepcopy(bot.LOC), copy.deepcopy(bot.BAT_DAY)
    kq = {}          # (tên phương án, chiến lược) -> thống kê
    lenh_moi = {"supertrend": [], "bat_day": []}
    for ten, thay_doi in PHUONG_AN:
        dat_cau_hinh(thay_doi)
        vni = bot.thi_truong_ok(cs)
        tat_ca = {"supertrend": [], "bat_day": []}
        for m, d in data.items():
            ok = bot.loc_mua_ngay(d, vni)
            ind = bot.tinh_chien_luoc(d, {"supertrend": ok, "bat_day": ok})
            for key, nguon in (("supertrend", ind["stt"]), ("bat_day", ind["bd"])):
                for x in nguon["lenh"]:
                    tat_ca[key].append(dict(x, ma=m))
        for key in tat_ca:
            kq[(ten, key)] = thong_ke(tat_ca[key])
        if thay_doi is MOI:
            lenh_moi = tat_ca
        print("Xong:", ten)
    bot.LOC.clear(); bot.LOC.update(goc_loc)
    bot.BAT_DAY.clear(); bot.BAT_DAY.update(goc_bd)

    # ----- So sánh cách đặt Target: khung ngày + khung 1 giờ (khoảng 80 ngày gần nhất) -----
    hom_nay = datetime.now(bot.VN).strftime("%Y-%m-%d")
    print("Tải nến 1 giờ...")
    with ThreadPoolExecutor(8) as ex:
        gio = dict(zip(data, ex.map(lambda m: bot._safe(bot.lich_su_1h, m, hom_nay), list(data))))
    gio = {m: g for m, g in gio.items() if isinstance(g, dict) and len(g.get("c", [])) > 60}
    print(f"Có nến 1 giờ của {len(gio)} mã")
    kq_t = so_sanh_target(data, gio)
    kq_g, tu_g = so_sanh_gio(data, gio)

    # ----- Ghi kết quả -----
    out = [f"# Kết quả backtest",
           f"",
           f"Chạy lúc {datetime.now(bot.VN).strftime('%H:%M %d/%m/%Y')} · {len(data)} mã · dữ liệu ngày từ "
           f"{bot.fmt_ngay(tu)} đến {bot.fmt_ngay(den)} · đã trừ phí + thuế {so(PHI, 1)}%/lệnh.",
           f"",
           f"**Cách đọc:** *Tỷ lệ thắng* = % lệnh có lãi. *Lãi TB/lệnh* = trung bình mỗi lệnh lãi bao nhiêu %, "
           f"**con số quan trọng nhất**. *Hệ số lợi nhuận* = tổng lãi của lệnh thắng ÷ tổng lỗ của lệnh thua "
           f"(trên 1,0 là có lãi, trên 1,5 là tốt).",
           ""]
    for key, ten_cl in bot.CHIEN_LUOC.items():
        out += [f"## {ten_cl} (khung ngày)", "",
                "| Phương án | Số lệnh | Tỷ lệ thắng | Lãi TB/lệnh | TB lệnh thắng | TB lệnh thua | Lỗ nặng nhất | Hệ số lợi nhuận | Số phiên giữ TB |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for ten, _ in PHUONG_AN:
            t = kq[(ten, key)]
            if not t:
                out.append(f"| {ten} | 0 | – | – | – | – | – | – | – |")
                continue
            pf = "∞" if t["pf"] == float("inf") else so(t["pf"])
            dam = "**" if ten.startswith(("BẢN MỚI", "Bản cũ")) else ""
            out.append(f"| {dam}{ten}{dam} | {t['so']} | {so(t['thang'], 1)}% | {dam}{so(t['tb'])}%{dam} | "
                       f"+{so(t['tb_thang'])}% | {so(t['tb_thua'])}% | {so(t['max_lo'])}% | {pf} | {so(t['phien'], 1)} |")
        # Lý do bán của bản mới
        ly = {}
        for x in lenh_moi[key]:
            r = ly.setdefault(x["ly"], [0, 0.0])
            r[0] += 1; r[1] += x["lai"] - PHI
        if ly:
            out += ["", f"Bản mới – lệnh được đóng vì lý do gì:", "", "| Lý do bán | Số lệnh | Lãi TB |", "|---|---:|---:|"]
            for k, (sl, tong) in sorted(ly.items(), key=lambda z: -z[1][0]):
                out.append(f"| {k} | {sl} | {so(tong / sl)}% |")
        out.append("")
    out += ["# So sánh cách đặt Target", "",
            f"Dùng cấu hình bộ lọc / quản lý lệnh hiện tại. Khung 1 giờ: {len(gio)} mã, khoảng 80 ngày gần nhất. "
            "Xếp theo *Lãi TB/lệnh* (cao xuống thấp). *Tổng* = cộng dồn % lãi của mọi lệnh.", ""]
    for khung, ten_k in (("ngay", "khung ngày"), ("gio", "khung 1 giờ")):
        for key, ten_cl in bot.CHIEN_LUOC.items():
            out += [f"## {ten_cl} ({ten_k})", "",
                    "| Cách đặt Target | Số lệnh | Tỷ lệ thắng | Lãi TB/lệnh | Tổng | Hệ số lợi nhuận | Số phiên giữ TB |",
                    "|---|---:|---:|---:|---:|---:|---:|"]
            hang = sorted(SO_TARGET, key=lambda x: -((kq_t[(x[0], khung, key)] or {}).get("tb", -999)))
            for ten, _ in hang:
                t = kq_t[(ten, khung, key)]
                if not t:
                    out.append(f"| {ten} | 0 | – | – | – | – | – |"); continue
                pf = "∞" if t["pf"] == float("inf") else so(t["pf"])
                out.append(f"| {ten} | {t['so']} | {so(t['thang'], 1)}% | **{so(t['tb'])}%** | {so(t['tb'] * t['so'], 0)}% | {pf} | {so(t['phien'], 1)} |")
            out.append("")
    out += ["# So sánh cách dùng khung 1 giờ", "",
            f"Nến 1 giờ từ {bot.fmt_ngay(tu_g)} ({len(gio)} mã). Dòng *Tham chiếu* = chiến lược khung NGÀY trong cùng thời gian, "
            "để biết thị trường giai đoạn này khó hay dễ. Xếp theo *Lãi TB/lệnh*.", ""]
    for key, ten_cl in bot.CHIEN_LUOC.items():
        out += [f"## {ten_cl} (khung 1 giờ)", "",
                "| Cách dùng | Số lệnh | Tỷ lệ thắng | Lãi TB/lệnh | Tổng | Hệ số lợi nhuận | Lỗ nặng nhất | Số phiên giữ TB |",
                "|---|---:|---:|---:|---:|---:|---:|---:|"]
        ten_all = ["Tham chiếu: khung NGÀY cùng thời gian"] + [x[0] for x in SO_GIO]
        for ten in sorted(ten_all, key=lambda x: -((kq_g[(x, key)] or {}).get("tb", -999))):
            t = kq_g[(ten, key)]
            if not t:
                out.append(f"| {ten} | 0 | – | – | – | – | – | – |"); continue
            pf = "∞" if t["pf"] == float("inf") else so(t["pf"])
            dam = "*" if ten.startswith("Tham") else ""
            out.append(f"| {dam}{ten}{dam} | {t['so']} | {so(t['thang'], 1)}% | **{so(t['tb'])}%** | {so(t['tb'] * t['so'], 0)}% | {pf} | {so(t['max_lo'])}% | {so(t['phien'], 1)} |")
        out.append("")
    if "--test" not in sys.argv:
        open("KET_QUA_BACKTEST.md", "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
