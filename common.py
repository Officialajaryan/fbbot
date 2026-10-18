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
        "You are a Bangla news editor for a Facebook page. Translate the news into natural, "
        "simple, accurate Bangla. Keep names of places/organisations in English if that is how "
        "Bangladeshis commonly read them. Do not add facts not in the text. "
        'Reply ONLY with JSON: {"headline": "punchy Bangla headline, max 60 chars, may end with !", '
        '"subline": "one Bangla sentence, max 110 chars, ends with ।", '
        '"country": "sg if the news is about Singapore, otherwise empty", '
        '"relevant": "true only if the news is about Singapore, or Bangladesh, or directly affects Bangladeshis living or working in Singapore (work passes, MOM rules, migrant workers, remittance, Singapore-Bangladesh relations). Otherwise false", '
        '"image_prompt": "English prompt for an AI image: realistic documentary-style scene that illustrates the topic (places, objects, crowds from far away). NO real people, NO faces of public figures, NO text, NO logos, NO flags, max 40 words"}'
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


def make_card(headline, subline, photo=None, country="", path="card.png", ai_label=False):
    W, H, PH, PY = 1080, 1280, 680, 630
    img = Image.new("RGB", (W, H), "#0a0a0a")
    if photo is None:  # fallback background
        photo = Image.new("RGB", (W, PH), "#1e293b")
    img.paste(_cover(photo, W, PH), (0, 0))

    # darken photo (top + bottom fade)
    shade = Image.new("RGBA", (W, PH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(PH):
        a = int(max(0, (y - PH * 0.45) / (PH * 0.55)) * 235) + int(max(0, 1 - y / 220) * 110)
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, min(a, 255)))
    img.paste(Image.alpha_composite(img.crop((0, 0, W, PH)).convert("RGBA"), shade).convert("RGB"), (0, 0))

    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, PY, W, H + 80], radius=56, fill="#0a0a0a")

    if ai_label:
        lf = _lat(17)
        tw = d.textlength("AI-generated illustration", font=lf)
        d.text((W - tw - 30, PY - 34), "AI-generated illustration", font=lf, fill="#cbd5e1")

    # logo
    d.rectangle([40, 42, 46, 92], fill="#dc2626")
    _draw_line(d, PAGE_NAME.split(), 46, 38, W, "white", x=62)

    # QR
    page_url = os.environ.get("FB_PAGE_URL", "")
    if page_url:
        q = qrcode.make(page_url, border=1).convert("RGB").resize((116, 116))
        d.rectangle([34, 112, 34 + 124, 112 + 124], fill="white")
        img.paste(q, (38, 116))
        d.text((34, 244), "Follow us on Facebook", font=_lat(15), fill="#facc15")

    # flags (Bangladesh + related country)
    x = W - 40 - 96
    for cc in [c for c in (country, "bd") if c]:
        f = _flag(cc.lower())
        if f:
            d.rectangle([x - 3, 47, x + 99, 114], fill="white")
            img.paste(f, (x, 50))
            x -= 110

    # text block
    top, bottom = PY + 70, H - 50
    avail = bottom - top
    for size in range(84, 40, -3):
        lh = int(size * 1.4)
        hl = _wrap(d, headline, size, W - 110)
        sl = _wrap(d, subline, int(size * 0.92), W - 90)
        if (len(hl) + len(sl)) * lh <= avail:
            break
    y = top + (avail - (len(hl) + len(sl)) * lh) // 2
    for ln in hl:
        _draw_line(d, ln, size, y, W, "#39e75f")
        y += lh
    for ln in sl:
        _draw_line(d, ln, int(size * 0.92), y, W, "white")
        y += lh
    img.save(path)
    return path


def post_card(path, caption, source_url):
    with open(path, "rb") as f:
        r = requests.post(
            f"{GRAPH}/{PAGE_ID}/photos",
            data={"caption": caption, "access_token": TOKEN},
            files={"source": f}, timeout=60,
        )
    r.raise_for_status()
    j = r.json()
    post_id = j.get("post_id") or j["id"]
    c = requests.post(
        f"{GRAPH}/{post_id}/comments",
        data={"message": f"Source: {source_url}", "access_token": TOKEN},
        timeout=30,
    )
    c.raise_for_status()
    return post_id


class NoImage(Exception):
    pass


def prepare(title, body, url, require_relevant=False, require_image=False):
    """Make the card + caption without posting.
    Image order: AI image -> article image (or reverse if IMAGE_MODE=article)."""
    t = to_bangla(title, body)
    if require_relevant and str(t.get("relevant")).lower() not in ("true", "yes"):
        raise ValueError("not about Singapore/Bangladesh, skipped")
    mode = os.environ.get("IMAGE_MODE", "ai")  # "ai" or "article"
    photo, is_ai = None, False
    order = ["ai", "article"] if mode == "ai" else ["article", "ai"]
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
        raise NoImage("no image found from AI or article")
    path = make_card(t["headline"], t["subline"], photo, t.get("country", ""), ai_label=is_ai)
    return {"path": path, "caption": f'{t["headline"]}\n\n{t["subline"]}',
            "url": url, "has_photo": photo is not None}


def publish(title, body, source_name, url):
    c = prepare(title, body, url)
    return post_card(c["path"], c["caption"], c["url"])


# ---------- Telegram approval ----------
def _tg():
    return f"https://api.telegram.org/bot{os.environ['TG_BOT_TOKEN']}"


def tg_say(chat, text):
    requests.post(f"{_tg()}/sendMessage", data={"chat_id": chat, "text": text}, timeout=20)


def tg_preview(chat, c, state):
    """Send card to Telegram with Post / Cancel buttons; remember it in state."""
    pid = hashlib.md5(c["url"].encode()).hexdigest()[:10]
    kb = {"inline_keyboard": [[
        {"text": "✅ Post", "callback_data": f"ok:{pid}"},
        {"text": "❌ Cancel", "callback_data": f"no:{pid}"},
    ]]}
    with open(c["path"], "rb") as f:
        r = requests.post(
            f"{_tg()}/sendPhoto",
            data={"chat_id": chat, "caption": "Preview - post this?\nSource: " + c["url"],
                  "reply_markup": json.dumps(kb)},
            files={"photo": f}, timeout=60,
        ).json()
    fid = r["result"]["photo"][-1]["file_id"]
    state["pending"][pid] = {"file_id": fid, "caption": c["caption"], "url": c["url"]}
    return pid


def tg_download(file_id, path="approved.png"):
    info = requests.get(f"{_tg()}/getFile", params={"file_id": file_id}, timeout=30).json()
    fp = info["result"]["file_path"]
    data = requests.get(f"https://api.telegram.org/file/bot{os.environ['TG_BOT_TOKEN']}/{fp}", timeout=60).content
    with open(path, "wb") as f:
        f.write(data)
    return path
