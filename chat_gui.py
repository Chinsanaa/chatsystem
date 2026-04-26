"""
chat_gui.py - Tkinter GUI for the ICS Chat System
Wraps chat_client_class.py and client_state_machine.py without modifying them.

Author: Sanaa
"""

import tkinter as tk
from tkinter import scrolledtext, font as tkfont
import threading
import time
import socket
import json
import argparse

from chat_utils import *
import client_state_machine as csm


# ==============================================================================
# Color palette and style constants
# ==============================================================================
BG_DARK     = "#1a1a2e"   # deep navy background
BG_MID      = "#16213e"   # slightly lighter panel
BG_INPUT    = "#0f3460"   # input area
ACCENT      = "#e94560"   # red-pink accent
ACCENT2     = "#533483"   # purple accent
TEXT_MAIN   = "#eaeaea"   # primary text
TEXT_DIM    = "#8892a4"   # dimmed/system text
BUBBLE_ME   = "#0f3460"   # sent message bubble
BUBBLE_PEER = "#1a1a2e"   # received message bubble
BUBBLE_SYS  = "#533483"   # system message bubble
ONLINE_DOT  = "#4ecca3"   # green online indicator


# ==============================================================================
# GUIClient: replaces the terminal-based Client class with a Tkinter GUI
# ==============================================================================
class GUIClient:
    def __init__(self, args):
        self.args = args
        self.name = ""
        self.state = S_OFFLINE
        self.sm = None
        self.socket = None

        # Build the main window
        self.root = tk.Tk()
        self.root.title("ICS Chat")
        self.root.geometry("780x620")
        self.root.configure(bg=BG_DARK)
        self.root.resizable(False, False)

        # Show login screen first
        self.build_login_screen()
        self.root.mainloop()

    # ==========================================================================
    # LOGIN SCREEN
    # ==========================================================================
    def build_login_screen(self):
        """Full-window login panel shown before main chat."""
        self.login_frame = tk.Frame(self.root, bg=BG_DARK)
        self.login_frame.place(relx=0.5, rely=0.5, anchor="center")

        # Title
        tk.Label(
            self.login_frame, text="ICS", bg=BG_DARK,
            fg=ACCENT, font=("Courier New", 48, "bold")
        ).pack(pady=(0, 0))

        tk.Label(
            self.login_frame, text="CHAT SYSTEM", bg=BG_DARK,
            fg=TEXT_DIM, font=("Courier New", 12, "bold"), letter_spacing=8
        ).pack(pady=(0, 30))

        # Username field
        tk.Label(
            self.login_frame, text="USERNAME", bg=BG_DARK,
            fg=TEXT_DIM, font=("Courier New", 9)
        ).pack(anchor="w")

        self.name_entry = tk.Entry(
            self.login_frame, width=28, bg=BG_INPUT, fg=TEXT_MAIN,
            insertbackground=ACCENT, relief="flat",
            font=("Courier New", 14), bd=8
        )
        self.name_entry.pack(pady=(4, 20), ipady=6)
        self.name_entry.focus()
        self.name_entry.bind("<Return>", lambda e: self.attempt_login())

        # Status label (shows errors)
        self.login_status = tk.Label(
            self.login_frame, text="", bg=BG_DARK,
            fg=ACCENT, font=("Courier New", 9)
        )
        self.login_status.pack(pady=(0, 10))

        # Connect button
        tk.Button(
            self.login_frame, text="CONNECT", command=self.attempt_login,
            bg=ACCENT, fg="white", font=("Courier New", 11, "bold"),
            relief="flat", cursor="hand2", bd=0,
            activebackground=ACCENT2, activeforeground="white",
            padx=30, pady=10
        ).pack()

    def attempt_login(self):
        """Try to connect to the server and log in."""
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

        # Send login message
        mysend(self.socket, json.dumps({"action": "login", "name": name}))
        try:
            response = json.loads(myrecv(self.socket))
        except Exception:
            self.login_status.config(text="Server error during login.")
            return

        if response["status"] == "ok":
            self.name = name
            self.state = S_LOGGEDIN
            self.sm = csm.ClientSM(self.socket)
            self.sm.set_state(S_LOGGEDIN)
            self.sm.set_myname(self.name)
            self.login_frame.destroy()
            self.build_chat_screen()
            self.start_recv_thread()
        elif response["status"] == "duplicate":
            self.login_status.config(text="Username taken. Try another.")
        else:
            self.login_status.config(text="Login failed.")

    # ==========================================================================
    # MAIN CHAT SCREEN
    # ==========================================================================
    def build_chat_screen(self):
        """Build the full chat UI after successful login."""
        self.root.title(f"ICS Chat  —  {self.name}")

        # ---- Top header bar ----
        header = tk.Frame(self.root, bg=BG_MID, height=54)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tk.Label(
            header, text="●", fg=ONLINE_DOT, bg=BG_MID,
            font=("Courier New", 14)
        ).pack(side="left", padx=(16, 6), pady=14)

        tk.Label(
            header, text=f"Logged in as  {self.name}",
            fg=TEXT_MAIN, bg=BG_MID, font=("Courier New", 11, "bold")
        ).pack(side="left", pady=14)

        tk.Label(
            header, text="ICS CHAT", fg=ACCENT,
            bg=BG_MID, font=("Courier New", 13, "bold")
        ).pack(side="right", padx=20, pady=14)

        # ---- Quick command buttons ----
        btn_bar = tk.Frame(self.root, bg=BG_MID, height=38)
        btn_bar.pack(fill="x")
        btn_bar.pack_propagate(False)

        cmds = [
            ("WHO",    lambda: self.send_command("who")),
            ("TIME",   lambda: self.send_command("time")),
            ("HELP",   lambda: self.append_msg("system", menu)),
        ]
        for label, cmd in cmds:
            tk.Button(
                btn_bar, text=label, command=cmd,
                bg=ACCENT2, fg="white", font=("Courier New", 8, "bold"),
                relief="flat", cursor="hand2", bd=0,
                activebackground=ACCENT, activeforeground="white",
                padx=12, pady=4
            ).pack(side="left", padx=4, pady=5)

        # Disconnect button on right
        tk.Button(
            btn_bar, text="DISCONNECT", command=lambda: self.send_command("bye"),
            bg=BG_DARK, fg=ACCENT, font=("Courier New", 8, "bold"),
            relief="flat", cursor="hand2", bd=0,
            activebackground=ACCENT, activeforeground="white",
            padx=12, pady=4
        ).pack(side="right", padx=8, pady=5)

        # ---- Message display area ----
        self.chat_area = scrolledtext.ScrolledText(
            self.root, state="disabled", wrap="word",
            bg=BG_DARK, fg=TEXT_MAIN,
            font=("Courier New", 11),
            relief="flat", bd=0,
            padx=16, pady=12,
            spacing3=6
        )
        self.chat_area.pack(fill="both", expand=True, padx=0, pady=0)

        # Configure text tags for bubble styling
        self.chat_area.tag_config(
            "me", foreground=ACCENT,
            font=("Courier New", 11, "bold"),
            lmargin1=80, lmargin2=80,
            rmargin=10
        )
        self.chat_area.tag_config(
            "peer", foreground=ONLINE_DOT,
            font=("Courier New", 11),
            lmargin1=10, lmargin2=10
        )
        self.chat_area.tag_config(
            "system", foreground=TEXT_DIM,
            font=("Courier New", 10, "italic"),
            lmargin1=10, lmargin2=10
        )
        self.chat_area.tag_config(
            "error", foreground=ACCENT,
            font=("Courier New", 10, "italic"),
            lmargin1=10
        )

        # ---- Bottom input area ----
        input_frame = tk.Frame(self.root, bg=BG_INPUT, height=60)
        input_frame.pack(fill="x", side="bottom")
        input_frame.pack_propagate(False)

        self.input_var = tk.StringVar()
        self.input_box = tk.Entry(
            input_frame, textvariable=self.input_var,
            bg=BG_INPUT, fg=TEXT_MAIN,
            insertbackground=ACCENT,
            font=("Courier New", 12),
            relief="flat", bd=0
        )
        self.input_box.pack(side="left", fill="both", expand=True, padx=16, pady=18)
        self.input_box.bind("<Return>", lambda e: self.send_message())

        tk.Button(
            input_frame, text="SEND", command=self.send_message,
            bg=ACCENT, fg="white",
            font=("Courier New", 10, "bold"),
            relief="flat", cursor="hand2", bd=0,
            activebackground=ACCENT2, activeforeground="white",
            padx=20
        ).pack(side="right", padx=10, pady=12)

        # Welcome message
        self.append_msg("system", f"Welcome, {self.name}! You are logged in.\n")
        self.append_msg("system", menu)

    # ==========================================================================
    # MESSAGING
    # ==========================================================================
    def append_msg(self, tag, text):
        """Thread-safe message display. tag: 'me', 'peer', 'system', 'error'"""
        def _insert():
            self.chat_area.config(state="normal")
            self.chat_area.insert("end", text + "\n", tag)
            self.chat_area.config(state="disabled")
            self.chat_area.see("end")
        self.root.after(0, _insert)

    def send_message(self):
        """Read input box, process through state machine, display sent message."""
        text = self.input_var.get().strip()
        if not text:
            return
        self.input_var.set("")

        # Display my own message in chat (required by rubric)
        if self.state == S_CHATTING:
            self.append_msg("me", f"[{self.name}]: {text}")

        # Feed into state machine
        out = self.sm.proc(text, "")
        self.state = self.sm.get_state()

        # Fix the intentional bug: system_msg reset is handled by proc return value
        if out:
            self.append_msg("system", out)

    def send_command(self, cmd):
        """Send a quick command from the button bar."""
        self.input_var.set(cmd)
        self.send_message()

    # ==========================================================================
    # RECEIVING MESSAGES (background thread)
    # ==========================================================================
    def start_recv_thread(self):
        """Background thread: polls server for incoming messages."""
        t = threading.Thread(target=self.recv_loop, daemon=True)
        t.start()

    def recv_loop(self):
        """Continuously receive from server, feed into state machine."""
        import select
        while self.state != S_OFFLINE:
            try:
                read, _, _ = select.select([self.socket], [], [], 0.2)
                if self.socket in read:
                    peer_msg = myrecv(self.socket)
                    if peer_msg:
                        # Parse to check if it's a chat exchange (show in peer bubble)
                        try:
                            parsed = json.loads(peer_msg)
                            if parsed.get("action") == "exchange":
                                sender = parsed.get("from", "peer")
                                message = parsed.get("message", "")
                                self.append_msg("peer", f"{sender}: {message}")
                            else:
                                # For connect/disconnect/list/etc, let SM handle it
                                out = self.sm.proc("", peer_msg)
                                self.state = self.sm.get_state()
                                if out:
                                    self.append_msg("system", out)
                        except Exception:
                            out = self.sm.proc("", peer_msg)
                            self.state = self.sm.get_state()
                            if out:
                                self.append_msg("system", out)
            except Exception:
                break
        self.append_msg("error", "Disconnected from server.")


# ==============================================================================
# Entry point
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="ICS Chat GUI Client")
    parser.add_argument("-d", type=str, default=None, help="Server IP address")
    args = parser.parse_args()
    GUIClient(args)


if __name__ == "__main__":
    main()
