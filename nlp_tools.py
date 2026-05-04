"""
nlp_tools.py

Simple NLP utilities for Final Project:
- extract_keywords_yake(messages)
- summarize_with_sumy(messages)

Dependencies:
    pip install yake sumy nltk
"""

from typing import List
import yake
import nltk

# Ensure NLTK tokenizer resources exist for Sumy
for resource in ("punkt", "punkt_tab"):
    try:
        nltk.data.find(f"tokenizers/{resource}")
    except LookupError:
        try:
            nltk.download(resource)
        except Exception:
            pass

from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.luhn import LuhnSummarizer


# ---------------------------
# Keyword extraction with YAKE
# ---------------------------

def extract_keywords_yake(messages: List[str], top_k: int = 5) -> List[str]:
    """
    Extract top_k keywords from a list of chat messages using YAKE.
    """
    if not messages:
        return []

    text = "\n".join(messages)

    kw_extractor = yake.KeywordExtractor(
        lan="en",
        n=1,
        top=top_k,
        features=None,
    )

    keywords = kw_extractor.extract_keywords(text)
    keywords_sorted = sorted(keywords, key=lambda x: x[1])  # lower score = more relevant
    return [kw for kw, score in keywords_sorted[:top_k]]


# ---------------------------
# Summarization with Sumy
# ---------------------------

def summarize_with_sumy(messages: List[str], sentences_count: int = 3) -> List[str]:
    """
    Generate a short extractive summary from chat messages using Sumy (Luhn).
    """
    if not messages:
        return []

    text = "\n".join(messages)

    parser = PlaintextParser.from_string(text, Tokenizer("english"))
    summarizer = LuhnSummarizer()

    summary_sentences = summarizer(parser.document, sentences_count)
    return [str(sentence) for sentence in summary_sentences]

# ---------------------------
# Small demo (optional)
# ---------------------------

if __name__ == "__main__":
    demo_history = [
        "Hi everyone, welcome to the chat system project discussion.",
        "We need to design the client-server architecture first.",
        "I think we should implement the GUI using Tkinter.",
        "What do you think about adding an AI chatbot feature to the system?",
        "We can also support file transfer and emojis as extra features.",
        "Later we should write clear documentation and a project guideline for users.",
    ]

    print("=== /keywords demo ===")
    print(extract_keywords_yake(demo_history))

    print("\n=== /summary demo ===")
    print(summarize_with_sumy(demo_history))