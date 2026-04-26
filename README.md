# ICDS Chat System — Final Project

## Team
- Sanaa (GUI, Chatbot, Sentiment)
- Bella (Game, Leaderboard)
- Zen (Login, Emoji)

## How to Run
1. Start the server: `python3 chat_server.py`
2. Start a client: `python3 chat_gui.py`
3. To connect to a remote server: `python3 chat_gui.py -d <server-ip>`

## Install Dependencies
pip install ollama textblob

## Ollama Setup
ollama pull phi3

## Branch Rules
- NEVER commit directly to main
- Sanaa works on: sanaa branch
- Teammate A works on: teammate-a branch
- Teammate B works on: teammate-b branch
- Sanaa merges everything into main before submission

## Files — Do Not Rename
chat_server.py, chat_client_class.py, chat_utils.py,
client_state_machine.py, chat_group.py, indexer.py

## Files Per Person
| File | Owner |
|------|-------|
| chat_gui.py | Sanaa + Teammate B |
| chat_bot_client.py | Sanaa |
| sentiment.py | Sanaa |
| snake.py | Teammate A |
| scoreboard.py | Teammate A |
| tictactoe.py | Teammate A (bonus) |
