import os, re
import requests
from bs4 import BeautifulSoup
from common import (load_state, save_state, prepare, post_card,
                    tg_say, tg_preview, tg_download, _tg)

OWNER = str(os.environ["TG_OWNER_ID"])


def read_article(url):
    h = {"User-Agent": "Mozilla/5.0"}
    soup = BeautifulSoup(requests.get(url, headers=h, timeout=30).text, "html.parser")

    def meta(p):
        t = soup.find("meta", property=p)
        return t["content"] if t and t.get("content") else ""

    title = meta("og:title") or (soup.title.string if soup.title else "")
    paras = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))[:3000]
    return title.strip(), (meta("og:description") + " " + paras).strip()


def handle_button(state, cb):
    requests.post(f"{_tg()}/answerCallbackQuery", data={"callback_query_id": cb["id"]}, timeout=20)
    action, _, pid = cb["data"].partition(":")
    chat = str(cb["message"]["chat"]["id"])
    item = state["pending"].pop(pid, None)
    if not item:
        tg_say(chat, "This one was already handled.")
        return
    if action == "no":
        tg_say(chat, "Cancelled ❌")
        return
    try:
        path = tg_download(item["file_id"])
        post_card(path, item["caption"], item["url"])
        tg_say(chat, "Posted to Facebook ✅")
    except Exception as ex:
        tg_say(chat, f"Failed: {ex}")


def main():
    state = load_state()
    r = requests.get(f"{_tg()}/getUpdates", params={"offset": state["tg_offset"] + 1}, timeout=30).json()
    for u in r.get("result", []):
        state["tg_offset"] = u["update_id"]
        cb = u.get("callback_query")
        if cb:
            if str(cb["from"]["id"]) == OWNER:
                handle_button(state, cb)
            continue
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
            card = prepare(title, body, url)
            if not card["has_photo"]:
                tg_say(chat, "⚠️ No image found for this link - plain background used.")
            tg_preview(chat, card, state)
        except Exception as ex:
            tg_say(chat, f"Failed: {ex}")
    save_state(state)


if __name__ == "__main__":
    main()
