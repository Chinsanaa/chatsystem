"""
chat_gui.py - Tkinter GUI for the ICS Chat System

Author: Sanaa
"""

import tkinter as tk
from tkinter import scrolledtext
import threading
import socket
import json
import argparse

from chat_utils import *
from chat_bot_client import ChatBotClient
from sentiment import get_sentiment

# ==============================================================================
# Friendly command reference (replaces raw terminal menu string)
# ==============================================================================
FRIENDLY_MENU = """
--- Available Commands ---
  chat <username>    Connect to a user        (e.g.  chat alice)
  who                See who is online
  time               Show current date/time
  bye                Leave current chat
  ? <word>           Search chat history      (e.g.  ? hello)
  p <number>         Get a Shakespeare sonnet (e.g.  p 18)
  q                  Quit the app
--------------------------
"""

# ==============================================================================
# Color palette
# ==============================================================================
BG_DARK    = "#1a1a2e"
BG_MID     = "#16213e"
BG_INPUT   = "#0f3460"
ACCENT     = "#e94560"
ACCENT2    = "#533483"
TEXT_MAIN  = "#eaeaea"
TEXT_DIM   = "#8892a4"
ONLINE_DOT = "#4ecca3"

# ==============================================================================
# GUIClient
# ==============================================================================
class GUIClient:
    def __init__(self, args):
        self.args    = args
        self.name    = ""
        self.state   = S_OFFLINE
        self.socket  = None

        self.bot          = ChatBotClient(personality="friendly")
        self.bot_mode     = False
        self.bot_thinking = False
        self.sentiment_on = True

        self.root = tk.Tk()
        self.root.title("ICS Chat")
        self.root.geometry("780x640")
        self.root.configure(bg=BG_DARK)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._cleanup_and_quit)

        self.build_login_screen()
        self.root.mainloop()

    # ==========================================================================
    # LOGIN SCREEN
    # ==========================================================================
    def build_login_screen(self):
        self.login_frame = tk.Frame(self.root, bg=BG_DARK)
        self.login_frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(self.login_frame, text="ICS", bg=BG_DARK,
                 fg=ACCENT, font=("Courier New", 48, "bold")).pack()
        tk.Label(self.login_frame, text="C H A T   S Y S T E M", bg=BG_DARK,
                 fg=TEXT_DIM, font=("Courier New", 12, "bold")).pack(pady=(0, 30))
        tk.Label(self.login_frame, text="USERNAME", bg=BG_DARK,
                 fg=TEXT_DIM, font=("Courier New", 9)).pack(anchor="w")

        self.name_entry = tk.Entry(
            self.login_frame, width=28, bg=BG_INPUT, fg=TEXT_MAIN,
            insertbackground=ACCENT, relief="flat",
            font=("Courier New", 14), bd=8
        )
        self.name_entry.pack(pady=(4, 20), ipady=6)
        self.name_entry.focus()
        self.name_entry.bind("<Return>", lambda e: self.attempt_login())

        self.login_status = tk.Label(self.login_frame, text="", bg=BG_DARK,
                                     fg=ACCENT, font=("Courier New", 9))
        self.login_status.pack(pady=(0, 10))

        tk.Button(
            self.login_frame, text="CONNECT", command=self.attempt_login,
            bg=ACCENT, fg="white", font=("Courier New", 11, "bold"),
            relief="flat", cursor="hand2", bd=0,
            activebackground=ACCENT2, activeforeground="white",
            padx=30, pady=10
        ).pack()

    def attempt_login(self):
        name = self.name_entry.get().strip()
        if not name:
            self.login_status.config(text="Please enter a username.")
            return

        self.login_status.config(text="Connecting...")
        self.root.update()

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            svr = SERVER if self.args.d is None else (self.args.d, CHAT_PORT)
            self.socket.connect(svr)
        except Exception:
            self.login_status.config(text="Cannot reach server. Is it running?")
            return

        mysend(self.socket, json.dumps({"action": "login", "name": name}))
        try:
            response = json.loads(myrecv(self.socket))
        except Exception:
            self.login_status.config(text="Server error during login.")
            return

        if response["status"] == "ok":
            self.name  = name
            self.state = S_LOGGEDIN
            self.login_frame.destroy()
            self.build_chat_screen()
            self.start_recv_thread()
        elif response["status"] == "duplicate":
            self.login_status.config(text="Username taken. Try another.")
        else:
            self.login_status.config(text="Login failed.")

    # ==========================================================================
    # CHAT SCREEN
    # ==========================================================================
    def build_chat_screen(self):
        self.root.title(f"ICS Chat  -  {self.name}")

        # Header bar
        header = tk.Frame(self.root, bg=BG_MID, height=54)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tk.Label(header, text="●", fg=ONLINE_DOT, bg=BG_MID,
                 font=("Courier New", 14)).pack(side="left", padx=(16, 6), pady=14)
        tk.Label(header, text=f"Logged in as  {self.name}",
                 fg=TEXT_MAIN, bg=BG_MID,
                 font=("Courier New", 11, "bold")).pack(side="left", pady=14)
        tk.Label(header, text="ICS CHAT", fg=ACCENT, bg=BG_MID,
                 font=("Courier New", 13, "bold")).pack(side="right", padx=20, pady=14)

        # Button bar
        btn_bar = tk.Frame(self.root, bg=BG_MID, height=38)
        btn_bar.pack(fill="x")
        btn_bar.pack_propagate(False)

        def _btn(label, cmd, fg="white"):
            tk.Button(
                btn_bar, text=label, command=cmd,
                bg=ACCENT2, fg=fg, font=("Courier New", 8, "bold"),
                relief="flat", cursor="hand2", bd=0,
                activebackground=ACCENT, activeforeground="white",
                padx=12, pady=4
            ).pack(side="left", padx=4, pady=5)

        _btn("WHO",      lambda: self.send_command("who"))
        _btn("TIME",     lambda: self.send_command("time"))
        _btn("HELP",     lambda: self.append_msg("system", FRIENDLY_MENU))
        _btn("BOT CHAT", self.toggle_bot_mode)

        self.sentiment_btn = tk.Button(
            btn_bar, text="SENTIMENT: ON", command=self.toggle_sentiment,
            bg=ACCENT2, fg=ONLINE_DOT, font=("Courier New", 8, "bold"),
            relief="flat", cursor="hand2", bd=0,
            activebackground=ACCENT, activeforeground="white",
            padx=12, pady=4
        )
        self.sentiment_btn.pack(side="left", padx=4, pady=5)

        tk.Button(
            btn_bar, text="DISCONNECT", command=self.disconnect_from_peer,
            bg=BG_DARK, fg=ACCENT, font=("Courier New", 8, "bold"),
            relief="flat", cursor="hand2", bd=0,
            activebackground=ACCENT, activeforeground="white",
            padx=12, pady=4
        ).pack(side="right", padx=8, pady=5)

        # Input area (packed early to guarantee visibility at the bottom)
        input_frame = tk.Frame(self.root, bg="#1e2a40", pady=10)
        input_frame.pack(fill="x", side="bottom")

        tk.Label(
            input_frame,
            text="Type a message or command  (e.g. /chat alice | /who | /time | /bye | /p 18)",
            bg="#1e2a40", fg=TEXT_DIM, font=("Courier New", 8)
        ).pack(anchor="w", padx=16, pady=(0, 4))

        input_row = tk.Frame(input_frame, bg="#1e2a40")
        input_row.pack(fill="x", padx=12, pady=(0, 6))

        # Use Entry for a clearly visible single-line composer across platforms.
        self.input_var = tk.StringVar()
        self.input_box = tk.Entry(
            input_row,
            textvariable=self.input_var,
            bg="#ffffff",
            fg="#111111",
            insertbackground="#111111",
            font=("Courier New", 13),
            relief="solid",
            bd=1
        )
        self.input_box.pack(side="left", fill="x", expand=True, ipady=7)
        self.input_box.bind("<Return>", self._on_input_enter)
        self.input_box.bind("<KP_Enter>", self._on_input_enter)

        tk.Button(
            input_row, text="SEND", command=self.send_message,
            bg=ACCENT, fg="white", font=("Courier New", 11, "bold"),
            relief="flat", cursor="hand2", bd=0,
            activebackground=ACCENT2, activeforeground="white",
            padx=24, pady=8
        ).pack(side="left", padx=(10, 0))

        # Middle frame: bot_bar (hidden) stacked above chat_area
        self.middle_frame = tk.Frame(self.root, bg=BG_DARK)
        self.middle_frame.pack(fill="both", expand=True)

        # Bot bar — created but not packed until bot mode ON
        self.bot_bar = tk.Frame(self.middle_frame, bg=ACCENT2, height=34)

        tk.Label(self.bot_bar, text="BOT PERSONALITY:", bg=ACCENT2,
                 fg=TEXT_MAIN, font=("Courier New", 8)).pack(side="left", padx=(10, 4), pady=7)

        self.personality_var = tk.StringVar(value="friendly")
        for p in self.bot.list_personalities():
            tk.Radiobutton(
                self.bot_bar, text=p.upper(), variable=self.personality_var,
                value=p, command=self.change_personality,
                bg=ACCENT2, fg=TEXT_MAIN, selectcolor=BG_DARK,
                activebackground=ACCENT2, activeforeground=TEXT_MAIN,
                font=("Courier New", 8), relief="flat"
            ).pack(side="left", padx=6)

        tk.Button(
            self.bot_bar, text="CLEAR HISTORY", command=self.clear_bot_history,
            bg=BG_DARK, fg=TEXT_DIM, font=("Courier New", 8),
            relief="flat", cursor="hand2", bd=0, padx=8
        ).pack(side="right", padx=10)

        # Chat display
        self.chat_area = scrolledtext.ScrolledText(
            self.middle_frame, state="normal", wrap="word",
            bg=BG_DARK, fg=TEXT_MAIN,
            font=("Courier New", 11),
            relief="flat", bd=0,
            padx=16, pady=12, spacing3=6
        )
        self.chat_area.pack(fill="both", expand=True)

        # Read-only: block keypresses, redirect clicks back to input box
        self.chat_area.bind("<Key>", lambda e: "break")
        self.chat_area.bind("<Button-1>",
                            lambda e: self.root.after_idle(self._refocus_input))

        # Text tags
        self.chat_area.tag_config("me",
            foreground=ACCENT, font=("Courier New", 11, "bold"),
            lmargin1=80, lmargin2=80, rmargin=10)
        self.chat_area.tag_config("peer",
            foreground=ONLINE_DOT, font=("Courier New", 11),
            lmargin1=10, lmargin2=10)
        self.chat_area.tag_config("system",
            foreground=TEXT_DIM, font=("Courier New", 10, "italic"),
            lmargin1=10, lmargin2=10)
        self.chat_area.tag_config("error",
            foreground=ACCENT, font=("Courier New", 10, "italic"),
            lmargin1=10)
        self.chat_area.tag_config("bot",
            foreground="#f5a623", font=("Courier New", 11, "bold"),
            lmargin1=10, lmargin2=10)
        self.chat_area.tag_config("positive",
            foreground=ONLINE_DOT, font=("Courier New", 9))
        self.chat_area.tag_config("negative",
            foreground=ACCENT, font=("Courier New", 9))
        self.chat_area.tag_config("neutral",
            foreground=TEXT_DIM, font=("Courier New", 9))

        self._refocus_input()
        self.append_msg("system", f"Welcome, {self.name}! You are logged in.")
        self.append_msg("system", FRIENDLY_MENU)

    def _refocus_input(self):
        """Safe focus redirect — guards against input_box not existing yet."""
        try:
            self.input_box.focus_force()
        except AttributeError:
            pass

    # ==========================================================================
    # SEND PATH
    # ==========================================================================
    def send_message(self):
        """Called by Enter key or SEND button."""
        text = self.input_var.get().strip()
        if not text:
            return
        self.input_var.set("")
        self._refocus_input()
        self._send_text(text)

    def _on_input_enter(self, _event):
        """Unified Enter handler for both main and numpad Enter keys."""
        self.send_message()
        return "break"

    def send_command(self, cmd):
        """Called by quick-command buttons (WHO, TIME, etc.)."""
        payload = self._parse_system_command(cmd)
        try:
            if payload:
                mysend(self.socket, json.dumps(payload))
            else:
                self._send_text(cmd)
        except Exception as e:
            self.append_msg("error", f"[command error: {e}]")
        self._refocus_input()

    def _translate_command(self, text):
        """Map friendly words to what ClientSM.proc() understands."""
        low = text.strip().lower()
        if low.startswith("chat "):
            return "c " + text.strip()[5:]
        if low.startswith("connect "):
            return "c " + text.strip()[8:]
        return text

    def _parse_system_command(self, text):
        """
        Parse command text into a server action payload.
        Supports both slash and non-slash forms:
          /time, /who, /chat bob, /? hello, /p 18, /bye
          time, who, chat bob, ? hello, p 18, bye
        Returns dict payload or None.
        """
        cmd = text.strip()
        if not cmd:
            return None
        if cmd.startswith("/"):
            cmd = cmd[1:].strip()
        low = cmd.lower()

        if low == "time":
            return {"action": "time"}
        if low == "who":
            return {"action": "list"}
        if low.startswith("chat "):
            peer = cmd[5:].strip()
            return {"action": "connect", "target": peer} if peer else None
        if low.startswith("connect "):
            peer = cmd[8:].strip()
            return {"action": "connect", "target": peer} if peer else None
        if low == "bye":
            return {"action": "disconnect"}
        if cmd.startswith("?"):
            term = cmd[1:].strip()
            return {"action": "search", "target": term} if term else None
        if low.startswith("p "):
            poem_idx = cmd[2:].strip()
            if poem_idx.isdigit():
                return {"action": "poem", "target": poem_idx}
        return None

    def _send_text(self, text):
        """Core send logic — always runs on the main GUI thread."""
        if not text:
            return
        if self.socket is None:
            self.append_msg("error", "Not connected. Please log in first.")
            return
        payload = self._parse_system_command(text)

        # q/quit -> clean shutdown
        if text.strip().lower() in ("q", "/q", "quit", "/quit"):
            self._cleanup_and_quit()
            return

        # Bot mode: messages go to phi3, not server
        if self.bot_mode:
            if text.lower() == "exit bot":
                self.toggle_bot_mode()
                return
            self.append_msg("me", f"[{self.name}]: {text}")
            def _thinking():
                self.chat_area.insert("end", "Bot is thinking...\n",
                                      ("bot", "bot_thinking"))
                self.chat_area.see("end")
            self.root.after(0, _thinking)
            threading.Thread(target=self._get_bot_reply,
                             args=(text,), daemon=True).start()
            return

        # Show outgoing message bubble only while chatting
        if self.state == S_CHATTING:
            if payload and payload.get("action") == "disconnect":
                try:
                    mysend(self.socket, json.dumps(payload))
                    self.append_msg("system", "You left the chat.")
                except Exception as e:
                    self.append_msg("error", f"[send error: {e}]")
                self.state = S_LOGGEDIN
                self.append_msg("system", FRIENDLY_MENU)
                return

            # Allow system commands while chatting (slash or legacy style).
            if payload and payload.get("action") != "connect":
                try:
                    mysend(self.socket, json.dumps(payload))
                except Exception as e:
                    self.append_msg("error", f"[command error: {e}]")
                return

            self.append_msg("me", f"[{self.name}]: {text}")
            if self.sentiment_on:
                stag, slabel = get_sentiment(text)
                if slabel:
                    self.append_sentiment(stag, slabel)
            try:
                mysend(self.socket, json.dumps(
                    {"action": "exchange", "from": f"[{self.name}]", "message": text}))
            except Exception as e:
                self.append_msg("error", f"[send error: {e}]")
            return

        # Logged-in command handling (non-chatting state)
        cmd_text = self._translate_command(text).strip()
        low = cmd_text.lower()
        if not payload:
            payload = self._parse_system_command(cmd_text)

        try:
            if payload:
                mysend(self.socket, json.dumps(payload))
            elif low == "bye":
                # Not in chat currently; keep behavior user-friendly.
                self.append_msg("system", "You are not in a chat.")
            else:
                self.append_msg("system",
                    "You are not in a chat yet. Use  chat <username>  first.")
                self.append_msg("system", FRIENDLY_MENU)
        except Exception as e:
            self.append_msg("error", f"[command error: {e}]")

    def disconnect_from_peer(self):
        """DISCONNECT button — only valid while in S_CHATTING."""
        if self.state != S_CHATTING:
            self.append_msg("system",
                "You are not in a chat. Use  chat <username>  to connect.")
            return
        self._send_text("bye")

    # ==========================================================================
    # RECEIVE PATH (background thread)
    # ==========================================================================
    def start_recv_thread(self):
        threading.Thread(target=self.recv_loop, daemon=True).start()

    def recv_loop(self):
        """Poll socket for server messages. Runs in background thread."""
        import select as sel
        while self.state != S_OFFLINE:
            try:
                read, _, _ = sel.select([self.socket], [], [], 0.2)
                if self.socket not in read:
                    continue

                peer_msg = myrecv(self.socket)
                if not peer_msg:
                    break  # server closed connection

                try:
                    parsed = json.loads(peer_msg)
                except json.JSONDecodeError:
                    self.append_msg("error", f"[bad server message: {peer_msg}]")
                    continue

                action = parsed.get("action", "")

                if action == "exchange":
                    # Incoming chat message — display directly, no SM needed
                    sender  = parsed.get("from", "peer")
                    message = parsed.get("message", "")
                    self.append_msg("peer", f"{sender}: {message}")
                    if self.bot.should_respond(message):
                        clean = self.bot.extract_message(message)
                        threading.Thread(target=self._broadcast_bot_reply,
                                         args=(clean, sender), daemon=True).start()

                elif action == "disconnect":
                    # Peer left the chat
                    msg = parsed.get("msg", "Your chat partner disconnected.")
                    self.append_msg("system", msg)
                    self.state = S_LOGGEDIN
                    self.append_msg("system", FRIENDLY_MENU)

                elif action == "connect":
                    status = parsed.get("status", "")
                    if status == "request":
                        requester = parsed.get("from", "unknown")
                        self.state = S_CHATTING
                        self.append_msg("system", f"You are connected with {requester}")
                        self.append_msg("system", f"Connect to {requester}. Chat away!")
                        self.append_msg("system", "-----------------------------------")
                    elif status == "success":
                        self.state = S_CHATTING
                        self.append_msg("system", "Connection successful. Chat away!")
                        self.append_msg("system", "-----------------------------------")
                    elif status == "busy":
                        self.append_msg("system", "User is busy. Please try again later.")
                    elif status == "self":
                        self.append_msg("system", "Cannot talk to yourself.")
                    else:
                        self.append_msg("system", "User is not online, try again later.")

                elif action == "time":
                    self.append_msg("system", "Time is: " + parsed.get("results", ""))
                elif action == "list":
                    self.append_msg("system", "Here are all the users in the system:")
                    self.append_msg("system", parsed.get("results", ""))
                elif action == "poem":
                    poem = parsed.get("results", "")
                    self.append_msg("system", poem if poem else "Sonnet not found")
                elif action == "search":
                    results = (parsed.get("results", "") or "").strip()
                    self.append_msg("system", results if results else "No matches found.")
                elif action == "error":
                    reason = parsed.get("reason", "unknown server error")
                    self.append_msg("error", f"[server error: {reason}]")
                else:
                    self.append_msg("error", f"[unknown server action: {action}]")

            except OSError:
                break
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                self.append_msg("error", f"[recv error: {e}]")
            except Exception:
                self.append_msg("error", "[recv error: unexpected internal error]")

        self.append_msg("error", "Disconnected from server.")

    # ==========================================================================
    # DISPLAY HELPERS
    # ==========================================================================
    def append_msg(self, tag, text):
        """Thread-safe message insert — scheduled on GUI thread via after()."""
        def _insert():
            self.chat_area.insert("end", text + "\n", tag)
            self.chat_area.see("end")
        self.root.after(0, _insert)

    def append_sentiment(self, tag, label):
        def _insert():
            self.chat_area.insert("end", " " * 36 + label + "\n", tag)
            self.chat_area.see("end")
        self.root.after(0, _insert)

    # ==========================================================================
    # BOT
    # ==========================================================================
    def toggle_bot_mode(self):
        self.bot_mode = not self.bot_mode
        if self.bot_mode:
            self.bot_bar.pack(fill="x", side="top", before=self.chat_area)
            self.bot.clear_history()
            self.append_msg("bot",
                "[Bot mode ON] I'm your assistant. Type 'exit bot' to go back.\n"
                f"Personality: {self.bot.get_personality().upper()}")
        else:
            self.bot_bar.pack_forget()
            self.append_msg("system", "[Bot mode OFF] Back to normal chat.")

    def change_personality(self):
        p = self.personality_var.get()
        self.bot.set_personality(p)
        self.append_msg("bot", f"[Bot] Personality -> {p.upper()}. History cleared.")

    def clear_bot_history(self):
        self.bot.clear_history()
        self.append_msg("bot", "[Bot] History cleared.")

    def _get_bot_reply(self, text):
        reply = self.bot.chat(text, sender_name=self.name)
        def _show():
            try:
                rng = self.chat_area.tag_nextrange("bot_thinking", "1.0")
                if rng:
                    self.chat_area.delete(rng[0], rng[1])
                    self.chat_area.tag_delete("bot_thinking")
            except Exception:
                pass
            self.append_msg("bot", f"[Bot ({self.bot.get_personality()})]: {reply}")
        self.root.after(0, _show)

    def _broadcast_bot_reply(self, message, sender):
        reply = self.bot.chat(message, sender_name=sender)
        if self.state == S_CHATTING:
            self.root.after(0, lambda: self.append_msg("bot", f"[Bot]: {reply}"))
            try:
                mysend(self.socket, json.dumps({
                    "action": "exchange",
                    "from": "[Bot]",
                    "message": f"@bot replies: {reply}"
                }))
            except Exception:
                pass

    # ==========================================================================
    # SENTIMENT
    # ==========================================================================
    def toggle_sentiment(self):
        self.sentiment_on = not self.sentiment_on
        status = "ON"       if self.sentiment_on else "OFF"
        color  = ONLINE_DOT if self.sentiment_on else TEXT_DIM
        self.sentiment_btn.config(text=f"SENTIMENT: {status}", fg=color)
        self.append_msg("system", f"[Sentiment analysis {status}]")

    # ==========================================================================
    # CLEANUP
    # ==========================================================================
    def _cleanup_and_quit(self):
        try:
            if self.socket:
                if self.state == S_CHATTING:
                    try:
                        mysend(self.socket, json.dumps({"action": "disconnect"}))
                    except Exception:
                        pass
                self.state = S_OFFLINE
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                self.socket.close()
        except Exception:
            pass
        self.root.destroy()


# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="ICS Chat GUI Client")
    parser.add_argument("-d", type=str, default=None, help="Server IP address")
    args = parser.parse_args()
    GUIClient(args)


if __name__ == "__main__":
    main()