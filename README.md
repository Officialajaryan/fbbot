# Facebook Bangla News Bot

## 1. GitHub
- Create a new **public** repo (public = unlimited free Actions; secrets stay private) and upload all these files.
- Settings → Secrets and variables → Actions → add:
  - DEEPSEEK_API_KEY   (platform.deepseek.com) — or ANTHROPIC_API_KEY instead
  - FB_PAGE_ID
  - FB_PAGE_TOKEN      (long-lived Page token)
  - PAGE_NAME          (logo text on card, e.g. ARYAN)
  - FB_PAGE_URL        (your page link, used for the QR code)
  - TG_BOT_TOKEN       (from @BotFather)
  - TG_OWNER_ID        (your number from @userinfobot)

## 2. Facebook token
- developers.facebook.com → Create app (Business) → add Facebook Login.
- Graph API Explorer → select your app → permissions:
  pages_manage_posts, pages_manage_engagement, pages_read_engagement, pages_show_list
- Generate user token → exchange for long-lived → call /me/accounts → copy your Page's access_token (never expires if from a long-lived user token).
- Page ID is in the same /me/accounts result.

## 3. Test
- Actions tab → daily-news → Run workflow. A card should appear on your page.

## Schedule (Bangladesh time)
- News: 8am, 11am, 2pm, 5pm, 8pm (edit cron in daily-news.yml)
- Link bot: checks Telegram every ~10 min (GitHub may delay a few minutes)
- Comments: every ~20 min

Send any news link to your Telegram bot → card posted + source comment.
