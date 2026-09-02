import os
import json
import hashlib
import time
from datetime import datetime, timezone

import requests
import feedparser


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

LLM_BASE_URL = os.environ.get(
    "LLM_BASE_URL",
    "http://127.0.0.1:20128/v1"
).rstrip("/")

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "saleh")

MAX_ITEMS_PER_SOURCE = 10
REQUEST_TIMEOUT = 20


# ============================================================
# NEWS SOURCES
# ============================================================

RSS_SOURCES = {
    "فارس": "https://www.farsnews.ir/rss",
    "ایرنا": "https://www.irna.ir/rss-homepage",
    "صداوسیما": "https://www.irib-news.ir/fa/rss/allnews",
    "جماران": "https://www.jamaran.news/feeds",
    "تسنیم": "https://www.tasnimnews.ir/fa/rss",
}


# ============================================================
# LOCAL STATE
# ============================================================

STATE_FILE = "radar_state.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"seen": []}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seen": []}


def save_state(state):
    # فقط آخرین 500 خبر را نگه می‌داریم
    state["seen"] = state.get("seen", [])[-500:]

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================
# HELPERS
# ============================================================

def normalize(text):
    if not text:
        return ""

    return (
        text.replace("ي", "ی")
            .replace("ى", "ی")
            .replace("ك", "ک")
            .replace("\u200c", " ")
            .strip()
    )


def make_id(title, link):
    raw = normalize(title) + "|" + (link or "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================
# RSS
# ============================================================

def fetch_feed(source, url):
    print(f"[RSS] {source}: {url}")

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": "WarRadar/1.0 (+news-monitor)"
            }
        )

        response.raise_for_status()

        feed = feedparser.parse(response.content)

        results = []

        for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:

            title = normalize(
                entry.get("title", "")
            )

            link = entry.get("link", "")

            summary = normalize(
                entry.get("summary", "")
            )

            published = (
                entry.get("published", "")
                or entry.get("updated", "")
            )

            if not title:
                continue

            results.append({
                "source": source,
                "title": title,
                "summary": summary,
                "link": link,
                "published": published
            })

        print(f"[RSS] {source}: {len(results)} items")

        return results

    except Exception as e:
        print(f"[ERROR] {source}: {e}")
        return []


def collect_news():
    all_news = []

    for source, url in RSS_SOURCES.items():
        all_news.extend(
            fetch_feed(source, url)
        )

    return all_news


# ============================================================
# LLM
# ============================================================

def analyze_news(news):

    prompt = f"""
تو تحلیلگر یک سیستم پایش اخبار به نام War Radar هستی.

خبر زیر را بررسی کن.

هدف:
تشخیص خبرهای مهم و واقعی درباره درگیری‌های نظامی و تهدیدهای مستقیم،
خصوصاً میان ایران، آمریکا و سایر بازیگران منطقه.

خبر:
منبع: {news["source"]}
عنوان: {news["title"]}
خلاصه: {news["summary"]}
لینک: {news["link"]}

قوانین:

1. خبرهای قدیمی را مهم تلقی نکن.
2. تحلیل، نظر شخصی، یادداشت و پیش‌بینی را به عنوان حمله واقعی ثبت نکن.
3. شایعه و ادعای تأییدنشده را حمله قطعی حساب نکن.
4. اگر خبر فقط درباره آمادگی یا تهدید است، آن را از حمله واقعی جدا کن.
5. اگر چند رسانه یک رویداد واحد را گزارش کنند، رویداد را تکراری در نظر بگیر.
6. فقط وقتی اهمیت بالا است که خبر واقعاً مربوط به یک رویداد نظامی/امنیتی مهم باشد.

سطوح:

critical:
حمله نظامی تأییدشده یا شروع عملیات مهم

severe:
تهدید مستقیم، اعلام حمله، دستور عملیات یا آماده‌باش بسیار مهم

warning:
تحرک نظامی مهم یا افزایش جدی تنش

normal:
خبر عادی، تحلیل، نظر، خبر قدیمی یا غیرمرتبط

فقط JSON معتبر برگردان:

{{
  "important": true,
  "severity": "critical",
  "event_type": "attack",
  "confidence": 0.95,
  "summary": "خلاصه کوتاه فارسی",
  "reason": "دلیل اهمیت خبر",
  "is_rumor": false
}}
"""

    url = f"{LLM_BASE_URL}/chat/completions"

    headers = {
        "Content-Type": "application/json"
    }

    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful Persian news verification "
                    "and conflict-event classification system."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.1,
        "max_tokens": 500
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=60
        )

        response.raise_for_status()

        data = response.json()

        text = data["choices"][0]["message"]["content"]

        # اگر مدل ```json برگرداند
        text = text.strip()

        if text.startswith("```"):
            text = text.replace("```json", "")
            text = text.replace("```", "")
            text = text.strip()

        return json.loads(text)

    except Exception as e:

        print("[LLM ERROR]", e)

        return {
            "important": False,
            "severity": "normal",
            "event_type": "unknown",
            "confidence": 0,
            "summary": "",
            "reason": "",
            "is_rumor": True
        }


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=20
        )

        response.raise_for_status()

        print("[TELEGRAM] Alert sent")

    except Exception as e:

        print("[TELEGRAM ERROR]", e)


# ============================================================
# FORMAT ALERT
# ============================================================

def format_alert(news, analysis):

    severity = analysis.get("severity", "warning")

    icons = {
        "critical": "🔴",
        "severe": "🟠",
        "warning": "🟡",
        "normal": "⚪"
    }

    icon = icons.get(
        severity,
        "🟡"
    )

    confidence = analysis.get(
        "confidence",
        0
    )

    confidence_percent = int(
        float(confidence) * 100
    )

    return f"""
{icon} WAR RADAR

سطح: {severity.upper()}

📰 {news["title"]}

📡 منبع: {news["source"]}

🧠 تحلیل:
{analysis.get("summary", "")}

📌 دلیل:
{analysis.get("reason", "")}

🎯 اطمینان: {confidence_percent}%

🔗 {news["link"]}
""".strip()


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("WAR RADAR START")
    print(datetime.now(timezone.utc).isoformat())
    print("=" * 60)

    state = load_state()

    seen = set(
        state.get("seen", [])
    )

    news_items = collect_news()

    print(
        f"[INFO] Total collected: {len(news_items)}"
    )

    new_count = 0
    alert_count = 0

    for news in news_items:

        news_id = make_id(
            news["title"],
            news["link"]
        )

        if news_id in seen:
            continue

        new_count += 1

        print(
            f"\n[NEW] {news['source']} | "
            f"{news['title']}"
        )

        analysis = analyze_news(news)

        print(
            "[ANALYSIS]",
            json.dumps(
                analysis,
                ensure_ascii=False
            )
        )

        # خبر را دیده‌شده علامت بزن
        seen.add(news_id)

        important = analysis.get(
            "important",
            False
        )

        rumor = analysis.get(
            "is_rumor",
            True
        )

        severity = analysis.get(
            "severity",
            "normal"
        )

        confidence = float(
            analysis.get(
                "confidence",
                0
            )
        )

        # فقط خبرهای مهم و با اطمینان مناسب ارسال شوند
        if (
            important
            and not rumor
            and severity != "normal"
            and confidence >= 0.70
        ):

            alert = format_alert(
                news,
                analysis
            )

            send_telegram(alert)

            alert_count += 1

        # جلوگیری از فشار زیاد روی API
        time.sleep(1)

    state["seen"] = list(seen)

    save_state(state)

    print("\n" + "=" * 60)
    print("WAR RADAR FINISHED")
    print(f"New news: {new_count}")
    print(f"Alerts: {alert_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
