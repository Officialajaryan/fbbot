"""Singapore news -> Bangla card -> posted straight to Facebook (no Telegram approval)."""
import os, re, random
import feedparser
from common import load_state, save_state, prepare, post_card, tg_say, tg_notify, NoImage, AIError, clean_url

POSTS_PER_RUN = 1
MAX_TRIES = 10  # how many articles to check per run

# Singapore only. A feed that fails or changes is skipped, the others still work.
FEEDS = {
    "CNA": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416",
    "Straits Times": "https://www.straitstimes.com/news/singapore/rss.xml",
    "Mothership": "https://mothership.sg/feed/",
    "TODAY": "https://www.todayonline.com/feed/singapore",
}

# Topics Bangladeshis in Singapore care about most -> these are tried first.
HOT = [
    "work pass", "s pass", "employment pass", "mom", "foreign worker", "migrant", "dormitory", "dormitories",
    "bangladesh", "bangladeshi", "salary", "wage", "pay ", "cpf", "bonus", "retrench", "layoff", "job",
    "hiring", "cost of living", "price", "gst", "grant", "subsid", "rebate", "voucher", "payout", "$",
    "remittance", "visa", "immigration", "ica", "mrt", "bus fare", "fare", "hdb", "rent", "medisave",
    "healthcare", "baby bonus", "children", "scam", "warning", "ban", "new rule", "fine",
]


def clean(h):
    return re.sub(r"<[^>]+>", "", h or "").strip()


def score(title, summary):
    t = f"{title} {summary}".lower()
    return sum(1 for k in HOT if k in t)


def main():
    state = load_state()
    pool = []
    for name, url in FEEDS.items():
        try:
            entries = feedparser.parse(url).entries[:12]
        except Exception as ex:
            print("Feed failed:", name, ex)
            continue
        print(name, len(entries), "items")
        for e in entries:
            if e.get("link") and e.link not in state["posted"]:
                pool.append((name, e))
    random.shuffle(pool)  # variety among equal scores
    pool.sort(key=lambda p: -score(p[1].get("title", ""), clean(p[1].get("summary", ""))))
    done = tries = ai_fails = 0
    last_err = ""
    for name, e in pool:
        if done >= POSTS_PER_RUN or tries >= MAX_TRIES:
            break
        tries += 1
        try:
            body = clean(e.get("summary", "")) or e.title
            card = prepare(e.title, body, e.link, require_relevant=True, require_image=True, source=name)
            post_id = post_card(card["path"], card["caption"], clean_url(e.link))
            state["posted"].append(e.link)
            done += 1
            print("Posted:", e.title, "->", post_id)
            # copy to Telegram, just to show you (no buttons, nothing to approve)
            owner, tok = os.environ.get("TG_OWNER_ID"), os.environ.get("TG_BOT_TOKEN")
            if owner and tok:
                tg_notify(owner, card["path"],
                          f"✅ Posted to Facebook\n\n{card['caption'].splitlines()[0]}\n\n"
                          f"Facebook: https://www.facebook.com/{post_id}\nSource: {clean_url(e.link)}")
        except AIError as ex:
            # the AI service failed, not the article: do NOT mark it as posted, and stop early if it keeps failing
            ai_fails += 1
            last_err = str(ex)
            print("AI error (article kept for next run):", e.title, "-", ex)
            if ai_fails >= 2:
                break
        except NoImage as ex:
            print("No image, trying next article:", e.title, "-", ex)  # not marked, may retry later
        except Exception as ex:
            state["posted"].append(e.link)  # don't check it again
            print("Skipped:", e.title, "-", ex)
    save_state(state)
    if done == 0:
        print("Nothing posted this run")
        owner = os.environ.get("TG_OWNER_ID")
        if owner and os.environ.get("TG_BOT_TOKEN"):
            try:
                if ai_fails:
                    tg_say(owner, "⚠️ Nothing posted: the AI step failed.\n" + last_err[:600])
                else:
                    tg_say(owner, "⚠️ News run finished but nothing was posted (no new Singapore article with a photo).")
            except Exception:
                pass


if __name__ == "__main__":
    main()
