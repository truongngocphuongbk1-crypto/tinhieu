# -*- coding: utf-8 -*-
"""
BOT TÍN HIỆU CỔ PHIẾU -> TELEGRAM + TRANG WEB
Chạy tự động trên GitHub Actions mỗi 5 phút trong giờ giao dịch.

Việc bot làm mỗi lần chạy:
  1. Lấy giá nến ngày của các mã trong DANH_SACH_MA (gồm cả phiên hôm nay đang chạy)
  2. Tính 2 chiến lược: SuperTrend (10,3) và Bắt Đáy (kênh giá + tam giác), mỗi chiến lược có Khung 1 ngày và Khung 1 giờ
  3. Có tín hiệu MUA/BÁN mới trong hôm nay -> gửi Telegram (mỗi tín hiệu chỉ gửi 1 lần)
  4. Ghi file dữ liệu cho trang web vào thư mục site/

Chạy thử trên máy:   python bot.py --test     (chỉ lấy 3 mã, không gửi Telegram)
"""
import bisect, hashlib, json, os, sys, time, shutil, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# ============ PHẦN CẤU HÌNH (Sếp có thể sửa) ============
DANH_SACH_MA = """AAA ABB ACB AGR ANV APH ASM BAF BCM BFC BID BMP BSI BSR BVB BVS BVH CEO CII CMG CSM CST CTD CTR CTG CTS CSV DCL DCM DDV DGC DGW DHC DIG DPG DPM DPR DRC DRI DXG DXS DXP EIB EVF EVG FCN FMC FOX FPT FRT FTS GAS GEE GEG GEL GEX GIL GMD GVR HAG HAH HBC HDB HDC HDG HHV HHS HII HNG HPG HSG HT1 HUT IDC IDI KBC KDH KHG KLB KOS KSV LAS LCG LDG LPS LPB MBB MCH MML MSB MSH MSN MSR MWG NAB NKG NLG NTL NTP NVB NVL OCB OIL ORS PAC PAN PC1 PDR PET PHP PHR PLC PLX PNJ POW PPC PVC PVB PVD PVP PVS PVT QTP REE SAB SBS SHB SHS SIP SJD SSB SSI STB SZC TCB TCH TCM TCX TNG TPB TV2 TVN TVS VCB VCK VCI VDS VFS VGC VGI VGS VGT VHC VHM VIB VIC VIX VJC VND VNM VOS VPI VPB VPL VPX VRE VSC VTO VTP VVS"""
CHI_SO = ["VNINDEX", "VN30"]

CHIEN_LUOC = {                      # khóa nội bộ -> tên hiện trên web/Telegram
    "supertrend": "SuperTrend (10, 3)",
    "bat_day": "Bắt Đáy",
}
# Tên tab Khung 1 giờ của từng chiến lược (trên web là nút "Khung 1 giờ" bên trong tab chính)
TEN_1H_CL = {"supertrend": "SuperTrend (1 giờ)", "bat_day": "Bắt Đáy (1 giờ)"}
# ----- Bộ lọc & quản lý lệnh: áp dụng cho CẢ 2 chiến lược -----
LOC = dict(
    gtgd_min=1,       # chỉ MUA mã có giá trị giao dịch TB 20 phiên >= bấy nhiêu TỶ đồng (đặt 0 = tắt)
    ema_chi_so=0,     # đang TẮT (0): thị trường xấu vẫn báo Xanh/Hồng bình thường. Đặt 50 để bật lại:
                      # chỉ MUA khi CHỈ SỐ ĐỀU (trung bình mọi mã, mỗi mã như nhau) trên EMA bấy nhiêu phiên (0 = tắt)
                      # (không dùng VNINDEX vì bị vài mã vốn hóa lớn như nhóm Vin chi phối)
    lo_toi_da=7,      # giá đóng cửa lỗ quá bấy nhiêu % so với giá mua -> BÁN (cắt lỗ cứng)
    ve_von=True,      # chạm Target 1 -> dời cắt lỗ lên bằng giá mua (True = bật, False = tắt)
)
# SuperTrend: Target 1 / Target 2 = giá mua + bấy nhiêu lần ATR (độ biến động trung bình)
SUPERTREND = dict(
    n=10, he_so=3.0,  # thông số SuperTrend (10, 3)
    atr=14,           # độ dài ATR dùng để tính Target
    t1_atr=2,         # Target 1 = giá mua + 2 x ATR   (chạm -> bán 1/3)
    t2_atr=4,         # Target 2 = giá mua + 4 x ATR   (chạm -> bán thêm 1/3)
    t_min=2,          # chỉ báo cắt lỗ từ T+ này trở đi
    chi_dao_chieu=True,  # True: chỉ báo HỒNG khi SuperTrend đảo xuống (bỏ cắt lỗ 7% và về vốn sau Target 1)
)
# ----- CÁCH ĐẶT TARGET (cho cả SuperTrend và Bắt Đáy, cả khung ngày và khung 1 giờ) -----
# kieu = "kenh"  : cách cũ (SuperTrend: ATR của chính khung đó; Bắt Đáy: đường giữa / dải trên, di chuyển theo kênh)
#        "atr"   : Target = giá mua + t1_atr / t2_atr x ATR(14) của khung NGÀY
#        "r"     : Target = giá mua + t1_r / t2_r x R   (R = giá mua - mức cắt lỗ lúc mua)
#        "atr_r" : lấy mức CAO HƠN giữa "atr" và "r"
# Khung 1 giờ cũng dùng ATR NGÀY, vì mua xong phải đủ T+2 mới bán được -> giữ hàng tính bằng ngày.
TARGET = dict(
    kieu="atr",
    t1_atr=2, t2_atr=4,     # số lần ATR ngày
    t1_r=1.5, t2_r=3,       # số lần R
    t1_min=5, t2_min=10,    # Target tối thiểu (% so với giá mua)
    theo_kenh=True,         # Bắt Đáy: Target không thấp hơn đường giữa / dải trên lúc mua
)
# Bắt Đáy: Target 1 = đường giữa kênh, Target 2 = dải trên (thay đổi theo kênh, không phải % cố định)
BAT_DAY = dict(
    do_dai=50,        # độ dài đường giữa (EMA)
    atr=50,           # độ dài ATR
    he_so=2.5,        # độ rộng dải = ATR x hệ số
    rsi=14,           # độ dài RSI
    qua_mua=70,       # RSI >= mức này + chạm dải trên -> chấm cam trên (CHỜ BÁN)
    qua_ban=30,       # RSI <= mức này + chạm dải dưới -> chấm cam dưới (CHỜ MUA)
    cho=10,           # sau chấm cam cuối cùng, chờ tam giác tối đa bao nhiêu phiên
    t_min=2,          # đang giữ hàng: chỉ báo chốt lời / cắt lỗ / bán từ T+ này trở đi
    qua_han=20,       # giữ bấy nhiêu phiên mà chưa chạm Target 1 -> BÁN (đặt 0 = tắt)
)
# ----- TÀI KHOẢN ẢO: mỗi chiến lược 1 tài khoản, tự mua/bán theo tín hiệu khung ngày -----
TAI_KHOAN = dict(
    von=1_000_000_000,  # vốn ban đầu mỗi tài khoản (đồng)
    so_ma=10,           # giữ tối đa bấy nhiêu mã; mỗi mã mua khoảng 1/10 tổng tài sản
    phi_mua=0.15,       # % phí khi mua
    phi_ban=0.25,       # % phí + thuế khi bán (0,15% phí + 0,1% thuế)
    gio_chot=15,        # từ giờ này (giờ VN) bot mới chốt giao dịch của phiên, theo giá đóng cửa
)
CHO_MUA_CACH = 0.03                 # giá cách điểm kích hoạt <= 3% thì đưa vào "Chờ mua"
SO_NEN_LUU_DO_THI = 150             # số phiên lưu cho đồ thị trên web
GIO_TONG_KET = 15                   # sau 15h (giờ VN) gửi 1 tin tổng kết phiên

# Phân ngành (mỗi dòng: Tên ngành: các mã). Mã không có ở đây sẽ vào nhóm "Khác".
NGANH = """
Ngân hàng: ABB ACB BID BVB CTG EIB HDB KLB LPB MBB MSB NAB NVB OCB SHB SSB STB TCB TPB VCB VIB VPB
Chứng khoán: AGR BSI BVS CTS FTS LPS ORS SBS SHS SSI TCX TVS VCI VCK VDS VFS VIX VND VPX
BĐS dân cư: CEO DIG DXG DXS EVG HDC KDH KHG KOS LDG NLG NTL NVL PDR TCH VHM VIC VPI VPL VRE
BĐS KCN: BCM GVR IDC KBC SIP SZC VGC
Xây dựng & Đầu tư công: CII CTD DPG FCN HBC HHV HUT LCG
Vật liệu XD & Nhựa: AAA APH BMP HII HT1 NTP
Thép: HPG HSG NKG TVN VGS
Dầu khí: BSR GAS OIL PLC PLX PVB PVC PVD PVP PVS PVT
Điện & Năng lượng: GEE GEG GEL GEX HDG PC1 POW PPC QTP REE SJD TV2
Hóa chất & Phân bón: BFC CSV DCM DDV DGC DPM LAS
Cao su: CSM DPR DRC DRI PHR
Thủy sản: ANV ASM FMC IDI VHC
Dệt may: GIL MSH TCM TNG VGT
Bán lẻ & Phân phối: DGW FRT MWG PET PNJ
Thực phẩm & Nông nghiệp: BAF HAG HNG MCH MML MSN PAN SAB VNM
Cảng, Vận tải & Hàng không: DXP GMD HAH HHS PHP VJC VOS VSC VTO VTP
Công nghệ & Viễn thông: CMG CTR FOX FPT VGI
Bảo hiểm & Tài chính: BVH EVF
Khoáng sản & Than: CST KSV MSR
"""
MA_NGANH = {m: dong.split(":")[0].strip() for dong in NGANH.strip().splitlines() for m in dong.split(":")[1].split()}
# ========================================================

VN = timezone(timedelta(hours=7))
ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
STATE_FILE = os.path.join(ROOT, "state.json")
UA = {"User-Agent": "Mozilla/5.0 (signal-bot)"}


# ---------------- Lấy dữ liệu ----------------
def http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def tai_15p(ma, loai, tu, den):
    url = (f"https://services.entrade.com.vn/chart-api/v2/ohlcs/{loai}?symbol={ma}"
           f"&resolution=15&from={tu}&to={den}")
    return http_json(url)


def gom_1h(j, chon):
    """Gộp nến 15 phút (các vị trí trong 'chon') thành nến 1 giờ: 9h, 10h, 11h, 13h, 14h."""
    out = dict(t=[], o=[], h=[], l=[], c=[], v=[])
    for i in chon:
        nhan = datetime.fromtimestamp(j["t"][i], VN).strftime("%Y-%m-%d %H:00")
        if out["t"] and out["t"][-1] == nhan:
            out["h"][-1] = max(out["h"][-1], j["h"][i])
            out["l"][-1] = min(out["l"][-1], j["l"][i])
            out["c"][-1] = j["c"][i]
            out["v"][-1] += j["v"][i]
        else:
            for k in "ohlcv":
                out[k].append(j[k][i])
            out["t"].append(nhan)
    return out


def nen_15p_hom_nay(ma, loai, hom_nay):
    now = int(time.time())
    j = tai_15p(ma, loai, now - 86400, now + 900)
    ds = [i for i, x in enumerate(j.get("t") or [])
          if datetime.fromtimestamp(x, VN).strftime("%Y-%m-%d") == hom_nay]
    return j, ds


import threading
TAI_1H_MOI_LUOT = 40          # mỗi lượt chạy chỉ tải lịch sử nến 1 giờ cho tối đa bấy nhiêu mã
TAI_1H_TOI_DA_GIAY = 180      # ... và không quá bấy nhiêu giây (các lượt sau tải tiếp, đã tải thì lưu đệm)
_khoa_1h = threading.Lock()
_dem_1h = [0, time.time()]


def duoc_tai_1h():
    """Giới hạn số mã tải lịch sử 1 giờ trong 1 lượt để bot không chạy quá lâu."""
    with _khoa_1h:
        if _dem_1h[0] >= TAI_1H_MOI_LUOT or time.time() - _dem_1h[1] > TAI_1H_TOI_DA_GIAY:
            return False
        _dem_1h[0] += 1
        return True


def lich_su_1h(ma, hom_nay):
    """Nến 1 giờ của khoảng 80 ngày gần nhất (không gồm hôm nay), gộp từ nến 15 phút."""
    now = int(time.time())
    j = tai_15p(ma, "stock", now - 86400 * 80, now + 900)
    chon = [i for i, x in enumerate(j.get("t") or [])
            if datetime.fromtimestamp(x, VN).strftime("%Y-%m-%d") < hom_nay]
    return gom_1h(j, chon)


def them_nen_hom_nay(d, j, ds, hom_nay):
    """DNSE chỉ tạo nến ngày sau khi hết phiên. Trong phiên, gộp nến 15 phút của hôm nay
    thành 1 nến ngày tạm thời rồi gắn vào cuối, để giá / T+ / tín hiệu cập nhật theo thời gian thực."""
    if d["t"] and d["t"][-1] >= hom_nay:
        return
    if not ds:
        return
    d["t"].append(hom_nay)
    d["o"].append(j["o"][ds[0]])
    d["h"].append(max(j["h"][i] for i in ds))
    d["l"].append(min(j["l"][i] for i in ds))
    d["c"].append(j["c"][ds[-1]])
    d["v"].append(sum(j["v"][i] for i in ds))


CACHE_DIR = os.path.join(ROOT, "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "nen_ngay.json")
CACHE_DA_DOI = os.path.join(CACHE_DIR, "da_doi.txt")


def doc_cache(hom_nay):
    """Đọc nến ngày đã lưu (bộ nhớ đệm). Chỉ dùng nếu được lưu trong hôm nay.
    Nhờ vậy mỗi 5 phút bot chỉ phải tải nến 15 phút của hôm nay -> nhanh, không bị nguồn chặn."""
    try:
        os.remove(CACHE_DA_DOI)
    except Exception:
        pass
    try:
        c = json.load(open(CACHE_FILE, encoding="utf-8"))
        if c.get("ngay") == hom_nay:
            print(f"Dùng nến ngày đã lưu của {len(c.get('data', {}))} mã")
            return c.get("data", {})
    except Exception:
        pass
    print("Chưa có nến ngày đã lưu cho hôm nay -> tải mới")
    return {}


def ghi_cache(hom_nay, cache, moi):
    if not moi:
        return
    cache.update(moi)
    os.makedirs(CACHE_DIR, exist_ok=True)
    json.dump({"ngay": hom_nay, "data": cache}, open(CACHE_FILE, "w", encoding="utf-8"),
              separators=(",", ":"))
    open(CACHE_DA_DOI, "w").write(str(len(moi)))
    print(f"Đã lưu thêm nến ngày của {len(moi)} mã")


def lay_gia_nhanh(ma, la_chi_so, cache, moi):
    """Nến ngày: lấy từ bộ nhớ đệm nếu có, không thì tải. Sau đó gắn nến trong phiên hôm nay."""
    khoa = ("CS:" if la_chi_so else "") + ma
    goc = cache.get(khoa)
    nguon = "DNSE (đã lưu)"
    if goc is None:
        d = lay_gia(ma, la_chi_so)
        nguon = d.get("nguon", "DNSE")
        goc = {k: list(d[k]) for k in "tohlcv"}
        if len(goc["c"]) > 30:
            moi[khoa] = goc
    d = {k: list(goc[k]) for k in "tohlcv"}
    d["nguon"] = nguon
    loai = "index" if la_chi_so else "stock"
    hom_nay = datetime.now(VN).strftime("%Y-%m-%d")
    # Nến 1 giờ (chỉ cổ phiếu): lịch sử lấy 1 lần/ngày rồi lưu đệm, hôm nay gộp từ nến 15 phút
    gio = None
    if not la_chi_so:
        gio = cache.get("H:" + ma)
        if gio is None and duoc_tai_1h():
            try:
                gio = lich_su_1h(ma, hom_nay)
                if len(gio["c"]) > 60:
                    moi["H:" + ma] = gio
            except Exception as e:
                print(f"{ma}: chưa lấy được nến 1 giờ ({e})")
    can_15p = not la_chi_so or not (d["t"] and d["t"][-1] >= hom_nay)
    j, ds = None, []
    if can_15p:
        for lan in range(3):
            try:
                j, ds = nen_15p_hom_nay(ma, loai, hom_nay)
                break
            except Exception as e:
                if lan == 2:
                    print(f"{ma}: chưa lấy được nến trong phiên ({e})")
                time.sleep(2)
    if j:
        them_nen_hom_nay(d, j, ds, hom_nay)
        # Dòng tiền trong phiên: cộng KL các nến 15 phút tăng (mua chủ động) và giảm (bán chủ động)
        if ds and not la_chi_so:
            mua = ban = 0.0
            for i in ds:
                v = j["v"][i] or 0
                if j["c"][i] > j["o"][i]:
                    mua += v
                elif j["c"][i] < j["o"][i]:
                    ban += v
                else:
                    mua += v / 2
                    ban += v / 2
            d["dt"] = [mua, ban]
    if gio and len(gio["c"]) > 60:
        d["gio"] = {k: list(gio[k]) for k in "tohlcv"}
        if j and ds:
            hn = gom_1h(j, ds)
            for k in "tohlcv":
                d["gio"][k] += hn[k]
    return d


def nguon_dnse(ma, la_chi_so=False):
    now = int(time.time())
    loai = "index" if la_chi_so else "stock"
    url = (f"https://services.entrade.com.vn/chart-api/v2/ohlcs/{loai}?symbol={ma}"
           f"&resolution=1D&from={now - 86400 * 420}&to={now + 86400}")
    j = http_json(url)
    if not j.get("t"):
        raise ValueError("rỗng")
    t = [datetime.fromtimestamp(x, VN).strftime("%Y-%m-%d") for x in j["t"]]
    return dict(t=t, o=list(j["o"]), h=list(j["h"]), l=list(j["l"]), c=list(j["c"]), v=list(j["v"]))


def nguon_tcbs(ma, la_chi_so=False):
    now = int(time.time())
    loai = "index" if la_chi_so else "stock"
    url = (f"https://apipubaws.tcbs.com.vn/stock-insight/v2/stock/bars-long-term?ticker={ma}"
           f"&type={loai}&resolution=D&to={now + 86400}&countBack=300")
    rows = http_json(url).get("data") or []
    if not rows:
        raise ValueError("rỗng")
    k = 1 if la_chi_so else 1000.0   # TCBS trả giá cổ phiếu theo đồng -> đổi ra nghìn đồng
    return dict(t=[r["tradingDate"][:10] for r in rows],
                o=[r["open"] / k for r in rows], h=[r["high"] / k for r in rows],
                l=[r["low"] / k for r in rows], c=[r["close"] / k for r in rows],
                v=[r["volume"] for r in rows])


NGUON = [("DNSE", nguon_dnse), ("TCBS", nguon_tcbs)]


def lay_gia(ma, la_chi_so=False):
    loi = []
    for ten, fn in NGUON:
        for _ in range(2):
            try:
                d = fn(ma, la_chi_so)
                d["nguon"] = ten
                return d
            except Exception as e:
                loi.append(f"{ten}: {e}")
                time.sleep(0.5)
    raise RuntimeError("; ".join(loi[-2:]))


# ---------------- Dòng tiền trong phiên ----------------
PHIEN = [(9 * 60, 11 * 60 + 30), (13 * 60, 14 * 60 + 45)]   # giờ khớp lệnh HOSE (phút trong ngày)
TONG_PHUT = sum(b - a for a, b in PHIEN)                     # 255 phút


def ty_le_phien(now):
    """Phần phiên đã trôi qua (0..1). Tối thiểu 15 phút để đầu phiên không bị phóng đại."""
    p = now.hour * 60 + now.minute
    da = sum(max(0, min(p, b) - a) for a, b in PHIEN)
    return max(15, da) / TONG_PHUT


def dong_tien(d, now, hom_nay):
    """Trả về [giá, %thay đổi, KL/TB (lần), ròng chủ động (-1..1), GTGD (tỷ), điểm sức mạnh]."""
    c, v = d["c"], d["v"]
    if len(c) < 22:
        return None
    hom_nay_co = d["t"][-1] == hom_nay
    frac = ty_le_phien(now) if hom_nay_co else 1.0     # chưa vào phiên -> dùng phiên gần nhất, đủ cả phiên
    tb20 = sum(v[-21:-1]) / 20
    if tb20 <= 0:
        return None
    ratio = v[-1] / (tb20 * frac)
    if hom_nay_co and d.get("dt") and sum(d["dt"]) > 0:
        mua, ban = d["dt"]
        net = (mua - ban) / (mua + ban)
    else:   # không có nến 15 phút: ước lượng bằng vị trí giá đóng cửa trong biên độ ngày
        h, l = d["h"][-1], d["l"][-1]
        net = ((c[-1] - l) - (h - c[-1])) / (h - l) if h > l else 0.0
    chg = (c[-1] / c[-2] - 1) * 100 if c[-2] else 0.0
    gt = v[-1] * c[-1] / 1e6            # giá theo nghìn đồng -> tỷ đồng
    diem = ratio * (1 + abs(net) * 0.5)
    return [round(c[-1], 2), round(chg, 2), round(ratio, 2), round(net, 3), round(gt, 1), round(diem, 2)]


# ---------------- Chỉ báo ----------------
def ema(a, n):
    k, out, prev = 2 / (n + 1), [], None
    for x in a:
        prev = x if prev is None else x * k + prev * (1 - k)
        out.append(prev)
    return [None if i < n - 1 else v for i, v in enumerate(out)]


def sma(a, n):
    out, s = [], 0.0
    for i, x in enumerate(a):
        s += x
        if i >= n:
            s -= a[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def bollinger(c, n=20, k=2):
    m = sma(c, n)
    u, d = [], []
    for i, v in enumerate(m):
        if v is None:
            u.append(None); d.append(None); continue
        w = c[i - n + 1:i + 1]
        sd = (sum((x - v) ** 2 for x in w) / n) ** 0.5
        u.append(v + k * sd); d.append(v - k * sd)
    return u, d


def supertrend(h, l, c, n=10, m=3.0):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    atr = [None] * len(c)
    for i in range(len(c)):
        if i == n - 1:
            atr[i] = sum(tr[:n]) / n
        elif i >= n:
            atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    st, up = [None] * len(c), [None] * len(c)
    fu = fd = None
    trend = 1
    for i in range(len(c)):
        if atr[i] is None:
            continue
        hl2 = (h[i] + l[i]) / 2
        bu, bd = hl2 - m * atr[i], hl2 + m * atr[i]
        if fu is None:
            fu, fd = bu, bd
        else:
            fu = max(bu, fu) if c[i - 1] > fu else bu
            fd = min(bd, fd) if c[i - 1] < fd else bd
            if trend == -1 and c[i] > fd:
                trend = 1
            elif trend == 1 and c[i] < fu:
                trend = -1
        st[i] = fu if trend == 1 else fd
        up[i] = 1 if trend == 1 else 0
    return st, up


def rma(a, n):
    """Trung bình kiểu Wilder (giống ta.rma của TradingView), dùng cho ATR và RSI."""
    out, prev = [None] * len(a), None
    for i, x in enumerate(a):
        if i == n - 1:
            prev = sum(a[:n]) / n
        elif i >= n:
            prev = (prev * (n - 1) + x) / n
        if i >= n - 1:
            out[i] = prev
    return out


def rsi(c, n=14):
    tang = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    giam = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    out = [None]
    for u, dd in zip(rma(tang, n), rma(giam, n)):
        out.append(None if u is None else 100.0 if dd == 0 else 100 - 100 / (1 + u / dd))
    return out


def true_range(h, l, c):
    return [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]


def chi_so_ngay(t):
    """Số thứ tự ngày giao dịch của từng nến (khung 1 giờ: nhiều nến chung 1 ngày) -> tính T+ theo ngày."""
    so_ngay, di = 0, []
    for i, x in enumerate(t):
        if i and x[:10] != t[i - 1][:10]:
            so_ngay += 1
        di.append(so_ngay)
    return di


def ghi_lenh(vao, i_vao, i_ra, gia_ra, da_ban, ly_do, di, t):
    """Ghi 1 lệnh đã đóng (dùng cho backtest). da_ban = các lần bán bớt [(tỷ lệ, giá)]."""
    con = 1 - sum(x for x, _ in da_ban)
    gia_tb = sum(x * g for x, g in da_ban) + con * gia_ra
    return dict(vao=vao, ra=gia_tb, lai=(gia_tb / vao - 1) * 100, phien=di[i_ra] - di[i_vao],
                ngay_mua=t[i_vao], ngay_ban=t[i_ra], ly=ly_do)


def gia_khop(muc, o):
    """Giá bán khi chạm 1 mức (Target): nếu phiên mở cửa đã vượt mức thì lấy giá mở cửa."""
    return o if o > muc else muc


def tinh_target(vao, atr_ng, sl, t1_kenh, t2_kenh):
    """(Target 1, Target 2) lúc mua, theo TARGET['kieu']. Kiểu "kenh" trả về đúng mức theo kênh/ATR khung hiện tại."""
    T = TARGET
    if T["kieu"] == "kenh":
        return t1_kenh, t2_kenh
    a = atr_ng or 0
    R = max(vao - sl, 0) if sl else 0
    t1a, t2a = vao + T["t1_atr"] * a, vao + T["t2_atr"] * a
    t1r, t2r = vao + T["t1_r"] * R, vao + T["t2_r"] * R
    if T["kieu"] == "atr":
        t1, t2 = t1a, t2a
    elif T["kieu"] == "r":
        t1, t2 = t1r, t2r
    else:
        t1, t2 = max(t1a, t1r), max(t2a, t2r)
    t1 = max(t1, vao * (1 + T["t1_min"] / 100))
    t2 = max(t2, vao * (1 + T["t2_min"] / 100))
    return t1, max(t2, t1 * 1.02)


def atr_ngay(d):
    """ATR(14) của nến ngày."""
    return rma(true_range(d["h"], d["l"], d["c"]), 14)


def atr_ngay_cho_gio(dg, d, atr_d):
    """Với mỗi nến 1 giờ: ATR ngày của phiên NGÀY gần nhất trước đó."""
    out = []
    for x in dg["t"]:
        j = bisect.bisect_left(d["t"], x[:10]) - 1
        out.append(atr_d[j] if j >= 0 else None)
    return out


def bat_day(d, mo=None, atr_ng=None):
    """Chiến lược BẮT ĐÁY: kênh xu hướng (EMA 50 ± 2,5 x ATR 50) + RSI + tam giác xác nhận.
    - Chấm cam dưới: giá chạm dải dưới và RSI <= 30 -> CHỜ MUA
    - Chấm cam trên: giá chạm dải trên và RSI >= 70 -> CHỜ BÁN
    - Tam giác xanh (MUA): đang chờ mua, nến tăng và đóng cửa vượt đỉnh phiên trước
      (chỉ MUA khi bộ lọc 'mo' cho phép ở nến đó: thanh khoản, chỉ số đều, khung ngày...)
    - Đang giữ hàng (từ T+2):
        chạm đường giữa = Target 1 (bán 1/2, dời cắt lỗ về giá mua), chạm dải trên = Target 2 (bán hết),
        đóng cửa dưới mức cắt lỗ = BÁN (mức cắt lỗ = cao hơn trong 2 mức: đáy vùng cảnh báo / giá mua - 7%),
        tam giác đỏ = BÁN, quá 20 phiên chưa chạm Target 1 = BÁN."""
    P = BAT_DAY
    o, h, l, c = d["o"], d["h"], d["l"], d["c"]
    n = len(c)
    giua = ema(c, P["do_dai"])
    atr = rma(true_range(h, l, c), P["atr"])
    r = rsi(c, P["rsi"])
    tren = [None if giua[i] is None or atr[i] is None else giua[i] + atr[i] * P["he_so"] for i in range(n)]
    duoi = [None if giua[i] is None or atr[i] is None else giua[i] - atr[i] * P["he_so"] for i in range(n)]
    di = chi_so_ngay(d["t"])
    lo = LOC["lo_toi_da"] / 100
    b, s, ly, cam_tren, cam_duoi, lenh = [], [], {}, [], [], []
    cho_mua = cho_ban = False
    i_cm = i_cb = -1
    day_vung = None
    giu, vao, i_vao, sl, tp1, da_ban, day_mua = False, None, None, None, False, [], None
    t1 = t2 = None
    kenh = TARGET["kieu"] == "kenh"
    for i in range(1, n):
        if tren[i] is None or r[i] is None:
            continue
        # Hết hạn chờ: quá số phiên kể từ chấm cam cuối cùng
        if cho_mua and i - i_cm > P["cho"]:
            cho_mua = False
        if cho_ban and i - i_cb > P["cho"]:
            cho_ban = False
        tren_ok = h[i] >= tren[i] and r[i] >= P["qua_mua"]
        duoi_ok = l[i] <= duoi[i] and r[i] <= P["qua_ban"]
        if tren_ok:
            cam_tren.append(i); cho_ban = True; i_cb = i; cho_mua = False
        if duoi_ok:
            cam_duoi.append(i)
            if not cho_mua:
                day_vung = l[i]          # bắt đầu vùng cảnh báo mới
            cho_mua = True; i_cm = i; cho_ban = False
        if cho_mua:
            day_vung = min(day_vung, l[i])
        tg_ban = cho_ban and not tren_ok and c[i] < o[i] and c[i] < l[i - 1]
        tg_mua = cho_mua and not duoi_ok and c[i] > o[i] and c[i] > h[i - 1]
        if tg_ban:
            cho_ban = False
        if tg_mua:
            cho_mua = False

        thoat, gia_ra = None, c[i]
        if giu and di[i] - di[i_vao] >= P["t_min"]:
            m1, m2 = (giua[i], tren[i]) if kenh else (t1, t2)
            if not tp1 and h[i] >= m1:
                tp1 = True
                da_ban.append((0.5, gia_khop(m1, o[i])))
                if LOC["ve_von"]:
                    sl = max(sl, vao)
            if h[i] >= m2:
                thoat, gia_ra = "Chạm Target 2 - chốt hết", gia_khop(m2, o[i])
            elif c[i] < sl:
                if tp1 and LOC["ve_von"] and sl == vao:
                    thoat = "Về giá Xanh sau khi chạm Target 1"
                elif sl > day_mua:
                    thoat = f"Lỗ quá {LOC['lo_toi_da']}% - cắt lỗ"
                else:
                    thoat = "Thủng đáy vùng cảnh báo - cắt lỗ"
            elif tg_ban:
                thoat = "Tam giác đỏ"
            elif P["qua_han"] and not tp1 and di[i] - di[i_vao] >= P["qua_han"]:
                thoat = f"Quá {P['qua_han']} phiên chưa chạm Target 1"
        if thoat:
            s.append(i); ly[i] = thoat; giu = False
            lenh.append(ghi_lenh(vao, i_vao, i, gia_ra, da_ban, thoat, di, d["t"]))
        elif tg_ban and not giu:
            s.append(i); ly[i] = "Tam giác đỏ (Hồng nếu đang giữ mã này)"
        elif tg_mua and not giu and (mo is None or mo[i]):
            b.append(i); giu = True; vao = c[i]; i_vao = i; tp1 = False; da_ban = []
            day_mua = day_vung
            sl = max(day_vung, vao * (1 - lo))
            t1, t2 = tinh_target(vao, (atr_ng or [None] * n)[i], sl, giua[i], tren[i])
            if TARGET.get("theo_kenh") and not kenh:
                t1, t2 = max(t1, giua[i]), max(t2, tren[i])
    if giu and kenh:
        t1, t2 = giua[-1], tren[-1]
    return dict(giua=giua, tren=tren, duoi=duoi, b=b, s=s, ly=ly, cam_tren=cam_tren, cam_duoi=cam_duoi,
                giu=giu, vao=vao, i_vao=i_vao, sl=sl, tp1=tp1, cho_mua=cho_mua, cho_ban=cho_ban, lenh=lenh,
                t1=t1, t2=t2)


def chay_supertrend(d, mo=None, atr_ng=None):
    """Chiến lược SUPERTREND (10, 3):
    - MUA: SuperTrend đảo lên (chỉ khi bộ lọc 'mo' cho phép ở nến đó)
    - Target 1 = giá mua + 2 x ATR (bán 1/3, dời cắt lỗ về giá mua), Target 2 = giá mua + 4 x ATR (bán thêm 1/3)
    - BÁN: SuperTrend đảo xuống. (Nếu SUPERTREND['chi_dao_chieu'] = False: thêm cắt lỗ 7% / về giá mua sau Target 1.)"""
    P = SUPERTREND
    o, h, l, c, t = d["o"], d["h"], d["l"], d["c"], d["t"]
    n = len(c)
    st, up = supertrend(h, l, c, P["n"], P["he_so"])
    atr = rma(true_range(h, l, c), P["atr"])
    di = chi_so_ngay(t)
    lo = LOC["lo_toi_da"] / 100
    b, s, ly, lenh = [], [], {}, []
    giu, vao, i_vao, t1, t2, tp1, tp2, da_ban = False, None, None, None, None, False, False, []
    for i in range(1, n):
        if up[i] is None or up[i - 1] is None:
            continue
        dao_len = up[i] == 1 and up[i - 1] == 0
        dao_xuong = up[i] == 0 and up[i - 1] == 1
        if giu and i > i_vao:
            if not tp1 and h[i] >= t1:
                tp1 = True; da_ban.append((1 / 3, gia_khop(t1, o[i])))
            if tp1 and not tp2 and h[i] >= t2:
                tp2 = True; da_ban.append((1 / 3, gia_khop(t2, o[i])))
            san = max(vao * (1 - lo), vao if (tp1 and LOC["ve_von"]) else 0)
            thoat = None
            if dao_xuong:
                thoat = "SuperTrend đảo chiều giảm"
            elif not P["chi_dao_chieu"] and di[i] - di[i_vao] >= P["t_min"] and c[i] < san:
                thoat = "Về giá Xanh sau khi chạm Target 1" if (tp1 and LOC["ve_von"]) else f"Lỗ quá {LOC['lo_toi_da']}% - cắt lỗ"
            if thoat:
                s.append(i); ly[i] = thoat; giu = False
                lenh.append(ghi_lenh(vao, i_vao, i, c[i], da_ban, thoat, di, t))
                continue
        if dao_xuong and not giu and not (s and s[-1] == i):
            s.append(i); ly[i] = "SuperTrend đảo chiều giảm (Hồng nếu đang giữ mã này)"
        elif dao_len and not giu and atr[i] is not None and (mo is None or mo[i]):
            b.append(i); giu = True; vao = c[i]; i_vao = i; tp1 = tp2 = False; da_ban = []
            t1, t2 = tinh_target(vao, (atr_ng or [None] * n)[i], st[i],
                                 vao + P["t1_atr"] * atr[i], vao + P["t2_atr"] * atr[i])
    sl = None
    if giu:   # mức cắt lỗ hiện tại = cao nhất trong: đường SuperTrend, giá mua - 7%, (giá mua nếu đã chạm T1)
        sl = st[-1] if P["chi_dao_chieu"] else max(st[-1] or 0, vao * (1 - lo), vao if (tp1 and LOC["ve_von"]) else 0)
    return dict(st=st, up=up, b=b, s=s, ly=ly, lenh=lenh, giu=giu, vao=vao, i_vao=i_vao,
                t1=t1, t2=t2, tp1=tp1, tp2=tp2, sl=sl)


# ---------------- Bộ lọc MUA ----------------
def chi_so_deu(ds_data):
    """CHỈ SỐ ĐỀU: mỗi ngày lấy TRUNG BÌNH % tăng/giảm của tất cả các mã (mã nào cũng có trọng số như nhau),
    rồi cộng dồn thành 1 đường chỉ số (bắt đầu = 100). Nhờ vậy vài mã vốn hóa lớn không kéo lệch được.
    Ngày giảm/tăng quá 15% của 1 mã (chia cổ tức, tách cổ phiếu...) bị bỏ qua để không làm méo chỉ số."""
    tong = {}
    for d in ds_data:
        t, c = d["t"], d["c"]
        for i in range(1, len(c)):
            if c[i - 1]:
                r = c[i] / c[i - 1] - 1
                if abs(r) <= 0.15:
                    x = tong.setdefault(t[i][:10], [0.0, 0])
                    x[0] += r; x[1] += 1
    ngay = sorted(k for k, v in tong.items() if v[1] >= 5)
    out, gia = dict(t=[], c=[]), 100.0
    for k in ngay:
        s, n = tong[k]
        gia *= 1 + s / n
        out["t"].append(k); out["c"].append(gia)
    return out


def thi_truong_ok(cs):
    """{ngày: True/False}: chỉ số đều đóng cửa trên EMA (LOC['ema_chi_so']) hay không. Tắt bộ lọc -> {}."""
    n = LOC["ema_chi_so"]
    if not n or not isinstance(cs, dict) or len(cs.get("c", [])) < n:
        return {}
    e = ema(cs["c"], n)
    return {t: (x is None or c > x) for t, c, x in zip(cs["t"], cs["c"], e)}


def loc_mua_ngay(d, vni):
    """Danh sách True/False cho từng nến ngày: có được phép MUA không (thanh khoản + chỉ số đều).
    Thanh khoản tính trên 20 phiên TRƯỚC đó (không dùng phiên đang chạy dở)."""
    c, v, t = d["c"], d["v"], d["t"]
    gt = [x * y / 1e6 for x, y in zip(v, c)]          # giá nghìn đồng x KL -> tỷ đồng
    out, tong = [], 0.0
    for i in range(len(c)):
        tb = tong / 20 if i >= 20 else 0.0
        ok_tk = LOC["gtgd_min"] <= 0 or (i >= 20 and tb >= LOC["gtgd_min"])
        out.append(ok_tk and vni.get(t[i][:10], True))
        tong += gt[i]
        if i >= 20:
            tong -= gt[i - 20]
    return out


def loc_mua_gio(dg, d, ok_ngay, ind_ngay):
    """Bộ lọc cho Khung 1 giờ, dựa vào phiên NGÀY gần nhất trước đó:
    - cả 2: thanh khoản + chỉ số đều của phiên ngày đó phải đạt
    - SuperTrend 1 giờ: SuperTrend khung ngày đang tăng
    - Bắt Đáy 1 giờ: giá ngày đóng cửa trên dải dưới của kênh ngày (khung ngày không còn rơi)"""
    ngay, duoi, up = d["t"], ind_ngay["bd"]["duoi"], ind_ngay["u"]
    st_ok, bd_ok = [], []
    for x in dg["t"]:
        j = bisect.bisect_left(ngay, x[:10]) - 1
        if j < 0:
            st_ok.append(False); bd_ok.append(False); continue
        st_ok.append(ok_ngay[j] and up[j] == 1)
        bd_ok.append(ok_ngay[j] and (duoi[j] is None or d["c"][j] > duoi[j]))
    return {"supertrend": st_ok, "bat_day": bd_ok}


def dong_bang(p, chg, kl, s):
    """1 dòng trong bảng tín hiệu của trang web."""
    row = dict(p=round(p, 2), c=round(chg, 2), v=round(kl / 1000, 1),
               eq=None if s.get("eq") is None else round(s["eq"], 2), rb=s["rb"],
               t=s.get("t"), d=s.get("d", ""),
               bn=None if s.get("bn") is None else round(s["bn"], 2))
    for k in ("t1", "t2", "sl", "ws"):
        if s.get(k) is not None:
            row[k] = round(s[k], 2)
    if s.get("ly"):
        row["ly"] = s["ly"]
    return row


def trang_thai_bd(d, bd, cho_phep=True):
    """Trạng thái ROBOT của tab Bắt Đáy (có thêm Target động, mức cắt lỗ, Chờ bán)."""
    h, l, t, n = d["h"], d["l"], d["t"], len(d["c"])
    kq = None
    if bd["giu"]:
        i = bd["i_vao"]
        rb = "MUA" if i == n - 1 else "Giữ 1/2" if bd["tp1"] else "NẮM GIỮ"
        kq = dict(rb=rb, eq=bd["vao"], t=so_phien(t, i), d=fmt_ngay(t[i]),
                  t1=bd["t1"], t2=bd["t2"], sl=bd["sl"])
    elif bd["s"] and bd["s"][-1] == n - 1:
        kq = dict(rb="BÁN", eq=None, t=None, d=fmt_ngay(t[-1]), ly=bd["ly"][n - 1])
    elif bd["cho_mua"] and cho_phep:
        kq = dict(rb="CHỜ MUA", bn=h[-1])
    if bd["cho_ban"]:
        kq = kq or dict(rb="CHỜ BÁN")
        kq["ws"] = l[-1]
    return kq


def trang_thai_st(d, stt, cho_phep=True):
    """Trạng thái ROBOT của tab SuperTrend."""
    c, t, n = d["c"], d["t"], len(d["c"])
    if stt["giu"]:
        i = stt["i_vao"]
        rb = "MUA" if i == n - 1 else "Giữ 1/3" if stt["tp2"] else "Giữ 2/3" if stt["tp1"] else "NẮM GIỮ"
        return dict(rb=rb, eq=stt["vao"], t=so_phien(t, i), d=fmt_ngay(t[i]),
                    t1=stt["t1"], t2=stt["t2"], sl=stt["sl"])
    if stt["s"] and stt["s"][-1] == n - 1:
        return dict(rb="BÁN", eq=None, t=None, d=fmt_ngay(t[-1]), ly=stt["ly"][n - 1])
    # Không giữ hàng: xem có gần điểm kích hoạt mua không
    trig = stt["st"][-1] if stt["up"][-1] == 0 else None
    if cho_phep and trig and c[-1] < trig <= c[-1] * (1 + CHO_MUA_CACH):
        return dict(rb="CHỜ MUA", bn=trig)
    return None


def tinh_chien_luoc(d, mo=None, atr_ng=None):
    """Trả về chỉ báo + danh sách chỉ số nến MUA (b) / BÁN (s) cho từng chiến lược.
    mo = {"supertrend": [True/False...], "bat_day": [...]}: nến nào được phép MUA (None = không lọc).
    atr_ng = ATR NGÀY cho từng nến (để tính Target). Không truyền -> tự tính (dùng cho nến ngày)."""
    mo = mo or {}
    if atr_ng is None:
        atr_ng = atr_ngay(d)
    stt = chay_supertrend(d, mo.get("supertrend"), atr_ng)
    bd = bat_day(d, mo.get("bat_day"), atr_ng)
    g = {"supertrend": {"b": stt["b"], "s": stt["s"]}, "bat_day": {"b": bd["b"], "s": bd["s"]}}
    return dict(st=stt["st"], u=stt["up"], g=g, bd=bd, stt=stt, mo=mo)


def trang_thai(d, ind, key):
    """Trạng thái ROBOT hiện tại của 1 mã theo 1 chiến lược."""
    m = ind["mo"].get(key)
    cho_phep = m is None or (bool(m) and m[-1])
    if key == "bat_day":
        return trang_thai_bd(d, ind["bd"], cho_phep)
    return trang_thai_st(d, ind["stt"], cho_phep)


# ---------------- Cơ hội / Rủi ro (độ rộng thị trường) ----------------
def co_hoi_rui_ro(ds_ma, cs, lui=0):
    """Chỉ số Cơ hội (0-100) tính trên TẤT CẢ các mã, = trung bình 3 phần:
      1) % số mã có giá đóng cửa trên MA20             (xu hướng ngắn hạn)
      2) % số mã có SuperTrend (10,3) ngày đang tăng   (xu hướng trung hạn)
      3) CHỈ SỐ ĐỀU trên EMA 50 = 100, dưới = 0       (thị trường chung, cũng là bộ lọc MUA của bot)
    ds_ma = [(d, ind)] ; lui = 0: phiên hiện tại, 1: phiên trước đó. Rủi ro = 100 - Cơ hội."""
    k = -1 - lui
    tren_ma20 = co_ma20 = tang_st = co_st = 0
    for d, ind in ds_ma:
        c = d["c"]
        if len(c) < 21 + lui:
            continue
        m20 = sum(c[k - 19:k] + [c[k]]) / 20 if lui else sum(c[-20:]) / 20
        co_ma20 += 1; tren_ma20 += c[k] > m20
        u = ind["u"][k]
        if u is not None:
            co_st += 1; tang_st += u == 1
    phan = {}
    if co_ma20:
        phan["ma20"] = round(100 * tren_ma20 / co_ma20, 1)
    if co_st:
        phan["st"] = round(100 * tang_st / co_st, 1)
    n = LOC["ema_chi_so"] or 50
    if isinstance(cs, dict) and len(cs.get("c", [])) > n + lui:
        e = ema(cs["c"], n)
        if e[k] is not None:
            phan["cs"] = 100 if cs["c"][k] > e[k] else 0
            phan["cs_gia"], phan["cs_ema"], phan["cs_n"] = round(cs["c"][k], 2), round(e[k], 2), n
    ba = [phan[x] for x in ("ma20", "st", "cs") if x in phan]
    phan["diem"] = round(sum(ba) / len(ba)) if ba else None
    phan["so_ma"] = co_ma20
    return phan


# ---------------- Bảng theo ngành ----------------
def trang_thai_nganh(d, ind, key):
    """Xanh (đang giữ từ lúc MUA) / hồng (đứng ngoài từ lúc BÁN), lãi-lỗ, T+, điểm SL hoặc vào lại."""
    c, n = d["c"], len(d["c"])
    ev = sorted([(i, 1) for i in ind["g"][key]["b"]] + [(i, -1) for i in ind["g"][key]["s"]])
    if not ev:
        return None
    i, s = ev[-1]
    if key == "supertrend":
        muc = ind["stt"]["sl"] if s > 0 else ind["st"][-1]
    else:   # bat_day
        bd = ind["bd"]
        muc = bd["sl"] if s > 0 else (d["h"][-1] if bd["cho_mua"] else None)
    return dict(s=s, pl=round((c[-1] / c[i] - 1) * 100, 2) if c[i] else 0.0, t=so_phien(d["t"], i),
                d=fmt_ngay(d["t"][i]), muc=None if muc is None else round(muc, 2), hn=1 if i == n - 1 else 0)


# ---------------- TÀI KHOẢN ẢO (giao dịch giấy theo tín hiệu) ----------------
def tk_moi(ngay):
    return dict(von=TAI_KHOAN["von"], tien=float(TAI_KHOAN["von"]), ma={}, nhat_ky=[], lich_su=[], bat_dau=ngay)


def tk_gia(tk, m, gia):
    p = tk["ma"][m]
    return gia.get(m, p.get("gia_ht", p["gia"]))


def tk_nav(tk, gia):
    """Tổng tài sản = tiền mặt + giá trị cổ phiếu (giá theo nghìn đồng -> x1000)."""
    return tk["tien"] + sum(p["kl"] * tk_gia(tk, m, gia) * 1000 for m, p in tk["ma"].items())


def tk_ban(tk, m, ty_le, gia, ngay, ly):
    """Bán ty_le (1 = bán hết, 1/3, 1/2...) số cổ phiếu MUA BAN ĐẦU của mã m, tại giá đóng cửa."""
    p = tk["ma"][m]
    kl = p["kl"] if ty_le >= 1 else max(100, int(p["kl_dau"] * ty_le / 100) * 100)
    kl = min(kl, p["kl"])
    tien = kl * gia * 1000
    phi = tien * TAI_KHOAN["phi_ban"] / 100
    tk["tien"] += tien - phi
    lai = ((tien - phi) / (kl * p["gia_von"] * 1000) - 1) * 100
    tk["nhat_ky"].append(dict(ngay=ngay, ma=m, loai="BÁN", kl=kl, gia=round(gia, 2), tien=round(tien - phi),
                              lai=round(lai, 2), lai_d=round(tien - phi - kl * p["gia_von"] * 1000), ly=ly))
    p["kl"] -= kl
    if p["kl"] <= 0:
        del tk["ma"][m]


def tk_xu_ly_phien(tk, key, ind_ngay, hom_nay):
    """Chạy 1 lần mỗi phiên, SAU giờ đóng cửa: bán theo tín hiệu, rồi mua mã mới có tín hiệu, rồi ghi sổ."""
    gia = {m: d["c"][-1] for m, (d, ind) in ind_ngay.items() if d["t"][-1] == hom_nay}
    phi_mua = TAI_KHOAN["phi_mua"] / 100
    # 1) BÁN: chiến lược không còn giữ mã đó / bán bớt khi chạm Target (chỉ bán được từ T+2)
    for m in list(tk["ma"]):
        p = tk["ma"][m]
        if m not in gia:
            continue
        d, ind = ind_ngay[m]
        t, n = d["t"], len(d["t"])
        cl = ind["stt"] if key == "supertrend" else ind["bd"]
        i0 = t.index(p["ngay"]) if p["ngay"] in t else None
        tplus = so_phien(t, i0) if i0 is not None else 99
        con_giu = cl["giu"] and i0 is not None and cl["i_vao"] == i0
        ly = p.get("cho_ban")
        if not con_giu and not ly:
            sau = [i for i in cl["s"] if i0 is None or i > i0]
            ly = cl["ly"].get(sau[0], "Tín hiệu Hồng") if sau else "Tín hiệu thay đổi"
        if ly:
            if tplus < 2:            # chưa đủ T+2 -> chờ, bán ở phiên được phép đầu tiên
                p["cho_ban"] = ly
                continue
            tk_ban(tk, m, 1, gia[m], hom_nay, ly)
            continue
        if tplus < 2:
            continue
        if key == "supertrend":
            if cl["tp1"] and not p.get("tp1"):
                p["tp1"] = True; tk_ban(tk, m, 1 / 3, gia[m], hom_nay, "Chạm Target 1 - chốt 1/3")
            if m in tk["ma"] and cl["tp2"] and not p.get("tp2"):
                p["tp2"] = True; tk_ban(tk, m, 1 / 3, gia[m], hom_nay, "Chạm Target 2 - chốt thêm 1/3")
        elif cl["tp1"] and not p.get("tp1"):
            p["tp1"] = True; tk_ban(tk, m, 1 / 2, gia[m], hom_nay, "Chạm Target 1 - chốt 1/2")
    # 2) MUA: mã có tín hiệu XANH đúng phiên hôm nay; nhiều tín hiệu thì ưu tiên mã thanh khoản cao
    nav = tk_nav(tk, gia)
    ung = []
    for m, (d, ind) in ind_ngay.items():
        if m in tk["ma"] or m not in gia:
            continue
        cl = ind["stt"] if key == "supertrend" else ind["bd"]
        if cl["giu"] and cl["i_vao"] == len(d["c"]) - 1:
            gt = sum(v * c for v, c in zip(d["v"][-21:-1], d["c"][-21:-1]))
            ung.append((gt, m))
    for _, m in sorted(ung, reverse=True):
        if len(tk["ma"]) >= TAI_KHOAN["so_ma"]:
            break
        g = gia[m]
        muc = min(nav / TAI_KHOAN["so_ma"], tk["tien"] / (1 + phi_mua))
        kl = int(muc / (g * 1000) / 100) * 100          # lô chẵn 100 cổ phiếu
        if kl < 100:
            continue
        tien = kl * g * 1000
        tk["tien"] -= tien * (1 + phi_mua)
        tk["ma"][m] = dict(kl=kl, kl_dau=kl, gia=g, gia_von=g * (1 + phi_mua), ngay=hom_nay)
        tk["nhat_ky"].append(dict(ngay=hom_nay, ma=m, loai="MUA", kl=kl, gia=round(g, 2),
                                  tien=round(tien * (1 + phi_mua)), ly="Tín hiệu Xanh"))
    # 3) Ghi sổ lãi/lỗ của phiên
    for m in tk["ma"]:
        tk["ma"][m]["gia_ht"] = tk_gia(tk, m, gia)
    nav = tk_nav(tk, gia)
    truoc = tk["lich_su"][-1]["nav"] if tk["lich_su"] else tk["von"]
    tk["lich_su"].append(dict(ngay=hom_nay, nav=round(nav), lai=round(nav - truoc),
                              lai_pt=round((nav / truoc - 1) * 100, 2), luy_ke=round((nav / tk["von"] - 1) * 100, 2),
                              so_ma=len(tk["ma"]), tien=round(tk["tien"])))
    tk["nhat_ky"] = tk["nhat_ky"][-1000:]


def ghi_tai_khoan(tk_all, ind_ngay, now, da_chot):
    """Ghi file tài khoản ảo cho web. Tên file lấy từ mật khẩu (GitHub secret TK_MAT_KHAU):
    không biết mật khẩu thì không biết tên file -> không xem được."""
    mk = os.environ.get("TK_MAT_KHAU", "").strip()
    if not mk:
        print("(Chưa cài mật khẩu TK_MAT_KHAU nên không xuất trang Tài khoản ảo)")
        return
    gia = {m: d["c"][-1] for m, (d, ind) in ind_ngay.items()}
    out = dict(asof=now.strftime("%H:%M %d/%m/%Y"), so_ma_toi_da=TAI_KHOAN["so_ma"], tk={})
    for key, ten in CHIEN_LUOC.items():
        tk = tk_all.get(key)
        if not tk:
            out["tk"][key] = dict(ten=ten, chua=True, von=TAI_KHOAN["von"])
            continue
        nav = tk_nav(tk, gia)
        truoc = tk["lich_su"][-2 if da_chot and len(tk["lich_su"]) > 1 else -1]["nav"] if tk["lich_su"] else tk["von"]
        if da_chot and len(tk["lich_su"]) == 1:
            truoc = tk["von"]
        ma = []
        for m, p in tk["ma"].items():
            g = tk_gia(tk, m, gia)
            d = ind_ngay.get(m, (None,))[0]
            ma.append(dict(m=m, kl=p["kl"], gv=round(p["gia_von"], 3), g=round(g, 2), gt=round(p["kl"] * g * 1000),
                           lai=round((g / p["gia_von"] - 1) * 100, 2), lai_d=round(p["kl"] * (g - p["gia_von"]) * 1000),
                           ngay=fmt_ngay(p["ngay"]), t=so_phien(d["t"], d["t"].index(p["ngay"])) if d and p["ngay"] in d["t"] else None,
                           cb=p.get("cho_ban")))
        ma.sort(key=lambda x: -x["gt"])
        out["tk"][key] = dict(ten=ten, von=tk["von"], tien=round(tk["tien"]), nav=round(nav), bat_dau=fmt_ngay(tk["bat_dau"]),
                              hn=round(nav - truoc), hn_pt=round((nav / truoc - 1) * 100, 2),
                              luy_ke=round((nav / tk["von"] - 1) * 100, 2), ma=ma,
                              lich_su=tk["lich_su"], nhat_ky=tk["nhat_ky"][-300:])
    out["da_chot"] = da_chot
    ten_file = "tk_" + hashlib.sha256(mk.encode("utf-8")).hexdigest()[:16] + ".json"
    json.dump(out, open(os.path.join(SITE, ten_file), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


def diem_xep_hang(vals):
    """Đổi danh sách số thành điểm 0-100 theo thứ hạng (cao nhất = 100, thấp nhất = 0)."""
    n = len(vals)
    if n == 1:
        return [50]
    out = [0] * n
    for r, i in enumerate(sorted(range(n), key=lambda i: vals[i])):
        out[i] = round(100 * r / (n - 1))
    return out


def trung_vi(a):
    """Trung vị: không bị 1 mã biến động bất thường (vd ngày GDKHQ) kéo lệch cả ngành."""
    a = sorted(a)
    k = len(a) // 2
    return a[k] if len(a) % 2 else (a[k - 1] + a[k]) / 2


def xep_nganh(rows):
    """Gom mã theo ngành, chấm điểm sức mạnh 20 phiên: mã so với ngành, ngành so với ngành."""
    nhom = {}
    for m, r in rows.items():
        nhom.setdefault(MA_NGANH.get(m, "Khác"), []).append(dict(r, m=m))
    kq = []
    for ten, ds in nhom.items():
        for x, dd in zip(ds, diem_xep_hang([x["r"] for x in ds])):
            x["sm"] = dd
        ds.sort(key=lambda x: (-x["sm"], -x["r"]))
        kq.append(dict(ten=ten, r=round(trung_vi([x["r"] for x in ds]), 2),
                       c=round(trung_vi([x["c"] for x in ds]), 2),
                       xanh=sum(1 for x in ds if x["s"] > 0), ma=ds))
    for x, dd in zip(kq, diem_xep_hang([x["r"] for x in kq])):
        x["sm"] = dd
    kq.sort(key=lambda x: -x["r"])
    return kq


def fmt_ngay(s):
    return f"{s[8:10]}/{s[5:7]}/{s[0:4]}" + (f" {s[11:16]}" if len(s) > 10 else "")


def so_phien(t, i):
    """Số ngày giao dịch từ nến i đến nến cuối (T+). Khung ngày = số nến; khung giờ = số ngày khác nhau."""
    return len({x[:10] for x in t[i:]}) - 1


def r2(a):
    return [None if x is None else round(x, 2) for x in a]


# ---------------- Telegram ----------------
def gui_telegram(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("(Chưa cài TELEGRAM_TOKEN / TELEGRAM_CHAT_ID nên không gửi)\n" + text)
        return
    for i in range(0, len(text), 3800):      # Telegram giới hạn ~4096 ký tự / tin
        body = urllib.parse.urlencode({"chat_id": chat, "text": text[i:i + 3800], "parse_mode": "HTML",
                                       "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
        try:
            urllib.request.urlopen(req, timeout=20).read()
        except Exception as e:
            print("Lỗi gửi Telegram:", e)


def so(x, d=2):
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------- Chương trình chính ----------------
def main():
    test = "--test" in sys.argv
    ds = list(dict.fromkeys(DANH_SACH_MA.split()))
    if test:
        ds = ["FPT", "HPG", "MSB"]
    now = datetime.now(VN)
    hom_nay = now.strftime("%Y-%m-%d")

    cache = doc_cache(hom_nay)   # nến ngày đã lưu trong hôm nay (nếu có)
    moi = {}
    with ThreadPoolExecutor(8) as ex:
        kq_idx = dict(zip(CHI_SO, ex.map(lambda m: _safe(lay_gia_nhanh, m, True, cache, moi), CHI_SO)))  # chỉ số lấy trước
        kq = dict(zip(ds, ex.map(lambda m: _safe(lay_gia_nhanh, m, False, cache, moi), ds)))
    if not test:
        ghi_cache(hom_nay, cache, moi)

    co = {m: d for m, d in kq.items() if isinstance(d, dict) and len(d["c"]) > 30}
    thieu = [m for m in ds if m not in co]
    print(f"Lấy được {len(co)}/{len(ds)} mã. Nguồn: {sorted({d['nguon'] for d in co.values()})}")
    if thieu:
        print("Thiếu:", ", ".join(thieu[:40]), "| lỗi mẫu:", kq.get(thieu[0]))
    if not co:
        print("KHÔNG lấy được mã nào – có thể nguồn giá đang lỗi hoặc chặn. Dừng.")
        sys.exit(1)

    # Trạng thái đã gửi (để không gửi trùng)
    try:
        state = json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        state = {}
    da_gui = set(state.get("da_gui", []))

    tabs = {}
    for k in CHIEN_LUOC:
        tabs[CHIEN_LUOC[k]] = {}
        tabs[TEN_1H_CL[k]] = {}
    nganh_raw = {t: {} for t in tabs}
    tin_moi = []
    os.makedirs(os.path.join(SITE, "h"), exist_ok=True)
    os.makedirs(os.path.join(SITE, "h1"), exist_ok=True)
    cs = chi_so_deu(list(co.values()))          # chỉ số đều của tất cả các mã
    vni = thi_truong_ok(cs)                      # bộ lọc thị trường chung
    ds_ind = []                               # (nến ngày, chỉ báo) của từng mã -> tính Cơ hội / Rủi ro
    ind_ngay = {}                             # mã -> (nến ngày, chỉ báo) -> tài khoản ảo
    if LOC["ema_chi_so"] and vni:
        print("Bộ lọc chỉ số đều hôm nay:", "cho phép MUA" if list(vni.values())[-1] else "KHÔNG mở lệnh MUA mới")
    for m, d in co.items():
        ok_ngay = loc_mua_ngay(d, vni)
        ind = tinh_chien_luoc(d, {"supertrend": ok_ngay, "bat_day": ok_ngay})
        ds_ind.append((d, ind))
        ind_ngay[m] = (d, ind)
        c = d["c"]
        p, chg = c[-1], (c[-1] / c[-2] - 1) * 100 if c[-2] else 0
        r20 = (c[-1] / c[-21] - 1) * 100 if len(c) > 21 and c[-21] else 0.0   # sức mạnh 20 phiên
        for key, ten in CHIEN_LUOC.items():
            s2 = trang_thai_nganh(d, ind, key)
            if s2:
                s2.update(p=round(p, 2), c=round(chg, 2), r=round(r20, 2))
                nganh_raw[ten][m] = s2
        for key, ten in CHIEN_LUOC.items():
            s = trang_thai(d, ind, key)
            if s:
                tabs[ten][m] = dong_bang(p, chg, d["v"][-1], s)
            # Tín hiệu mới của HÔM NAY
            if d["t"][-1] == hom_nay:
                for loai in ("b", "s"):
                    if len(c) - 1 in ind["g"][key][loai]:
                        khoa = f"{hom_nay}|{m}|{key}|{loai}"
                        if khoa not in da_gui:
                            da_gui.add(khoa)
                            tin_moi.append((loai, m, ten, p, chg, key, ind))
        # file đồ thị cho từng mã
        k0 = max(0, len(c) - SO_NEN_LUU_DO_THI)
        bu, bl = bollinger(c)
        cut = lambda a: r2(a[k0:])
        bd = ind["bd"]
        hist = dict(t=d["t"][k0:], o=cut(d["o"]), h=cut(d["h"]), l=cut(d["l"]), c=cut(c),
                    v=[int(x) for x in d["v"][k0:]], st=cut(ind["st"]), u=ind["u"][k0:],
                    m20=cut(sma(c, 20)), bu=cut(bu), bl=cut(bl),
                    kg=cut(bd["giua"]), kt=cut(bd["tren"]), kd=cut(bd["duoi"]),
                    ct=[i - k0 for i in bd["cam_tren"] if i >= k0], cd=[i - k0 for i in bd["cam_duoi"] if i >= k0],
                    g={k: {"b": [i - k0 for i in v["b"] if i >= k0], "s": [i - k0 for i in v["s"] if i >= k0]}
                       for k, v in ind["g"].items()})
        json.dump(hist, open(os.path.join(SITE, "h", m + ".json"), "w"), separators=(",", ":"))

        # ----- Khung 1 giờ (SuperTrend + Bắt Đáy) -----
        dg = d.get("gio")
        if dg and len(dg["c"]) > 60:
            indg = tinh_chien_luoc(dg, loc_mua_gio(dg, d, ok_ngay, ind), atr_ngay_cho_gio(dg, d, atr_ngay(d)))
            bdg = indg["bd"]
            n1 = len(dg["c"]) - 1
            for key in CHIEN_LUOC:
                ten1 = TEN_1H_CL[key]
                s = trang_thai(dg, indg, key)
                if s:
                    tabs[ten1][m] = dong_bang(p, chg, d["v"][-1], s)
                s2 = trang_thai_nganh(dg, indg, key)
                if s2:
                    s2.update(p=round(p, 2), c=round(chg, 2), r=round(r20, 2))
                    nganh_raw[ten1][m] = s2
                if dg["t"][-1][:10] == hom_nay:
                    for loai in ("b", "s"):
                        if n1 in indg["g"][key][loai]:
                            khoa = f"{dg['t'][-1]}|{m}|{key}_1h|{loai}"
                            if khoa not in da_gui:
                                da_gui.add(khoa)
                                tin_moi.append((loai, m, ten1, p, chg, key, indg))
            k1 = max(0, len(dg["c"]) - SO_NEN_LUU_DO_THI)
            cg = lambda a: r2(a[k1:])
            gu, gl = bollinger(dg["c"])
            hist1 = dict(t=dg["t"][k1:], o=cg(dg["o"]), h=cg(dg["h"]), l=cg(dg["l"]), c=cg(dg["c"]),
                         v=[int(x) for x in dg["v"][k1:]], st=cg(indg["st"]), u=indg["u"][k1:],
                         m20=cg(sma(dg["c"], 20)),
                         bu=cg(gu), bl=cg(gl), kg=cg(bdg["giua"]), kt=cg(bdg["tren"]), kd=cg(bdg["duoi"]),
                         ct=[i - k1 for i in bdg["cam_tren"] if i >= k1], cd=[i - k1 for i in bdg["cam_duoi"] if i >= k1],
                         g={k: {"b": [i - k1 for i in v["b"] if i >= k1], "s": [i - k1 for i in v["s"] if i >= k1]}
                            for k, v in indg["g"].items()})
            json.dump(hist1, open(os.path.join(SITE, "h1", m + ".json"), "w"), separators=(",", ":"))

    idx = {}
    for k, d in kq_idx.items():
        if isinstance(d, dict) and len(d["c"]) > 1:
            idx[k] = [round(d["c"][-1], 2), round((d["c"][-1] / d["c"][-2] - 1) * 100, 2)]

    dt = {}
    for m, d in co.items():
        try:
            x = dong_tien(d, now, hom_nay)
            if x:
                dt[m] = x
        except Exception as e:
            print(f"{m}: lỗi tính dòng tiền ({e})")

    if len(cs["c"]) > 1:   # hiện chỉ số đều trên đầu trang, cạnh VNINDEX / VN30
        idx["CHỈ SỐ ĐỀU"] = [round(cs["c"][-1], 2), round((cs["c"][-1] / cs["c"][-2] - 1) * 100, 2)]
    ch = co_hoi_rui_ro(ds_ind, cs)
    ch["truoc"] = co_hoi_rui_ro(ds_ind, cs, lui=1).get("diem")   # phiên trước để so sánh
    print("Cơ hội / Rủi ro:", ch)
    data = dict(asof=now.strftime("%H:%M %d/%m/%Y"), idx=idx, tabs=tabs, dt=dt, ch=ch,
                nganh={t: xep_nganh(r) for t, r in nganh_raw.items()}, symbols=ds, missing=thieu,
                phien=cs["t"][-150:],   # danh sách ngày giao dịch gần nhất (trang Giao dịch thử dùng để tính T+2)
                telegram=os.environ.get("TELEGRAM_LINK", ""))
    # ----- Tài khoản ảo: chốt giao dịch 1 lần/phiên sau giờ đóng cửa -----
    tk_all = state.setdefault("tai_khoan", {})
    co_hom_nay = any(d["t"][-1] == hom_nay for d, _ in ind_ngay.values())
    if co_hom_nay and now.hour >= TAI_KHOAN["gio_chot"] and state.get("tk_ngay") != hom_nay:
        for key in CHIEN_LUOC:
            tk = tk_all.setdefault(key, tk_moi(hom_nay))
            tk_xu_ly_phien(tk, key, ind_ngay, hom_nay)
        state["tk_ngay"] = hom_nay
        print("Tài khoản ảo:", {k: (round(v["lich_su"][-1]["nav"]), len(v["ma"])) for k, v in tk_all.items()})
    ghi_tai_khoan(tk_all, ind_ngay, now, state.get("tk_ngay") == hom_nay)

    json.dump(data, open(os.path.join(SITE, "data.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    trang = os.path.join(ROOT, "index.html")
    if not os.path.exists(trang):
        trang = os.path.join(ROOT, "web", "index.html")
    shutil.copy(trang, os.path.join(SITE, "index.html"))

    # ----- Gửi Telegram -----
    if tin_moi and not test:
        dong = [f"<b>📡 TÍN HIỆU MỚI</b> — {now.strftime('%H:%M %d/%m')}"]
        for loai, m, ten, p, chg, key, ind in sorted(tin_moi, key=lambda x: (x[0], x[1])):
            if loai == "b":
                if key == "bat_day":
                    bd = ind["bd"]
                    t1, t2, sl = bd["t1"], bd["t2"], bd["sl"]
                else:
                    stt = ind["stt"]
                    t1, t2, sl = stt["t1"], stt["t2"], stt["sl"]
                dong.append(f"\n🟢 <b>XANH {m}</b> · {ten}\nGiá {so(p)} ({'+' if chg >= 0 else ''}{so(chg)}%)"
                            f" · T1 {so(t1)} · T2 {so(t2)} · Cắt lỗ {so(sl)}")
            else:
                nguon = ind["bd"] if key == "bat_day" else ind["stt"]
                ly = nguon["ly"].get(len(ind["st"]) - 1)
                dong.append(f"\n🔴 <b>HỒNG {m}</b> · {ten}\nGiá {so(p)} ({'+' if chg >= 0 else ''}{so(chg)}%)"
                            + (f"\nLý do: {ly}" if ly else ""))
        dong.append("\n<i>Tín hiệu trong phiên là tạm thời, chỉ xác nhận khi đóng cửa. Không phải khuyến nghị đầu tư.</i>")
        gui_telegram("\n".join(dong))
    elif test:
        print("Chế độ test – tín hiệu mới hôm nay:", [(x[0], x[1], x[2]) for x in tin_moi])

    # Tổng kết cuối phiên (1 lần/ngày)
    if not test and now.hour >= GIO_TONG_KET and state.get("tong_ket") != hom_nay and any(
            d["t"][-1] == hom_nay for d in co.values()):
        dong = [f"<b>📊 TỔNG KẾT PHIÊN {now.strftime('%d/%m/%Y')}</b>"]
        if "VNINDEX" in idx:
            v, c = idx["VNINDEX"]
            dong.append(f"VNINDEX {so(v)} ({'+' if c >= 0 else ''}{so(c)}%)")
        for ten, rows in tabs.items():
            mua = [m for m, r in rows.items() if r["rb"] == "MUA"]
            ban = [m for m, r in rows.items() if r["rb"] == "BÁN"]
            dong.append(f"\n<b>{ten}</b>\n🟢 XANH: {', '.join(mua) or '—'}\n🔴 HỒNG: {', '.join(ban) or '—'}")
        gui_telegram("\n".join(dong))
        state["tong_ket"] = hom_nay

    # Giữ khóa đã gửi của 10 ngày gần nhất
    moc = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    state["da_gui"] = sorted(k for k in da_gui if k[:10] >= moc)
    if not test:
        json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"Xong. Tín hiệu mới: {len(tin_moi)}")


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return f"lỗi: {e}"


if __name__ == "__main__":
    main()
