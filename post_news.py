import os, re, random
import feedparser
from common import load_state, save_state, publish

POSTS_PER_RUN = 1
FEEDS = {
    "CNN": "http://rss.cnn.com/rss/edition.rss",
    "BBC": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}


def clean(h):
    return re.sub(r"<[^>]+>", "", h or "").strip()


def main():
    state = load_state()
    pool = []
    for name, url in FEEDS.items():
        for e in feedparser.parse(url).entries[:10]:
            if e.get("link") and e.link not in state["posted"]:
                pool.append((name, e))
    random.shuffle(pool)
    done = 0
    for name, e in pool:
        if done >= POSTS_PER_RUN:
            break
        try:
            publish(e.title, clean(e.get("summary", "")) or e.title, name, e.link)
            state["posted"].append(e.link)
            done += 1
            print("Posted:", e.title)
        except Exception as ex:
            print("Failed:", e.link, ex)
    save_state(state)


if __name__ == "__main__":
    main()
