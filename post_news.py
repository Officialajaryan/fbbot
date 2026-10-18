import os, re, random
import feedparser
from common import load_state, save_state, publish, prepare, post_card, tg_preview

POSTS_PER_RUN = 1
MAX_TRIES = 8  # how many articles to check per run

FEEDS = {
    # Singapore
    "CNA": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416",
    "Straits Times": "https://www.straitstimes.com/news/singapore/rss.xml",
    # Bangladesh
    "The Daily Star": "https://www.thedailystar.net/frontpage/rss.xml",
    "Dhaka Tribune": "https://www.dhakatribune.com/feed",
}


def clean(h):
    return re.sub(r"<[^>]+>", "", h or "").strip()


def main():
    state = load_state()
    pool = []
    for name, url in FEEDS.items():
        try:
            entries = feedparser.parse(url).entries[:10]
        except Exception as ex:
            print("Feed failed:", name, ex)
            continue
        print(name, len(entries), "items")
        for e in entries:
            if e.get("link") and e.link not in state["posted"]:
                pool.append((name, e))
    random.shuffle(pool)
    done = tries = 0
    for name, e in pool:
        if done >= POSTS_PER_RUN or tries >= MAX_TRIES:
            break
        tries += 1
        try:
            body = clean(e.get("summary", "")) or e.title
            card = prepare(e.title, body, e.link, require_relevant=True)
            if os.environ.get("APPROVE_DAILY") == "1":
                tg_preview(os.environ["TG_OWNER_ID"], card, state)
            else:
                post_card(card["path"], card["caption"], card["url"])
            state["posted"].append(e.link)
            done += 1
            print("Posted:", e.title)
        except Exception as ex:
            state["posted"].append(e.link)  # don't check it again
            print("Skipped:", e.title, "-", ex)
    save_state(state)


if __name__ == "__main__":
    main()
