import os
import requests

# Public base URL for the Instagram-sized images (1080x1350 JPEG) in this repo.
# Instagram can only fetch these while the repository is public.
IMAGE_BASE = (
    "https://raw.githubusercontent.com/somhairlemaccormick-collab/"
    "The-Drowned-Concordat-Promo/main/images/instagram/"
)

HASHTAGS = "#TheDrownedConcordat #HamishCRannoch #scifi #dystopian #bookstagram #scifibooks"

# Each post pairs a caption with an image from images/instagram/.
# Instagram captions don't make links clickable, so links are written out plainly.
POSTS = [
    {
        "image": "book1-rise-of-the-covenant-ebook-ig.jpg",
        "text": (
            "Behind the sea walls of the European Delta, the food is grown in vats "
            "and the truth is rationed. Dive into Book One of The Drowned Concordat: "
            "The Rise of the Covenant. Available now on Amazon! 🌊📚 "
            "https://www.amazon.com/dp/B0HJLRN48X"
        ),
    },
    {
        "image": "art-gelderland-station-1-ig.jpg",
        "text": (
            "“The water took the world it knew. What's left feeds five hundred million people — "
            "and none of it grew in soil.” Experience the hard sci-fi dystopian world of "
            "Hamish C. Rannoch. Grab your copy: https://thedrownedconcordat.com/"
        ),
    },
    {
        "image": "book1-rise-of-the-covenant-painted-ig.jpg",
        "text": (
            "Dr. Elara Di Canti built the chemistry that keeps a drowned hemisphere fed, "
            "but what does it cost the soul? Discover The Drowned Concordat today. "
            "🔗 https://www.amazon.com/dp/B0HJLRN48X"
        ),
    },
    {
        "image": "art-gelderland-station-2-ig.jpg",
        "text": (
            "In the Delta, real food is something only the richest have ever tasted. "
            "Everyone else lives on gel — dispensed as foam or lump, measured to the gram. "
            "The Drowned Concordat, Book One: The Rise of the Covenant. "
            "https://thedrownedconcordat.com/"
        ),
    },
    {
        "image": "series-all-six-covers-ig.jpg",
        "text": (
            "Three novels. Three novellas. One drowned world. "
            "The Drowned Concordat by Hamish C. Rannoch — start with Book One, "
            "The Rise of the Covenant. https://thedrownedconcordat.com/"
        ),
    },
    {
        "image": "novella-rounding-error-ebook-ig.jpg",
        "text": (
            "Five friends. One ration system. And an arithmetic gap nobody else noticed. "
            "The Rounding Error — a darkly comic novella from the world of The Drowned Concordat."
        ),
    },
    {
        "image": "novella-business-time-ebook-ig.jpg",
        "text": (
            "Greg just wants to get ahead in the Delta. How hard can it be? "
            "Business Time — a darkly comic novella from the world of The Drowned Concordat."
        ),
    },
    {
        "image": "novella-where-they-grew-ebook-ig.jpg",
        "text": (
            "A covert Enforcer unit is sent to count the faithful. "
            "The bodies tell them something the numbers can't. "
            "Where They Grew — a novella from the world of The Drowned Concordat."
        ),
    },
]


def pick_post():
    """Rotate through the posts in order, so nothing repeats until every post has run.

    GitHub sets GITHUB_RUN_NUMBER on each run; locally it falls back to the first post.
    """
    run = int(os.environ.get("GITHUB_RUN_NUMBER", "1"))
    return POSTS[(run - 1) % len(POSTS)]


def send_to_make(post):
    """Send the caption and public image link to the Make webhook."""
    payload = {
        "text": f"{post['text']}\n\n{HASHTAGS}",
        "image_url": IMAGE_BASE + post["image"],
    }
    print(f"Caption: {payload['text']}")
    print(f"Image: {payload['image_url']}")

    webhook_url = os.environ.get("SOCIAL_WEBHOOK_URL")
    if not webhook_url:
        print("Webhook URL not found. Running in test mode.")
        return

    response = requests.post(webhook_url, json=payload, timeout=30)
    print(f"Status: {response.status_code} {response.text[:200]}")
    response.raise_for_status()


if __name__ == "__main__":
    send_to_make(pick_post())
