import requests
from common import GRAPH, PAGE_ID, TOKEN, load_state, save_state, ask_claude

SYSTEM = (
    "You manage a Bangla news Facebook page. Write a short, polite, friendly reply "
    "(max 2 sentences) in the same language as the comment. Do not argue, do not "
    "give political opinions, do not add new facts. If the comment is abusive, spam, "
    "a link, or needs no reply, answer exactly: SKIP"
)


def get(path, **params):
    params["access_token"] = TOKEN
    r = requests.get(f"{GRAPH}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    state = load_state()
    posts = get(f"{PAGE_ID}/posts", limit=10, fields="id,message").get("data", [])
    n = 0
    for p in posts:
        cs = get(f"{p['id']}/comments", limit=50, fields="id,message,from", filter="toplevel").get("data", [])
        for c in cs:
            if c["id"] in state["replied"] or n >= 15:
                continue
            if c.get("from", {}).get("id") == PAGE_ID:
                state["replied"].append(c["id"])
                continue
            msg = c.get("message", "").strip()
            state["replied"].append(c["id"])
            if not msg:
                continue
            reply = ask_claude(SYSTEM, f"Post: {p.get('message','')[:300]}\nComment: {msg}", 200)
            if reply.upper().startswith("SKIP"):
                continue
            requests.post(f"{GRAPH}/{c['id']}/comments",
                          data={"message": reply, "access_token": TOKEN}, timeout=30).raise_for_status()
            n += 1
            print("Replied:", msg[:40])
    save_state(state)


if __name__ == "__main__":
    main()
