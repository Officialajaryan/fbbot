import os, json, glob, re, io, functools, hashlib
import qrcode
import requests
from PIL import Image, ImageDraw, ImageFont

GRAPH = "https://graph.facebook.com/v21.0"
PAGE_ID = os.environ.get("FB_PAGE_ID", "")
TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
MODEL = "claude-haiku-5-5"
PAGE_NAME = os.environ.get("PAGE_NAME", "Bangla News")
STATE_FILE = "state.json"


def load_state():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("posted", [])
    s.setdefault("replied", [])
    s.setdefault("tg_offset", 0)
    s.setdefault("pending", {})
    return s


def save_state(s):
    s["posted"] = s["posted"][-500:]
    s["replied"] = s["replied"][-2000:]
    s["pending"] = dict(list(s["pending"].items())[-50:])
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=1)


def ask_claude(system, user, max_tokens=700):
    """Uses DeepSeek if DEEPSEEK_API_KEY is set, otherwise Claude."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "deepseek-chat",
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=90,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip()


def to_bangla(title, body):
    system = (
        "You are a Bangla news editor for a Facebook page for Bangladeshis living in Singapore. "
        "Translate the news into natural, simple, accurate Bangla. Keep names of places/organisations "
        "in English if that is how Bangladeshis commonly read them. Do not add facts not in the text. "
        'Reply ONLY with JSON: {"headline": "punchy Bangla headline that makes people curious but is 100% accurate, '
        'max 60 chars, may end with !", '
        '"subline": "one Bangla sentence, max 110 chars, ends with \u0964", '
        '"highlight": "1 to 3 key words copied EXACTLY from your headline (numbers, money, the main subject) to colour yellow", '
        '"country": "sg", '
        '"relevant": "true only if the news is about Singapore: its people, government, money, jobs, pay, work passes, '
        'MOM rules, cost of living, housing, transport, schools, health, safety, weather, or Singapore-Bangladesh ties. '
        'False for news about other countries, sports results, celebrity gossip or crime with no effect on residents", '
        '"image_prompt": "English prompt for an AI image: realistic documentary-style scene that illustrates the topic '
        '(places, objects, crowds from far away). NO real people, NO faces of public figures, NO text, NO logos, NO flags, max 40 words"}'
    )
    out = ask_claude(system, f"Title: {title}\n\nText: {body[:3000]}")
    out = re.sub(r"^```(?:json)?|```$", "", out.strip()).strip()
    return json.loads(out)


# ---------- fonts ----------
@functools.lru_cache(maxsize=None)
def _bn(size):
    files = glob.glob("/usr/share/fonts/truetype/noto/NotoSansBengali*")
    files.sort(key=lambda p: ("Bold" not in p, "UI" in p, p))
    if not files:
        raise RuntimeError("Bangla font not found. Install fonts-noto-core.")
    try:
        return ImageFont.truetype(files[0], size, layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        return ImageFont.truetype(files[0], size)


@functools.lru_cache(maxsize=None)
def _lat(size):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return _bn(size)


def _runs(word):
    """split a word into (text, is_latin) runs"""
    return [(m, bool(re.match(r"[A-Za-z0-9]", m)))
            for m in re.findall(r"[A-Za-z0-9]+|[^A-Za-z0-9]+", word)]


def _wlen(d, word, size):
    return sum(d.textlength(t, font=(_lat(size) if lat else _bn(size))) for t, lat in _runs(word))


def _wrap(d, text, size, maxw):
    space = d.textlength(" ", font=_bn(size))
    lines, cur, curw = [], [], 0
    for w in text.split():
        ww = _wlen(d, w, size)
        if cur and curw + space + ww > maxw:
            lines.append(cur)
            cur, curw = [w], ww
        else:
            curw += (space if cur else 0) + ww
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def _draw_line(d, words, size, y, W, fill, x=None):
    space = d.textlength(" ", font=_bn(size))
    total = sum(_wlen(d, w, size) for w in words) + space * (len(words) - 1)
    cx = x if x is not None else (W - total) / 2
    base = y + size
    for i, w in enumerate(words):
        for t, lat in _runs(w):
            f = _lat(size) if lat else _bn(size)
            d.text((cx, base), t, font=f, fill=fill, anchor="ls")
            cx += d.textlength(t, font=f)
        cx += space


# ---------- images ----------
UA = {"User-Agent": "Mozilla/5.0"}


def get_article_image(url):
    """Get the article's main picture (og:image / twitter:image)."""
    try:
        html = requests.get(url, headers=UA, timeout=25).text
        cands = []
        for prop in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src"):
            for pat in (
                r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop) + r'["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']' + re.escape(prop),
            ):
                cands += re.findall(pat, html)
        for u in cands:
            u = u.replace("&amp;", "&")
            if u.startswith("//"):
                u = "https:" + u
            try:
                r = requests.get(u, headers=UA, timeout=25)
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                if img.width >= 300 and img.height >= 200:
                    return img
            except Exception as e:
                print("bad article image:", e)
        return None
    except Exception as e:
        print("no image:", e)
        return None


def get_ai_image(prompt):
    """Free AI image via Pollinations (no API key). Prints why it fails."""
    import random, urllib.parse, time
    full = prompt + ", realistic news photo, natural light, high detail, no text, no watermark"
    q = urllib.parse.quote(full)
    tries = [
        f"https://image.pollinations.ai/prompt/{q}?width=1080&height=680&nologo=true&model=flux&seed=",
        f"https://image.pollinations.ai/prompt/{q}?width=1080&height=680&nologo=true&seed=",
        f"https://pollinations.ai/p/{q}?width=1080&height=680&nologo=true&seed=",
    ]
    for url in tries:
        for attempt in range(3):
            try:
                r = requests.get(url + str(random.randint(1, 10**6)), headers=UA, timeout=120)
                ct = r.headers.get("content-type", "")
                if r.ok and ct.startswith("image"):
                    return Image.open(io.BytesIO(r.content)).convert("RGB")
                print("AI image failed:", r.status_code, ct, r.text[:150].replace("\n", " "))
            except Exception as e:
                print("AI image error:", e)
            time.sleep(4)
    return None


def _cover(img, w, h):
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1))
    l, t = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((l, t, l + w, t + h))


def _flag(cc):
    try:
        r = requests.get(f"https://flagcdn.com/w160/{cc}.png", timeout=15)
        return Image.open(io.BytesIO(r.content)).convert("RGB").resize((96, 64))
    except Exception:
        return None


def _cover_at(img, w, h, fy=0.3):
    """cover-crop; fy 0 = keep top, 1 = keep bottom (0.3 keeps faces, which are usually high up)"""
    sc = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * sc) + 1, int(img.height * sc) + 1))
    l, t = (img.width - w) // 2, int((img.height - h) * fy)
    return img.crop((l, t, l + w, t + h))


def _draw_words(d, words, size, y, W, base, hi_words):
    """one centred line; words in hi_words are yellow"""
    space = d.textlength(" ", font=_bn(size))
    total = sum(_wlen(d, w, size) for w in words) + space * (len(words) - 1)
    cx = (W - total) / 2
    for w in words:
        col = "#ffd60a" if w.strip("!?.,।:;\"'") in hi_words else base
        for t, lat in _runs(w):
            f = _lat(size) if lat else _bn(size)
            d.text((cx, y + size), t, font=f, fill=col, anchor="ls")
            cx += d.textlength(t, font=f)
        cx += space


def make_card(headline, subline, photo=None, country="sg", path="card.png", ai_label=False,
              credit="", highlight=""):
    """1080x1350 (4:5). Big photo on top, red tag, white headline with yellow key words,
    footer with Facebook QR."""
    W, H, PH = 1080, 1350, 800
    PAD = 50
    img = Image.new("RGB", (W, H), "#0a0a0a")
    if photo is None:  # fallback background: dark blue gradient
        photo = Image.new("RGB", (W, PH))
        pd = ImageDraw.Draw(photo)
        for y in range(PH):
            pd.line([(0, y), (W, y)], fill=(18, 30 + y // 18, 60 + y // 12))
    img.paste(_cover_at(photo, W, PH, 0.3), (0, 0))

    # top shade (for logo/flags) + long bottom fade into the dark panel
    shade = Image.new("RGBA", (W, PH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(PH):
        top = max(0.0, 1 - y / 230) * 0.55
        bot = max(0.0, (y - PH * 0.50) / (PH * 0.50)) ** 1.4
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, int(255 * min(1.0, top + bot))))
    img.paste(Image.alpha_composite(img.crop((0, 0, W, PH)).convert("RGBA"), shade).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img)

    # brand (top-left) + flags (top-right)
    d.rectangle([40, 42, 46, 92], fill="#dc2626")
    _draw_line(d, PAGE_NAME.split(), 46, 38, W, "white", x=62)
    x = W - 40 - 96
    for cc in [c for c in (country, "bd") if c]:
        f = _flag(cc.lower())
        if f:
            d.rectangle([x - 3, 47, x + 99, 114], fill="white")
            img.paste(f, (x, 50))
            x -= 110

    # red tag
    tag, tsz = "সিঙ্গাপুর নিউজ", 36
    tw = int(_width_words(d, tag, tsz))
    ty = PH - 70
    d.rounded_rectangle([PAD, ty, PAD + tw + 56, ty + 66], radius=33, fill="#dc2626")
    _draw_line(d, tag.split(), tsz, ty + 11, W, "white", x=PAD + 28)

    # photo credit / AI label (right of the tag)
    note = "AI-generated illustration" if ai_label else (f"Photo: {credit}" if credit else "")
    if note:
        lf = _lat(18)
        d.text((W - PAD - d.textlength(note, font=lf), ty + 24), note, font=lf, fill="#cbd5e1")

    # headline + subline
    hi = {w for w in (highlight or "").replace(",", " ").split()}
    top, bottom = PH + 20, 1195
    avail = bottom - top
    for size in range(92, 44, -3):
        lh = int(size * 1.32)
        ssz = max(30, int(size * 0.5))
        slh = int(ssz * 1.45)
        hl = _wrap(d, headline, size, W - 2 * PAD - 20)
        sl = _wrap(d, subline, ssz, W - 2 * PAD - 20)
        if len(hl) * lh + len(sl) * slh + 20 <= avail:
            break
    y = top + (avail - (len(hl) * lh + len(sl) * slh + 20)) // 2
    for ln in hl:
        _draw_words(d, ln, size, y, W, "white", hi)
        y += lh
    y += 20
    for ln in sl:
        _draw_line(d, ln, ssz, y, W, "#aeb7c2")
        y += slh

    # footer: follow text (left) + QR (right)
    d.line([PAD, 1222, W - PAD, 1222], fill="#26262b", width=2)
    _draw_line(d, "ফেসবুকে ফলো করুন".split(), 36, 1250, W, "white", x=PAD)
    _draw_line(d, PAGE_NAME.split(), 30, 1300, W, "#facc15", x=PAD)
    page_url = os.environ.get("FB_PAGE_URL", "")
    if page_url:
        q = qrcode.make(page_url, border=1).convert("RGB").resize((96, 96))
        d.rectangle([W - PAD - 104, 1236, W - PAD, 1236 + 104], fill="white")
        img.paste(q, (W - PAD - 100, 1240))
    img.save(path)
    return path


def _width_words(d, text, size):
    space = d.textlength(" ", font=_bn(size))
    ws = text.split()
    return sum(_wlen(d, w, size) for w in ws) + space * (len(ws) - 1)


def _fb_check(r):
    if not r.ok:
        raise RuntimeError(f"Facebook error {r.status_code}: {r.text[:300]}")


def clean_url(u):
    """Remove tracking junk (fbclid, cid, utm_*) from a link."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    p = urlsplit(u)
    bad = {"fbclid", "cid", "traffic_source", "gclid", "igshid", "ref", "ref_src", "mc_cid"}
    q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in bad and not k.lower().startswith("utm_")]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ""))


def post_card(path, caption, source_url):
    with open(path, "rb") as f:
        r = requests.post(
            f"{GRAPH}/{PAGE_ID}/photos",
            data={"caption": caption, "access_token": TOKEN},
            files={"source": f}, timeout=60,
        )
    _fb_check(r)
    j = r.json()
    post_id = j.get("post_id") or j["id"]
    try:
        c = requests.post(
            f"{GRAPH}/{post_id}/comments",
            data={"message": f"Source: {source_url}", "access_token": TOKEN},
            timeout=30,
        )
        _fb_check(c)
    except Exception as e:
        print("source comment failed (post is live):", e)
    return post_id


class NoImage(Exception):
    pass


HASHTAGS = "#Singapore #সিঙ্গাপুর #প্রবাসী #SingaporeNews"


def prepare(title, body, url, require_relevant=False, require_image=False, source=""):
    """Make the card + caption without posting.
    Image order: real article photo -> AI image (set IMAGE_MODE=ai to reverse)."""
    t = to_bangla(title, body)
    if require_relevant and str(t.get("relevant")).lower() not in ("true", "yes"):
        raise ValueError("not about Singapore, skipped")
    mode = os.environ.get("IMAGE_MODE", "article")  # "article" or "ai"
    photo, is_ai = None, False
    order = ["article", "ai"] if mode == "article" else ["ai", "article"]
    for src in order:
        if src == "ai":
            photo = get_ai_image(t.get("image_prompt") or title)
            is_ai = photo is not None
        else:
            photo = get_article_image(url)
            is_ai = False
        if photo is not None:
            break
    if photo is None and require_image:
        raise NoImage("no image found from article or AI")
    path = make_card(t["headline"], t["subline"], photo, t.get("country") or "sg",
                     ai_label=is_ai, credit=source, highlight=t.get("highlight", ""))
    caption = (f'{t["headline"]}\n\n{t["subline"]}\n\n'
               f"💬 আপনার মতামত কমেন্টে জানান\n📤 প্রবাসী ভাইদের সাথে শেয়ার করুন\n\n{HASHTAGS}")
    return {"path": path, "caption": caption, "url": url, "has_photo": photo is not None}


def publish(title, body, source_name, url):
    c = prepare(title, body, url)
    return post_card(c["path"], c["caption"], c["url"])


# ---------- Telegram approval ----------
def _tg():
    return f"https://api.telegram.org/bot{os.environ['TG_BOT_TOKEN']}"


def tg_say(chat, text):
    requests.post(f"{_tg()}/sendMessage", data={"chat_id": chat, "text": text}, timeout=20)


def tg_preview(chat, c, state=None):
    """Send card to Telegram with Post / Cancel buttons.
    The caption carries everything needed to post (headline + source), so the
    button works without any saved state."""
    kb = {"inline_keyboard": [[
        {"text": "✅ Post", "callback_data": "ok"},
        {"text": "❌ Cancel", "callback_data": "no"},
    ]]}
    caption = f'{c["caption"]}\n\nSource: {c["url"]}'
    with open(c["path"], "rb") as f:
        r = requests.post(
            f"{_tg()}/sendPhoto",
            data={"chat_id": chat, "caption": caption[:1024],
                  "reply_markup": json.dumps(kb)},
            files={"photo": f}, timeout=60,
        ).json()
    if not r.get("ok"):
        raise RuntimeError(f"Telegram error: {r}")


def tg_notify(chat, path, caption):
    """Send the card to Telegram as a plain copy (no buttons). Never raises."""
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"{_tg()}/sendPhoto",
                data={"chat_id": chat, "caption": caption[:1024]},
                files={"photo": f}, timeout=60,
            ).json()
        if not r.get("ok"):
            print("Telegram notify failed:", r)
    except Exception as e:
        print("Telegram notify error:", e)


def tg_download(file_id, path="approved.png"):
    info = requests.get(f"{_tg()}/getFile", params={"file_id": file_id}, timeout=30).json()
    fp = info["result"]["file_path"]
    data = requests.get(f"https://api.telegram.org/file/bot{os.environ['TG_BOT_TOKEN']}/{fp}", timeout=60).content
    with open(path, "wb") as f:
        f.write(data)
    return path
