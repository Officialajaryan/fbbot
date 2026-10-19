"""Daily "আজকের রেট" card in the simple centred layout (brand, title, date,
SGD->BDT, gold, small print).
SGD->BDT  : Ria Money Transfer (main source), Mustafa as backup.
Gold      : Mustafa (22K / 24K per gram). If gold cannot be read, the card is
            still made with the BDT rate only."""
import os, re, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

import qrcode
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

import common
from common import PAGE_NAME, _bn, _lat, _wlen, _draw_line, _flag, get_ai_image, post_card, tg_preview, tg_say

RIA_URL = "https://www.riamoneytransfer.com/en-us/rates-conversion/?From=SGD&To=BDT&Amount=1"
URL = "https://www.mustafa.com.sg/"
MIRROR = "https://www.livepriceofgold.com/mustafa-gold-price.html"  # copy of Mustafa's rates
VORI = 11.664  # grams in 1 bhori/vori
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
GREEN, WHITE, GREY, DIM, CARD, LINE = "#4ade80", "#f4f7f4", "#93a39a", "#6b7a72", "#0f1512", "#24302a"
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


def _check_bdt(bdt):
    if not 50 <= bdt <= 200:
        raise RuntimeError(f"BDT rate looks wrong: {bdt}")
    return bdt


def _parse_ria(text):
    """Ria page text contains e.g. '1.00 SGD = 96.39270177 BDT'"""
    return _check_bdt(_find(text, [r"1(?:\.00)?\s*SGD\s*=\s*([\d.,]+)\s*BDT"], "Ria SGD->BDT rate"))


def _parse_mustafa_bdt(text):
    return _check_bdt(_find(text, [r"Bangladesh Taka\s*(?:Todays?|Today's)?\s*Rate\s*([\d.,]+)",
                                   r"Draft Rate:?\s*Bangladesh Taka\s*([\d.,]+)"], "BDT rate"))


def _parse_gold(text):
    k22 = _find(text, [r"22K\s*-?\s*916\s*Jewellery\s*([\d.,]+)",
                       r"22K Gold \(916\) Jewellery\s*([\d.,]+)"], "22K gold rate")
    bar = _find(text, [r"24K\s*-?\s*999\s*Gold\s*Bar\s*100\s*g\s*([\d.,]+)",
                       r"24K Gold Bar: 100 Gram \(999\)\s*([\d.,]+)"], "24K gold bar rate")
    k24 = bar / 100  # price per gram
    if not 50 <= k22 <= 600 or not 50 <= k24 <= 600:  # never post nonsense
        raise RuntimeError(f"Gold rate looks wrong: 22K={k22} 24K/g={k24}")
    return {"k22": k22, "k24": k24}


def _check_fresh(text):
    """mirror page shows 'LAST UPDATE: dd-mm-yyyy' - refuse old data"""
    m = re.search(r"LAST UPDATE\W*(\d{2})-(\d{2})-(\d{4})", text)
    if m:
        d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        age = (datetime.now() - d).days
        if age > 3:
            raise RuntimeError(f"backup source is {age} days old")


def fetch_bdt():
    """Main: Ria. Backups: Mustafa site, then Mustafa mirror."""
    errors = []
    try:
        return {"bdt": _parse_ria(_page_text(RIA_URL, tries=3, timeout=20)),
                "bdt_source": "Ria Money Transfer", "bdt_url": RIA_URL}
    except Exception as e:
        errors.append(f"Ria: {e}")
        print("Ria failed, trying Mustafa:", e)
    try:
        return {"bdt": _parse_mustafa_bdt(_page_text(URL, tries=2, timeout=15)),
                "bdt_source": "Mustafa", "bdt_url": URL}
    except Exception as e:
        errors.append(f"mustafa.com.sg: {e}")
    try:
        text = _page_text(MIRROR)
        _check_fresh(text)
        return {"bdt": _parse_mustafa_bdt(text),
                "bdt_source": "Mustafa", "bdt_url": MIRROR}
    except Exception as e:
        errors.append(f"mirror: {e}")
    raise RuntimeError(" | ".join(errors))


def fetch_gold():
    """Mustafa gold. Returns None if it cannot be read (card then has no gold block)."""
    for url in (URL, MIRROR):
        try:
            text = _page_text(url, tries=2, timeout=15)
            if url == MIRROR:
                _check_fresh(text)
            return _parse_gold(text)
        except Exception as e:
            print(f"gold from {url} failed:", e)
    return None


def fetch_rates():
    r = fetch_bdt()
    g = fetch_gold()
    r["k22"] = g["k22"] if g else None
    r["k24"] = g["k24"] if g else None
    return r


# ---------- card ----------
def _fit(d, text, size, maxw):
    while size > 20 and _wlen(d, text, size) > maxw:
        size -= 2
    return size


def _width(d, text, size):
    space = d.textlength(" ", font=_bn(size))
    ws = text.split()
    return sum(_wlen(d, w, size) for w in ws) + space * (len(ws) - 1)


HERO_H = 540
OWN_PHOTO_FOCUS_Y = 0.95  # 0 = crop from top, 1 = from bottom (keeps lower part of your photo)
# one scene per weekday; used only when no own photo is found in ./photos/
SCENES = [
    "Marina Bay Sands Singapore skyline at golden hour, calm water",
    "green rice fields in Bangladesh at sunrise, soft mist, village",
    "Singapore Gardens by the Bay supertrees at dusk, no people",
    "Bangladesh river with a wooden boat at sunset, golden light",
    "Singapore Merlion and city skyline at blue hour, no people",
    "Dhaka city skyline at sunset, warm light, no people",
    "Singapore airport plane taking off at sunrise, travel mood",
]


def get_hero_photo(now):
    """1) own photo from ./photos/ (rotates daily)  2) AI photo  3) None -> gradient"""
    import glob
    mine = sorted(glob.glob("photos/*.jpg") + glob.glob("photos/*.jpeg") + glob.glob("photos/*.png"))
    if mine:
        try:
            im = Image.open(mine[now.toordinal() % len(mine)]).convert("RGB")
            im.info["focus_y"] = OWN_PHOTO_FOCUS_Y
            return im
        except Exception as e:
            print("own photo failed:", e)
    try:
        return get_ai_image(SCENES[now.weekday()])
    except Exception as e:
        print("AI photo failed:", e)
        return None


def _hero(W, photo):
    """top banner: photo (or green gradient) fading into the card colour"""
    if photo is not None:
        fy = photo.info.get("focus_y", 0.5)
        sc = max(W / photo.width, HERO_H / photo.height)
        ph = photo.resize((int(photo.width * sc) + 1, int(photo.height * sc) + 1))
        l, t = (ph.width - W) // 2, int((ph.height - HERO_H) * fy)
        hero = ph.crop((l, t, l + W, t + HERO_H))
    else:
        hero = Image.new("RGB", (W, HERO_H))
        hd = ImageDraw.Draw(hero)
        for y in range(HERO_H):
            t = y / HERO_H
            hd.line([(0, y), (W, y)], fill=(int(20 + 6 * t), int(83 - 60 * t), int(45 - 25 * t)))
    # darken for readable text + fade into the card
    shade = Image.new("L", (W, HERO_H))
    sd = ImageDraw.Draw(shade)
    for y in range(HERO_H):
        t = y / HERO_H
        sd.line([(0, y), (W, y)], fill=int(255 * (0.12 + 0.88 * t ** 2.4)))
    return Image.composite(Image.new("RGB", (W, HERO_H), CARD), hero, shade)


def make_rate_card(r, now, path="rate_card.png", photo="auto"):
    """Photo banner with title on top, then BDT rate, gold rows, small print."""
    W, H = 1080, 1350
    PAD = 90
    if photo == "auto":
        photo = get_hero_photo(now)
    img = Image.new("RGB", (W, H), CARD)
    img.paste(_hero(W, photo), (0, 0))
    d = ImageDraw.Draw(img)

    def line(text, size, y, fill, maxw=W - 2 * PAD):
        s = _fit(d, text, size, maxw)
        _draw_line(d, text.split(), s, y + (size - s) // 2, W, fill)

    def row(left, right, size_l, size_r, y):
        _draw_line(d, left.split(), size_l, y + (size_r - size_l) // 2 + 6, W, WHITE, x=PAD)
        _draw_line(d, right.split(), size_r, y, W, GREEN, x=W - PAD - _width(d, right, size_r))

    def divider(y):
        d.line([PAD, y, W - PAD, y], fill=LINE, width=2)

    # brand (left) + flags (right) on the photo
    d.rectangle([40, 44, 46, 90], fill="#dc2626")
    _draw_line(d, PAGE_NAME.upper().split(), 38, 42, W, WHITE, x=62)
    x = W - 40 - 96
    for cc in ("bd", "sg"):
        f = _flag(cc)
        if f:
            d.rectangle([x - 3, 47, x + 99, 114], fill="white")
            img.paste(f, (x, 50))
            x -= 110

    line("আজকের রেট", 120, 320, WHITE)
    line(f"{bn(now.day)} {BN_MONTHS[now.month - 1]} {bn(now.year)}", 40, 462, "#e5ebe7")

    # block 1: money transfer
    y0 = HERO_H + 10
    line("সিঙ্গাপুর থেকে বাংলাদেশ", 38, y0 + 10, GREY)
    line(f"১ SGD = {money(r['bdt'])} BDT", 96, y0 + 80, GREEN)

    # block 2: gold (only when available)
    if r.get("k22") and r.get("k24"):
        divider(y0 + 250)
        line("সোনার দাম, ১ গ্রাম", 38, y0 + 285, GREY)
        row("২২ ক্যারেট", f"SGD {money(r['k22'])}", 46, 62, y0 + 365)
        row("২৪ ক্যারেট", f"SGD {money(r['k24'])}", 46, 62, y0 + 470)

    # small print
    line("রেট যেকোনো সময় বদলাতে পারে। লেনদেনের আগে যাচাই করে নিন।", 30, 1215, GREY)
    src = r.get("bdt_source", "Ria Money Transfer")
    if r.get("k22"):
        src += " | Mustafa (gold)"
    line(f"{src} | {now:%d %b %Y, %I:%M %p} SGT", 26, 1280, DIM)
    img.save(path)
    return path


def caption(r, now):
    lines = [f"\U0001F4B8 আজ দেশে টাকা পাঠাবেন? আগে রেট দেখে নিন! - {bn(now.day)} {BN_MONTHS[now.month - 1]} {bn(now.year)}", "",
             f"{r.get('bdt_source', 'Ria')}: ১ SGD = {money(r['bdt'])} BDT"]
    if r.get("k22") and r.get("k24"):
        v22 = r["k22"] * VORI * r["bdt"]
        lines += [f"সোনা ২২K ১ গ্রাম: SGD {money(r['k22'])} | ২৪K ১ গ্রাম: SGD {money(r['k24'])}",
                  f"আনুমানিক ২২ ক্যারেট ১ ভরি: {money(v22, 0)} BDT"]
    lines += ["", "রেট যেকোনো সময় বদলাতে পারে।", "",
              "\U0001F4E4 প্রবাসী ভাইদের জানাতে শেয়ার করুন",
              "#সিঙ্গাপুর #বাংলাদেশ #রেমিট্যান্স #আজকেরRate #SGDtoBDT"]
    return "\n".join(lines)


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
        post_id = post_card(path, cap, r.get("bdt_url", RIA_URL))
        print("Posted:", post_id)
        if owner and os.environ.get("TG_BOT_TOKEN"):
            try:
                tg_say(owner, "Rate card posted to Facebook ✅")
            except Exception:
                pass
    else:  # only if RATE_AUTOPOST=false: Telegram ✅ Post / ❌ Cancel flow
        tg_preview(owner, {"path": path, "caption": cap, "url": r.get("bdt_url", RIA_URL)})
        print("Sent to Telegram for approval")


if __name__ == "__main__":
    main()
