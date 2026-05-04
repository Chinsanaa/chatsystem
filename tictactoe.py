import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any


WIN_TRIPLES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
]


def check_winner(board):
    for a, b, c in WIN_TRIPLES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return None


@dataclass
class TTTMeta:
    game_id: str
    your_symbol: str  # "X" or "O"


class TicTacToeMultiplayerWindow:
    """
    Importable TicTacToe multiplayer Tk window.

    It expects to be driven by server events coming from GUIClient:
      - ttt_challenge -> show Accept/Decline
      - ttt_start -> lock in symbols + show board + enable moves on your turn
      - ttt_state -> update board, status, disable if finished
      - ttt_abort  -> show reason and disable
    """

    def __init__(
        self,
        root: tk.Misc,
        *,
        title_prefix: str,
        username: str,
        send_json: Callable[[dict], None],
    ):
        self.root = root
        self.username = username
        self.send_json = send_json
        self.game_id: Optional[str] = None
        self.your_symbol: Optional[str] = None
        self.opponent_name: Optional[str] = None

        self.board = [""] * 9
        self.turn = "X"
        self.winner: Optional[str] = None
        self.draw = False
        self.status = "not_started"

        self.window = tk.Toplevel(self.root)
        self.window.title(f"{title_prefix} - Tic Tac Toe")
        # Position next to main window
        self.window.geometry("450x550")

        self.label_top = tk.Label(self.window, text="Waiting for opponent...", font=("Arial", 12))
        self.label_top.pack(pady=(8, 4))

        self.board_frame = tk.Frame(self.window)
        self.board_frame.pack(pady=8)

        self.buttons = []
        for i in range(9):
            btn = tk.Button(
                self.board_frame,
                text="",
                font=("Arial", 24),
                width=5,
                height=2,
                command=lambda i=i: self.on_cell_clicked(i),
                state="disabled",
            )
            btn.grid(row=i // 3, column=i % 3, padx=3, pady=3)
            self.buttons.append(btn)

        self.status_label = tk.Label(self.window, text="--", font=("Arial", 12))
        self.status_label.pack(pady=(6, 8))

        self.actions_frame = tk.Frame(self.window)
        self.actions_frame.pack(pady=(0, 10))

        self.accept_btn = tk.Button(
            self.actions_frame, text="ACCEPT", font=("Arial", 10),
            width=10, state="disabled", command=self.accept
        )
        self.accept_btn.grid(row=0, column=0, padx=5)

        self.decline_btn = tk.Button(
            self.actions_frame, text="DECLINE", font=("Arial", 10),
            width=10, state="disabled", command=self.decline
        )
        self.decline_btn.grid(row=0, column=1, padx=5)

        self.leave_btn = tk.Button(
            self.actions_frame, text="CLOSE", font=("Arial", 10),
            width=10, state="normal", command=self.window.destroy
        )
        self.leave_btn.grid(row=0, column=2, padx=5)

        self.set_board_disabled(True)

    # -------------------------
    # Server-driven handlers
    # -------------------------
    def on_challenge(self, payload: Dict[str, Any]):
        """
        payload:
          action=ttt_challenge
          game_id, from (inviter), your_symbol
        """
        self.game_id = payload["game_id"]
        self.your_symbol = payload.get("your_symbol")
        self.opponent_name = payload.get("from")

        self.board = [""] * 9
        self.turn = "X"
        self.winner = None
        self.draw = False
        self.status = "pending"

        self._render_board()
        self.label_top.config(text=f"Challenge from {self.opponent_name or 'Unknown'}")
        self.status_label.config(text="Do you accept the game?")

        self.accept_btn.config(state="normal")
        self.decline_btn.config(state="normal")
        self.leave_btn.config(state="disabled")
        self.set_board_disabled(True)

    def on_start(self, payload: Dict[str, Any]):
        """
        payload:
          action=ttt_start
          game_id, board, players, turn, your_symbol, status
        """
        self.game_id = payload["game_id"]
        self.your_symbol = payload.get("your_symbol")
        players = payload.get("players", {})

        self.opponent_name = payload.get("opponent") or players.get("O" if self.your_symbol == "X" else "X") or "Unknown"

        self.board = list(payload.get("board", [""] * 9))
        self.turn = payload.get("turn", "X")
        self.winner = payload.get("winner")
        self.draw = bool(payload.get("draw", False))
        self.status = payload.get("status", "playing")

        self.accept_btn.config(state="disabled")
        self.decline_btn.config(state="disabled")

        self.leave_btn.config(state="normal")
        self._sync_controls_from_state()
        self._render_board()
        self.label_top.config(text=f"vs {self.opponent_name }" or "Tic Tac Toe")

        self._render_status()

    def on_state(self, payload: Dict[str, Any]):
        self.game_id = payload["game_id"]
        self.your_symbol = payload.get("your_symbol", self.your_symbol)

        self.board = list(payload.get("board", self.board))
        self.turn = payload.get("turn", self.turn)
        self.winner = payload.get("winner")
        self.draw = bool(payload.get("draw", False))
        self.status = payload.get("status", "playing")

        self.leave_btn.config(state="normal")
        self._sync_controls_from_state()
        self._render_board()
        self._render_status()

    def on_abort(self, payload: Dict[str, Any]):
        reason = payload.get("reason", "opponent left")
        self.status = "aborted"
        self.set_board_disabled(True)
        self.accept_btn.config(state="disabled")
        self.decline_btn.config(state="disabled")
        self.leave_btn.config(state="disabled")
        self.status_label.config(text=f"Game ended: {reason}")

    # -------------------------
    # UI interactions
    # -------------------------
    def on_cell_clicked(self, index: int):
        if self.status != "playing":
            return
        if not self.game_id or not self.your_symbol:
            return
        if self.your_symbol != self.turn:
            return
        if self.board[index] != "":
            return

        self.send_json({"action": "ttt_move", "game_id": self.game_id, "index": index})

    def set_board_disabled(self, disabled: bool):
        for i, b in enumerate(self.buttons):
            if disabled:
                b.config(state="disabled")
            else:
                # Only enable empty cells; disable others
                b.config(state=("normal" if self.board[i] == "" else "disabled"))

    def accept(self):
        if not self.game_id:
            return
        self.send_json({"action": "ttt_accept", "game_id": self.game_id})
        self.accept_btn.config(state="disabled")
        self.decline_btn.config(state="disabled")

    def decline(self):
        if not self.game_id:
            return
        # Server currently doesn't implement ttt_decline; we still attempt and
        # gracefully ignore server error by disabling controls locally.
        try:
            self.send_json({"action": "ttt_decline", "game_id": self.game_id})
        finally:
            self.accept_btn.config(state="disabled")
            self.decline_btn.config(state="disabled")
            self.status_label.config(text="Declined.")

    def leave(self):
        if not self.game_id:
            return
        self.send_json({"action": "ttt_leave", "game_id": self.game_id})
        self.leave_btn.config(state="disabled")
        self.set_board_disabled(True)

    # -------------------------
    # Rendering helpers
    # -------------------------
    def _render_board(self):
        for i, btn in enumerate(self.buttons):
            btn.config(text=self.board[i])

    def _render_status(self):
        if self.status == "aborted":
            return

        if self.status == "finished":
            if self.winner:
                self.status_label.config(text=f"{self.winner} wins!")
            elif self.draw:
                self.status_label.config(text="Draw!")
            else:
                self.status_label.config(text="Game finished.")
            self.set_board_disabled(True)
            return

        # playing
        your_turn = (self.your_symbol == self.turn)
        if your_turn:
            self.status_label.config(text=f"Your turn ({self.your_symbol})")
        else:
            self.status_label.config(text=f"Opponent's turn ({self.turn})")

    def _sync_controls_from_state(self):
        if self.status != "playing":
            self.set_board_disabled(True)
            return
        if self.your_symbol != self.turn:
            self.set_board_disabled(True)
            return
        # it's your turn
        self.set_board_disabled(False)
        # ensure only empties are enabled
        for i, btn in enumerate(self.buttons):
            btn.config(state=("normal" if self.board[i] == "" else "disabled"))


__all__ = ["TicTacToeMultiplayerWindow"]
