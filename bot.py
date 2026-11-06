# -*- coding: utf-8 -*-
"""
BOT TÍN HIỆU CỔ PHIẾU -> TELEGRAM + TRANG WEB
Chạy tự động trên GitHub Actions mỗi 5 phút trong giờ giao dịch.

Việc bot làm mỗi lần chạy:
  1. Lấy giá nến ngày của các mã trong DANH_SACH_MA (gồm cả phiên hôm nay đang chạy)
  2. Tính 3 chiến lược: SuperTrend (10,3), EMA 9/21, Lướt T+ (vượt kháng cự)
  3. Có tín hiệu MUA/BÁN mới trong hôm nay -> gửi Telegram (mỗi tín hiệu chỉ gửi 1 lần)
  4. Ghi file dữ liệu cho trang web vào thư mục site/

Chạy thử trên máy:   python bot.py --test     (chỉ lấy 3 mã, không gửi Telegram)
"""
import json, os, sys, time, shutil, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# ============ PHẦN CẤU HÌNH (Sếp có thể sửa) ============
DANH_SACH_MA = """AAA AAT ABB ACB ACL ADS AGR ANV APH ASM BAF BCC BCM BFC BID BKC BMC BMP BMI BSI BSR BVB BVS BVH CBO CEO CII CMG CMX CNG CSM CST CTD CTR CTG CTS CSV DCL DCM DDV DGC DGW DHC DIG DPG DPM DPR DRC DRI DXG DXS DXP EIB EVF EVG FCN FMC FOX FPT FRT FTS G36 GAS GEE GEG GEL GEX GIL GMD GSP GVR HAG HAH HBC HCD HDB HDC HDG HEX HHV HHS HII HNG HPG HSG HT1 HUT IDC IDI KBC KCB KDH KHP KHG KLB KOS KSV L14 LAS LCG LDG LPS LPB MBB MCH MIG MML MPC MSB MSH MSN MSR MVN MWG NAB NBC NHH NKG NLG NTL NTP NVB NVL OC8 OCB OIL ORS PAC PAN PC1 PDR PET PGN PHP PHR PLC PLP PLX PNJ POW PPC PVC PVB PVD PVP PVS PVT QTP REE SAB SBS SGP SHB SHS SIP SJD SMC SSB SSI STB SZC TCB TCH TCM TCX THT TLH TNG TPB TSC TV2 TVD TVN TVS VCB VCK VCI VDE VDS VFS VGC VGI VGL VGS VGT VHC VHM VIB VIC VID VIP VIS VIX VJC VJS VLC VMD VND VNM VOS VPI VPB VPD VPG VPL VPO VPR VPX VRE VSC VSI VST VSU VTO VTP VTV VVS"""
CHI_SO = ["VNINDEX", "VN30"]

CHIEN_LUOC = {                      # khóa nội bộ -> tên hiện trên web/Telegram
    "supertrend": "SuperTrend (10, 3)",
    "ema": "EMA 9/21",
    "vuot_khang_cu": "Lướt T+ (vượt kháng cự)",
}
TARGET = {"supertrend": (1.085, 1.135), "ema": (1.085, 1.135), "vuot_khang_cu": (1.04, 1.07)}
CHO_MUA_CACH = 0.03                 # giá cách điểm kích hoạt <= 3% thì đưa vào "Chờ mua"
SO_NEN_LUU_DO_THI = 150             # số phiên lưu cho đồ thị trên web
GIO_TONG_KET = 15                   # sau 15h (giờ VN) gửi 1 tin tổng kết phiên

# Phân ngành (mỗi dòng: Tên ngành: các mã). Mã không có ở đây sẽ vào nhóm "Khác".
NGANH = """
Ngân hàng: ABB ACB BID BVB CTG EIB HDB KLB LPB MBB MSB NAB NVB OCB SHB SSB STB TCB TPB VCB VIB VPB
Chứng khoán: AGR BSI BVS CTS FTS LPS ORS SBS SHS SSI TCX TVS VCI VCK VDS VFS VIX VND VPX
BĐS dân cư: CEO DIG DXG DXS EVG HDC KDH KHG KOS L14 LDG NLG NTL NVL PDR TCH VHM VIC VPI VPL VRE
BĐS KCN: BCM GVR IDC KBC SIP SZC VGC
Xây dựng & Đầu tư công: CII CTD DPG FCN G36 HBC HHV HUT LCG VSI
Vật liệu XD & Nhựa: AAA APH BCC BMP HCD HII HT1 NHH NTP PGN PLP
Thép: HPG HSG NKG SMC TLH TVN VGL VGS VIS
Dầu khí: BSR CNG GAS GSP OIL PLC PLX PVB PVC PVD PVP PVS PVT
Điện & Năng lượng: GEE GEG GEL GEX HDG KHP PC1 POW PPC QTP REE SJD TV2 VPD VTV
Hóa chất & Phân bón: BFC CSV DCM DDV DGC DPM LAS
Cao su: CSM DPR DRC DRI PHR
Thủy sản: ACL ANV ASM CMX FMC IDI MPC VHC
Dệt may: AAT ADS GIL MSH TCM TNG VGT
Bán lẻ & Phân phối: DGW FRT MWG PET PNJ VPG
Thực phẩm & Nông nghiệp: BAF HAG HNG MCH MML MSN PAN SAB TSC VLC VNM
Cảng, Vận tải & Hàng không: DXP GMD HAH HHS MVN PHP SGP VIP VJC VOS VSC VST VTO VTP
Công nghệ & Viễn thông: CMG CTR FOX FPT VGI
Bảo hiểm & Tài chính: BMI BVH EVF MIG
Khoáng sản & Than: BKC BMC CST KCB KSV MSR NBC THT TVD
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


def them_nen_hom_nay(d, ma, loai):
    """DNSE chỉ tạo nến ngày sau khi hết phiên. Trong phiên, gộp nến 15 phút của hôm nay
    thành 1 nến ngày tạm thời rồi gắn vào cuối, để giá / T+ / tín hiệu cập nhật theo thời gian thực."""
    hom_nay = datetime.now(VN).strftime("%Y-%m-%d")
    if d["t"] and d["t"][-1] >= hom_nay:
        return
    now = int(time.time())
    url = (f"https://services.entrade.com.vn/chart-api/v2/ohlcs/{loai}?symbol={ma}"
           f"&resolution=15&from={now - 86400}&to={now + 900}")
    j = http_json(url)
    ds = [i for i, x in enumerate(j.get("t") or [])
          if datetime.fromtimestamp(x, VN).strftime("%Y-%m-%d") == hom_nay]
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
    for lan in range(3):
        try:
            them_nen_hom_nay(d, ma, loai)
            break
        except Exception as e:
            if lan == 2:
                print(f"{ma}: chưa lấy được nến trong phiên ({e})")
            time.sleep(2)
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


def tinh_chien_luoc(d):
    """Trả về chỉ báo + danh sách chỉ số nến MUA (b) / BÁN (s) cho từng chiến lược."""
    h, l, c = d["h"], d["l"], d["c"]
    n = len(c)
    st, up = supertrend(h, l, c)
    e9, e21 = ema(c, 9), ema(c, 21)
    rs = [None if i < 20 else max(h[i - 20:i]) for i in range(n)]
    ma10 = sma(c, 10)
    g = {k: {"b": [], "s": []} for k in CHIEN_LUOC}
    for i in range(1, n):
        if up[i] is not None and up[i - 1] is not None and up[i] != up[i - 1]:
            g["supertrend"]["b" if up[i] else "s"].append(i)
        if None not in (e9[i], e21[i], e9[i - 1], e21[i - 1]):
            if e9[i - 1] <= e21[i - 1] and e9[i] > e21[i]:
                g["ema"]["b"].append(i)
            elif e9[i - 1] >= e21[i - 1] and e9[i] < e21[i]:
                g["ema"]["s"].append(i)
    # Lướt T+: MUA khi đóng cửa vượt đỉnh 20 phiên trước; BÁN khi đóng cửa dưới MA10
    giu = False
    for i in range(21, n):
        if not giu and rs[i] is not None and c[i] > rs[i]:
            g["vuot_khang_cu"]["b"].append(i); giu = True
        elif giu and ma10[i] is not None and c[i] < ma10[i]:
            g["vuot_khang_cu"]["s"].append(i); giu = False
    return dict(st=st, u=up, e9=e9, e21=e21, rs=rs, ma10=ma10, g=g)


def trang_thai(d, ind, key):
    """Trạng thái ROBOT hiện tại của 1 mã theo 1 chiến lược."""
    c, h, t = d["c"], d["h"], d["t"]
    n = len(c)
    ev = sorted([(i, "b") for i in ind["g"][key]["b"]] + [(i, "s") for i in ind["g"][key]["s"]])
    if not ev:
        return None
    i, loai = ev[-1]
    if loai == "b":
        eq = c[i]
        t1, t2 = eq * TARGET[key][0], eq * TARGET[key][1]
        dinh = max(h[i + 1:]) if i < n - 1 else eq   # giá cao nhất từ sau ngày mua
        rb = "MUA" if i == n - 1 else ("Giữ 1/3" if dinh >= t2 else "Giữ 2/3" if dinh >= t1 else "NẮM GIỮ")
        return dict(rb=rb, eq=eq, t=n - 1 - i, d=fmt_ngay(t[i]))
    if i == n - 1:
        return dict(rb="BÁN", eq=None, t=None, d=fmt_ngay(t[i]))
    # Không giữ hàng: xem có gần điểm kích hoạt mua không
    trig = None
    if key == "supertrend" and ind["u"][-1] == 0:
        trig = ind["st"][-1]
    elif key == "vuot_khang_cu":
        trig = max(h[-20:])
    if trig and c[-1] < trig <= c[-1] * (1 + CHO_MUA_CACH):
        return dict(rb="CHỜ MUA", bn=trig)
    return None


# ---------------- Bảng theo ngành ----------------
def gia_cat_ema(e9, e21):
    """Giá đóng cửa hôm nay để EMA9 cắt EMA21 (điểm SL khi đang giữ / điểm vào lại khi đứng ngoài)."""
    if len(e9) < 2 or e9[-2] is None or e21[-2] is None:
        return None
    a9, a21 = 2 / 10, 2 / 22
    p = ((1 - a21) * e21[-2] - (1 - a9) * e9[-2]) / (a9 - a21)
    return p if p > 0 else None


def trang_thai_nganh(d, ind, key):
    """Xanh (đang giữ từ lúc MUA) / hồng (đứng ngoài từ lúc BÁN), lãi-lỗ, T+, điểm SL hoặc vào lại."""
    c, n = d["c"], len(d["c"])
    ev = sorted([(i, 1) for i in ind["g"][key]["b"]] + [(i, -1) for i in ind["g"][key]["s"]])
    if not ev:
        return None
    i, s = ev[-1]
    if key == "supertrend":
        muc = ind["st"][-1]
    elif key == "ema":
        muc = gia_cat_ema(ind["e9"], ind["e21"])
    else:
        muc = ind["ma10"][-1] if s > 0 else ind["rs"][-1]
    return dict(s=s, pl=round((c[-1] / c[i] - 1) * 100, 2) if c[i] else 0.0, t=n - 1 - i,
                d=fmt_ngay(d["t"][i]), muc=None if muc is None else round(muc, 2), hn=1 if i == n - 1 else 0)


def diem_xep_hang(vals):
    """Đổi danh sách số thành điểm 0-100 theo thứ hạng (cao nhất = 100, thấp nhất = 0)."""
    n = len(vals)
    if n == 1:
        return [50]
    out = [0] * n
    for r, i in enumerate(sorted(range(n), key=lambda i: vals[i])):
        out[i] = round(100 * r / (n - 1))
    return out


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
        kq.append(dict(ten=ten, r=round(sum(x["r"] for x in ds) / len(ds), 2),
                       c=round(sum(x["c"] for x in ds) / len(ds), 2),
                       xanh=sum(1 for x in ds if x["s"] > 0), ma=ds))
    for x, dd in zip(kq, diem_xep_hang([x["r"] for x in kq])):
        x["sm"] = dd
    kq.sort(key=lambda x: -x["r"])
    return kq


def fmt_ngay(s):
    return f"{s[8:10]}/{s[5:7]}/{s[0:4]}"


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

    tabs = {CHIEN_LUOC[k]: {} for k in CHIEN_LUOC}
    nganh_raw = {CHIEN_LUOC[k]: {} for k in CHIEN_LUOC}
    tin_moi = []
    os.makedirs(os.path.join(SITE, "h"), exist_ok=True)
    for m, d in co.items():
        ind = tinh_chien_luoc(d)
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
                tabs[ten][m] = dict(p=round(p, 2), c=round(chg, 2), v=round(d["v"][-1] / 1000, 1),
                                    eq=None if s.get("eq") is None else round(s["eq"], 2), rb=s["rb"],
                                    t=s.get("t"), d=s.get("d", ""),
                                    bn=None if s.get("bn") is None else round(s["bn"], 2))
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
        hist = dict(t=d["t"][k0:], o=cut(d["o"]), h=cut(d["h"]), l=cut(d["l"]), c=cut(c),
                    v=[int(x) for x in d["v"][k0:]], st=cut(ind["st"]), u=ind["u"][k0:],
                    e9=cut(ind["e9"]), e21=cut(ind["e21"]), rs=cut(ind["rs"]),
                    m20=cut(sma(c, 20)), m50=cut(sma(c, 50)), m200=cut(sma(c, 200)), bu=cut(bu), bl=cut(bl),
                    g={k: {"b": [i - k0 for i in v["b"] if i >= k0], "s": [i - k0 for i in v["s"] if i >= k0]}
                       for k, v in ind["g"].items()})
        json.dump(hist, open(os.path.join(SITE, "h", m + ".json"), "w"), separators=(",", ":"))

    idx = {}
    for k, d in kq_idx.items():
        if isinstance(d, dict) and len(d["c"]) > 1:
            idx[k] = [round(d["c"][-1], 2), round((d["c"][-1] / d["c"][-2] - 1) * 100, 2)]

    data = dict(asof=now.strftime("%H:%M %d/%m/%Y"), idx=idx, tabs=tabs, nganh={t: xep_nganh(r) for t, r in nganh_raw.items()}, symbols=ds, missing=thieu,
                telegram=os.environ.get("TELEGRAM_LINK", ""))
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
                t1, t2 = p * TARGET[key][0], p * TARGET[key][1]
                dong.append(f"\n🟢 <b>MUA {m}</b> · {ten}\nGiá {so(p)} ({'+' if chg >= 0 else ''}{so(chg)}%)"
                            f" · T1 {so(t1)} · T2 {so(t2)}")
            else:
                dong.append(f"\n🔴 <b>BÁN {m}</b> · {ten}\nGiá {so(p)} ({'+' if chg >= 0 else ''}{so(chg)}%)")
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
            dong.append(f"\n<b>{ten}</b>\n🟢 MUA: {', '.join(mua) or '—'}\n🔴 BÁN: {', '.join(ban) or '—'}")
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
