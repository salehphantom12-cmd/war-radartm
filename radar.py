import os
import requests
import feedparser
import hashlib

# =====================
# Telegram Config
# =====================

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


# =====================
# News Sources
# =====================

RSS_FEEDS = [
    "https://www.farsnews.ir/rss",
    "https://www.irna.ir/rss",
    "https://www.tasnimnews.com/fa/rss",
]


KEYWORDS = [
    "جنگ",
    "حمله",
    "آمریکا",
    "ایران",
    "اسرائیل",
    "موشک",
    "تهدید",
]


# جلوگیری از ارسال تکراری
sent_file = "sent.txt"


def load_sent():
    if os.path.exists(sent_file):
        return open(sent_file).read().splitlines()
    return []


def save_sent(items):
    with open(sent_file, "w") as f:
        f.write("\n".join(items))


# =====================
# Telegram Sender
# =====================

def send_telegram(message):
    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    requests.post(url, data=data)



# =====================
# Radar
# =====================

def main():

    sent = load_sent()
    new_sent = sent.copy()

    for feed_url in RSS_FEEDS:

        feed = feedparser.parse(feed_url)

        for item in feed.entries[:10]:

            title = item.title

            if title in sent:
                continue


            for word in KEYWORDS:

                if word in title:

                    msg = f"""
🚨 هشدار رادار جنگ

{title}

{item.link}
"""

                    send_telegram(msg)

                    new_sent.append(title)
                    break


    save_sent(new_sent)



if __name__ == "__main__":
    main()
