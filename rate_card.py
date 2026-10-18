"""Daily "আজকের রেট" card: Mustafa BDT remittance rate + Mustafa gold rate.
Same look as the news cards (dark card, QR code, BD + SG flags).
Rates are read from https://www.mustafa.com.sg/ every run."""
import os, re, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

import qrcode
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

import common
from common import PAGE_NAME, _bn, _lat, _wlen, _draw_line, _flag, post_card, tg_preview, tg_say

URL = "https://www.mustafa.com.sg/"
VORI = 11.664  # grams in 1 bhori/vori
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
GREEN, WHITE, GREY, DIM, PANEL = "#39e75f", "white", "#9ca3af", "#6b7280", "#161616"
BN_MONTHS = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন",
             "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"]


def bn(x):
    """Latin digits -> Bangla digits"""
    return str(x).translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))


def money(x, dec=2):
    """12345.6 -> '12,345.60' in Bangla digits, Indian grouping (১,৭৩,৬৩৫)"""
    s = f"{x:.{dec}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return bn(whole + ("." + frac if dec else ""))


# ---------- scrape ----------
MIRROR = "https://www.livepriceofgold.com/mustafa-gold-price.html"  # copy of Mustafa's rates


def _num(m):
    return float(m.group(1).replace(",", ""))


def _page_text(url, tries=3, timeout=20):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=timeout)
            r.raise_for_status()
            return re.sub(r"\s+", " ", BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
        except Exception as e:
            last = e
            print(f"fetch {url} try {i + 1} failed: {e}")
            time.sleep(3)
    raise RuntimeError(f"cannot open {url}: {last}")


def _find(text, patterns, name):
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return _num(m)
    raise RuntimeError(f"Could not find {name} (page layout changed?)")


def _parse(text):
    bdt = _find(text, [r"Bangladesh Taka\s*(?:Todays?|Today's)?\s*Rate\s*([\d.,]+)",
                       r"Draft Rate:?\s*Bangladesh Taka\s*([\d.,]+)"], "BDT rate")
    k22 = _find(text, [r"22K\s*-?\s*916\s*Jewellery\s*([\d.,]+)",
                       r"22K Gold \(916\) Jewellery\s*([\d.,]+)"], "22K gold rate")
    bar = _find(text, [r"24K\s*-?\s*999\s*Gold\s*Bar\s*100\s*g\s*([\d.,]+)",
                       r"24K Gold Bar: 100 Gram \(999\)\s*([\d.,]+)"], "24K gold bar rate")
    k24 = bar / 100  # price per gram
    # sanity checks - never post nonsense
    if not 50 <= bdt <= 200:
        raise RuntimeError(f"BDT rate looks wrong: {bdt}")
    if not 50 <= k22 <= 600 or not 50 <= k24 <= 600:
        raise RuntimeError(f"Gold rate looks wrong: 22K={k22} 24K/g={k24}")
    return {"bdt": bdt, "k22": k22, "k24": k24}


def _check_fresh(text):
    """mirror page shows 'LAST UPDATE: dd-mm-yyyy' - refuse old data"""
    m = re.search(r"LAST UPDATE\W*(\d{2})-(\d{2})-(\d{4})", text)
    if m:
        d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        age = (datetime.now() - d).days
        if age > 3:
            raise RuntimeError(f"backup source is {age} days old")


def fetch_rates():
    errors = []
    try:  # 1) Mustafa's own site (may block foreign servers like GitHub's)
        r = _parse(_page_text(URL, tries=2, timeout=15))
        r["source"] = "mustafa.com.sg"
        r["url"] = URL
        return r
    except Exception as e:
        errors.append(f"mustafa.com.sg: {e}")
        print("Mustafa site failed, trying backup:", e)
    try:  # 2) backup: live copy of the same Mustafa rates
        text = _page_text(MIRROR)
        _check_fresh(text)
        r = _parse(text)
        r["source"] = "Mustafa rates via livepriceofgold.com"
        r["url"] = MIRROR
        return r
    except Exception as e:
        errors.append(f"backup: {e}")
    raise RuntimeError(" | ".join(errors))


# ---------- card ----------
def _fit(d, text, size, maxw):
    while size > 20 and _wlen(d, text, size) > maxw:
        size -= 2
    return size


def make_rate_card(r, now, path="rate_card.png"):
    W, H = 1080, 1400
    img = Image.new("RGB", (W, H), "#0a0a0a")
    d = ImageDraw.Draw(img)

    def line(text, size, y, fill, x=None, maxw=W - 120):
        s = _fit(d, text, size, maxw)
        _draw_line(d, text.split(), s, y + (size - s) // 2, W, fill, x=x)

    # logo + QR + flags (same as news card)
    d.rectangle([40, 42, 46, 92], fill="#dc2626")
    _draw_line(d, PAGE_NAME.split(), 46, 38, W, WHITE, x=62)
    page_url = os.environ.get("FB_PAGE_URL") or "https://www.facebook.com/Aryaanby/"
    if page_url:
        q = qrcode.make(page_url, border=1).convert("RGB").resize((116, 116))
        d.rectangle([34, 112, 34 + 124, 112 + 124], fill="white")
        img.paste(q, (38, 116))
        d.text((34, 244), "Follow us on Facebook", font=_lat(15), fill="#facc15")
    x = W - 40 - 96
    for cc in ("bd", "sg"):
        f = _flag(cc)
        if f:
            d.rectangle([x - 3, 47, x + 99, 114], fill="white")
            img.paste(f, (x, 50))
            x -= 110

    # title + date
    line("আজকের রেট", 100, 290, GREEN)
    line(f"{bn(now.day)} {BN_MONTHS[now.month - 1]} {bn(now.year)}", 44, 420, "#e5e7eb")

    # panel 1: money transfer
    py = 510
    d.rounded_rectangle([30, py, W - 30, py + 260], radius=44, fill=PANEL)
    line("সিঙ্গাপুর থেকে বাংলাদেশ", 40, py + 28, GREY)
    line(f"Mustafa: ১ SGD = {money(r['bdt'])} BDT", 60, py + 100, GREEN)
    line("Mustafa Remittance রেট", 34, py + 195, GREY)

    # panel 2: gold
    gy = 800
    d.rounded_rectangle([30, gy, W - 30, gy + 400], radius=44, fill=PANEL)
    line("সোনার দাম (Mustafa)", 40, gy + 28, GREY)
    line(f"২২K ১ গ্রাম: SGD {money(r['k22'])}", 54, gy + 100, GREEN)
    line(f"২৪K ১ গ্রাম: SGD {money(r['k24'])}", 54, gy + 180, GREEN)
    v22 = r["k22"] * VORI * r["bdt"]
    v24 = r["k24"] * VORI * r["bdt"]
    line(f"আনুমানিক: ২২ ক্যারেট ১ ভরি: {money(v22, 0)} BDT", 40, gy + 275, WHITE)
    line(f"আনুমানিক: ২৪ ক্যারেট ১ ভরি: {money(v24, 0)} BDT", 40, gy + 335, WHITE)

    # small print
    line("রেট যেকোনো সময় কমবেশি হতে পারে।", 32, 1235, GREY)
    line("বিক্রির আগে দোকান বা এক্সচেঞ্জে রেট যাচাই করে নিন।", 32, 1285, GREY)
    line(f"Source: {r.get('source', 'mustafa.com.sg')} | {now:%d %b %Y, %I:%M %p} SGT", 26, 1350, DIM)
    img.save(path)
    return path


def caption(r, now):
    v22 = r["k22"] * VORI * r["bdt"]
    return (
        f"আজকের রেট - {bn(now.day)} {BN_MONTHS[now.month - 1]} {bn(now.year)}\n\n"
        f"Mustafa: ১ SGD = {money(r['bdt'])} BDT\n"
        f"সোনা ২২K ১ গ্রাম: SGD {money(r['k22'])} | ২৪K ১ গ্রাম: SGD {money(r['k24'])}\n"
        f"আনুমানিক ২২ ক্যারেট ১ ভরি: {money(v22, 0)} BDT\n\n"
        "রেট যেকোনো সময় কমবেশি হতে পারে।"
    )


def main():
    now = datetime.now(ZoneInfo("Asia/Singapore"))
    owner = os.environ.get("TG_OWNER_ID")
    try:
        r = fetch_rates()
    except Exception as ex:
        print("FAILED:", ex)
        if owner and os.environ.get("TG_BOT_TOKEN"):
            tg_say(owner, f"⚠️ Rate card not made: {ex}")
        sys.exit(1)
    print("Rates:", r)
    path = make_rate_card(r, now)
    cap = caption(r, now)
    if os.environ.get("RATE_AUTOPOST", "true").lower() in ("1", "true", "yes"):
        post_id = post_card(path, cap, r.get("url", URL))
        print("Posted:", post_id)
        if owner and os.environ.get("TG_BOT_TOKEN"):
            try:
                tg_say(owner, "Rate card posted to Facebook ✅")
            except Exception:
                pass
    else:  # only if RATE_AUTOPOST=false: Telegram ✅ Post / ❌ Cancel flow
        tg_preview(owner, {"path": path, "caption": cap, "url": r.get("url", URL)})
        print("Sent to Telegram for approval")


if __name__ == "__main__":
    main()
