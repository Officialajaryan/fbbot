import requests
from common import GRAPH, PAGE_ID, TOKEN, load_state, save_state, ask_claude

SYSTEM = (
    "You manage a Bangla news Facebook page for Bangladeshis living in Singapore. "
    "Write a short, polite, friendly reply (max 2 sentences) in the same language as the comment "
    "(Bangla comments get Bangla replies). Do not argue, do not give political opinions, "
    "do not invent facts. If the comment asks about legal, visa, passport, NID or work-pass "
    "rules, do not give specific advice: politely say to check the official website or contact "
    "the relevant office. If the comment is only emojis, abusive, spam, or a link, "
    "answer exactly: SKIP"
)


def get(path, **params):
    params["access_token"] = TOKEN
    r = requests.get(f"{GRAPH}/{path}", params=params, timeout=30)
    if not r.ok:
        print("FACEBOOK ERROR:", r.status_code, r.text[:400])
        r.raise_for_status()
    return r.json()


def main():
    state = load_state()
    posts = get(f"{PAGE_ID}/posts", limit=10, fields="id,message").get("data", [])
    print("Posts found:", len(posts))
    n = 0
    for p in posts:
        cs = get(f"{p['id']}/comments", limit=50, fields="id,message,from",
                 filter="toplevel").get("data", [])
        print("Post", p["id"], "-> comments:", len(cs))
        for c in cs:
            if c["id"] in state["replied"]:
                continue
            if n >= 15:
                break
            if c.get("from", {}).get("id") == PAGE_ID:
                state["replied"].append(c["id"])
                continue
            msg = c.get("message", "").strip()
            state["replied"].append(c["id"])
            if not msg:
                print("Skipped (no text)")
                continue
            reply = ask_claude(
                SYSTEM, f"Post: {p.get('message', '')[:300]}\nComment: {msg}", 200)
            if reply.upper().startswith("SKIP"):
                print("Skipped by AI:", msg[:40])
                continue
            requests.post(f"{GRAPH}/{c['id']}/comments",
                          data={"message": reply, "access_token": TOKEN},
                          timeout=30).raise_for_status()
            n += 1
            print("Replied to:", msg[:40])
    save_state(state)


if __name__ == "__main__":
    main()
