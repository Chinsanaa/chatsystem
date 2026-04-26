"""
chat_bot_client.py - Chatbot module for ICS Chat System
Uses Ollama with phi3 model locally.

Features:
  - Basic 1-on-1 conversation
  - Conversation context (remembers previous messages)
  - Personality modes (friendly, formal, tutor)
  - Group chat @bot mention detection

Usage:
    from chat_bot_client import ChatBotClient
    bot = ChatBotClient()
    reply = bot.chat("Hello!")

Author: Sanaa
"""

import json
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# ==============================================================================
# Personality system prompts
# ==============================================================================
PERSONALITIES = {
    "friendly": (
        "You are a friendly, casual chat assistant in a student chat app. "
        "Keep replies short (1-3 sentences), warm, and conversational. "
        "Use simple language. Never use bullet points or headers."
    ),
    "formal": (
        "You are a professional, concise assistant. "
        "Respond formally and precisely. Keep replies to 1-3 sentences. "
        "No slang or casual language."
    ),
    "tutor": (
        "You are a helpful academic tutor. When asked questions, explain clearly "
        "and briefly (2-4 sentences). Encourage the student. "
        "If the topic is unclear, ask one clarifying question."
    ),
}

DEFAULT_PERSONALITY = "friendly"
MODEL_NAME = "phi3"
MAX_HISTORY = 20      # max messages kept in context window


# ==============================================================================
# ChatBotClient
# ==============================================================================
class ChatBotClient:
    def __init__(self, personality=DEFAULT_PERSONALITY, model=MODEL_NAME):
        """
        Args:
            personality: one of 'friendly', 'formal', 'tutor'
            model:       ollama model name (default: phi3)
        """
        self.model = model
        self.history = []           # list of {"role": ..., "content": ...}
        self.set_personality(personality)

    # --------------------------------------------------------------------------
    # Personality
    # --------------------------------------------------------------------------
    def set_personality(self, personality):
        """Switch personality. Clears conversation history."""
        if personality not in PERSONALITIES:
            personality = DEFAULT_PERSONALITY
        self.personality = personality
        self.system_prompt = PERSONALITIES[personality]
        self.history = []           # reset context on personality change

    def get_personality(self):
        return self.personality

    def list_personalities(self):
        return list(PERSONALITIES.keys())

    # --------------------------------------------------------------------------
    # Core chat method
    # --------------------------------------------------------------------------
    def chat(self, user_message, sender_name="user"):
        """
        Send a message to phi3 and get a reply.

        Args:
            user_message: the text to send
            sender_name:  who sent it (used in group chat context)

        Returns:
            str: the bot's reply, or an error string
        """
        if not OLLAMA_AVAILABLE:
            return "[Bot] Ollama is not installed. Run: pip install ollama"

        if not user_message.strip():
            return ""

        # Add to history (label with sender in group chat scenarios)
        content = f"{sender_name}: {user_message}" if sender_name != "user" else user_message
        self.history.append({"role": "user", "content": content})

        # Trim history to avoid exceeding context window
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[-MAX_HISTORY:]

        # Build messages list: system prompt + full history
        messages = [{"role": "system", "content": self.system_prompt}] + self.history

        try:
            response = ollama.chat(
                model=self.model,
                messages=messages
            )
            reply = response["message"]["content"].strip()
        except Exception as e:
            reply = f"[Bot error] {str(e)}"

        # Save bot reply to history for context
        self.history.append({"role": "assistant", "content": reply})

        return reply

    # --------------------------------------------------------------------------
    # Group chat: decide whether to respond
    # --------------------------------------------------------------------------
    def should_respond(self, message):
        """
        Returns True if the bot should respond to this group chat message.
        Triggers on: @bot (case-insensitive)
        """
        return "@bot" in message.lower()

    def extract_message(self, message):
        """
        Strip the @bot mention so phi3 only sees the actual question.
        Example: "@bot what is recursion?" -> "what is recursion?"
        """
        import re
        cleaned = re.sub(r"@bot", "", message, flags=re.IGNORECASE).strip()
        return cleaned if cleaned else message

    # --------------------------------------------------------------------------
    # Context management
    # --------------------------------------------------------------------------
    def clear_history(self):
        """Clear conversation history (keeps personality)."""
        self.history = []

    def get_history_length(self):
        return len(self.history)


# ==============================================================================
# Quick test (run this file directly to verify phi3 works)
# ==============================================================================
if __name__ == "__main__":
    print("Testing ChatBotClient with phi3...\n")
    bot = ChatBotClient(personality="friendly")

    test_messages = [
        "Hi! Who are you?",
        "What did I just ask you?",   # tests context
        "Can you switch to tutor mode?",
    ]

    for msg in test_messages:
        print(f"You: {msg}")
        reply = bot.chat(msg)
        print(f"Bot: {reply}\n")

    print("--- Testing @bot detection ---")
    print(bot.should_respond("@bot what is a socket?"))   # True
    print(bot.should_respond("hey everyone wassup"))       # False
    print(bot.extract_message("@bot explain threading"))
