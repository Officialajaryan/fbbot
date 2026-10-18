import os, re
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from common import load_state, save_state, publish

BOT = os.environ["TG_BOT_TOKEN"]
OWNER = str(os.environ["TG_OWNER_ID"])
API = f"https://api.telegram.org/bot{BOT}"


def say(chat, text):
    requests.post(f"{API}/sendMessage", data={"chat_id": chat, "text": text}, timeout=20)


def read_article(url):
    h = {"User-Agent": "Mozilla/5.0"}
    soup = BeautifulSoup(requests.get(url, headers=h, timeout=30).text, "html.parser")

    def meta(p):
        t = soup.find("meta", property=p)
        return t["content"] if t and t.get("content") else ""

    title = meta("og:title") or (soup.title.string if soup.title else "")
    paras = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))[:3000]
    body = meta("og:description") + " " + paras
    return title.strip(), body.strip()


def main():
    state = load_state()
    r = requests.get(f"{API}/getUpdates", params={"offset": state["tg_offset"] + 1}, timeout=30).json()
    for u in r.get("result", []):
        state["tg_offset"] = u["update_id"]
        m = u.get("message") or {}
        chat = str(m.get("chat", {}).get("id", ""))
        if chat != OWNER:
            continue
        found = re.findall(r"https?://\S+", m.get("text", ""))
        if not found:
            continue
        url = found[0]
        try:
            title, body = read_article(url)
            src = urlparse(url).netloc.replace("www.", "")
            publish(title, body, src, url)
            say(chat, "Posted to Facebook ✅")
        except Exception as ex:
            say(chat, f"Failed: {ex}")
    save_state(state)


if __name__ == "__main__":
    main()
