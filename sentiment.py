"""
sentiment.py - Sentiment analysis for ICS Chat System
Uses TextBlob for offline, no-API sentiment detection.

Returns an emoji tag + label for every outgoing message.

Usage:
    from sentiment import get_sentiment
    tag, label = get_sentiment("I love this!")
    # tag   -> "positive"
    # label -> "😊 Positive"

Author: Sanaa
"""

try:
    from textblob import TextBlob
    TEXTBLOB_AVAILABLE = True
except ImportError:
    TEXTBLOB_AVAILABLE = False


# Thresholds: polarity is a float from -1.0 (very negative) to +1.0 (very positive)
POS_THRESHOLD =  0.1
NEG_THRESHOLD = -0.1

# (tag, display label) pairs — tag is used for Tkinter text coloring
SENTIMENTS = {
    "positive": "😊 Positive",
    "neutral":  "😐 Neutral",
    "negative": "😡 Negative",
}


def get_sentiment(message: str):
    """
    Analyze the sentiment of a message.

    Args:
        message: the raw text to analyze

    Returns:
        tuple: (tag: str, label: str)
            tag   — one of 'positive', 'neutral', 'negative'
            label — emoji + word for display, e.g. '😊 Positive'
            If TextBlob is unavailable, returns ('neutral', '')
    """
    if not TEXTBLOB_AVAILABLE or not message.strip():
        return ("neutral", "")

    polarity = TextBlob(message).sentiment.polarity

    if polarity > POS_THRESHOLD:
        tag = "positive"
    elif polarity < NEG_THRESHOLD:
        tag = "negative"
    else:
        tag = "neutral"

    return (tag, SENTIMENTS[tag])


# ==============================================================================
# Quick test
# ==============================================================================
if __name__ == "__main__":
    tests = [
        "I love this chat system, it's amazing!",
        "This is okay I guess",
        "I hate bugs so much, this is terrible",
        "@bot can you help me?",
        "",
    ]
    for t in tests:
        tag, label = get_sentiment(t)
        print(f"[{label or 'N/A':15}]  {t!r}")
