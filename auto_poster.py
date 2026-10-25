import os
import random
import requests

# A sample content bank for The Drowned Concordat promotion
# We can expand this with direct quotes, lore drops, and direct links to Amazon.
POSTS = [
    (
        "Behind the sea walls of the European Delta, the food is grown in vats "
        "and the truth is rationed. Dive into Book One of The Drowned Concordat: "
        "The Rise of the Covenant. Available now on Amazon! 🌊📚 "
        "https://www.amazon.com/dp/B0HJLRN48X"
    ),
    (
        "“The water took the world it knew. What's left feeds five hundred million people — "
        "and none of it grew in soil.” Experience the hard sci-fi dystopian world of "
        "Hamish C. Rannoch. Grab your copy: https://thedrownedconcordat.com/"
    ),
    (
        "Dr. Elara Di Canti built the chemistry that keeps a drowned hemisphere fed, "
        "but what does it cost the soul? Discover The Drowned Concordat today. "
        "🔗 https://www.amazon.com/dp/B0HJLRN48X"
    ),
]

def get_random_post():
    """Selects a random promotional post from the bank."""
    return random.choice(POSTS)

def send_to_social_media(message):
    """
    Placeholder function for pushing updates. 
    We can hook this into specific platform Webhooks or APIs (like LinkedIn, Discord, or Mastodon)
    or integrate social media schedulers.
    """
    print(f"Attempting to publish: {message}")
    # Example: If using a webhook for automation tools like Make.com or Zapier:
    webhook_url = os.environ.get("SOCIAL_WEBHOOK_URL")
    if webhook_url:
        response = requests.post(webhook_url, json={"text": message}, timeout=30)
        print(f"Status: {response.status_code} {response.text[:200]}")
        response.raise_for_status()
    else:
        print("Webhook URL not found. Running in test mode.")

if __name__ == "__main__":
    post = get_random_post()
    send_to_social_media(post)
