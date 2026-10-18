import os, re, json, time
import requests
from bs4 import BeautifulSoup
from common import prepare, post_card, tg_say, tg_preview, tg_download, clean_url, _tg

OWNER = str(os.environ["TG_OWNER_ID"])
RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "270"))  # how long each run listens


def read_article(url):
    h = {"User-Agent": "Mozilla/5.0"}
    soup = BeautifulSoup(requests.get(url, headers=h, timeout=30).text, "html.parser")

    def meta(p):
        t = soup.find("meta", property=p)
        return t["content"] if t and t.get("content") else ""

    title = meta("og:title") or (soup.title.string if soup.title else "")
    paras = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))[:3000]
    return title.strip(), (meta("og:description") + " " + paras).strip()


def api(method, **data):
    try:
        return requests.post(f"{_tg()}/{method}", data=data, timeout=30).json()
    except Exception as e:
        print(method, "error:", e)
        return {}


def handle_button(cb, done):
    msg = cb.get("message") or {}
    chat = str(msg.get("chat", {}).get("id", ""))
    mid = msg.get("message_id")
    key = (chat, mid)
    action = (cb.get("data") or "").partition(":")[0]

    if key in done:
        api("answerCallbackQuery", callback_query_id=cb["id"], text="Already handled")
        return
    done.add(key)

    # remove the buttons at once so it can't be tapped twice
    api("editMessageReplyMarkup", chat_id=chat, message_id=mid,
        reply_markup=json.dumps({"inline_keyboard": []}))

    if action == "no":
        api("answerCallbackQuery", callback_query_id=cb["id"], text="Cancelled")
        tg_say(chat, "Cancelled ❌")
        return

    api("answerCallbackQuery", callback_query_id=cb["id"], text="Posting... ⏳")
    try:
        photos = msg.get("photo") or []
        fb_caption, sep, url = (msg.get("caption") or "").rpartition("\n\nSource: ")
        if not photos or not sep or not url.strip():
            tg_say(chat, "This is an old preview and can't be posted. Please send the link again.")
            return
        path = tg_download(photos[-1]["file_id"])
        post_card(path, fb_caption, url.strip())
        tg_say(chat, "Posted to Facebook ✅")
    except Exception as ex:
        tg_say(chat, f"Failed: {ex}")
        done.discard(key)
        if msg.get("reply_markup"):  # give the buttons back so you can retry
            api("editMessageReplyMarkup", chat_id=chat, message_id=mid,
                reply_markup=json.dumps(msg["reply_markup"]))


def handle_message(m):
    chat = str(m.get("chat", {}).get("id", ""))
    if chat != OWNER:
        return
    found = re.findall(r"https?://\S+", m.get("text", ""))
    if not found:
        if m.get("text"):
            tg_say(chat, "Send me a news link and I will make a card 🙂")
        return
    url = found[0].rstrip(").,>]")
    tg_say(chat, "⏳ Making the card...")
    try:
        title, body = read_article(url)
        card = prepare(title, body, url)
        card["url"] = clean_url(url)
        if not card["has_photo"]:
            tg_say(chat, "⚠️ No image found for this link - plain background used.")
        tg_preview(chat, card)
    except Exception as ex:
        tg_say(chat, f"Failed: {ex}")


def main():
    """Listen to Telegram for RUN_SECONDS so buttons react within seconds."""
    offset, done = 0, set()
    end = time.time() + RUN_SECONDS
    while True:
        wait = int(max(0, min(25, end - time.time())))
        try:
            r = requests.get(
                f"{_tg()}/getUpdates",
                params={"offset": offset, "timeout": wait,
                        "allowed_updates": json.dumps(["message", "callback_query"])},
                timeout=wait + 20,
            ).json()
        except Exception as e:
            print("getUpdates error:", e)
            time.sleep(3)
            r = {}
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            try:
                cb = u.get("callback_query")
                if cb:
                    if str(cb["from"]["id"]) == OWNER:
                        handle_button(cb, done)
                else:
                    handle_message(u.get("message") or {})
            except Exception as ex:
                print("update error:", ex)
        if time.time() >= end:
            break
    # confirm the last updates so they are never handled twice
    requests.get(f"{_tg()}/getUpdates", params={"offset": offset, "timeout": 0}, timeout=30)


if __name__ == "__main__":
    main()
