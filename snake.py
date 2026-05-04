import random
import tkinter as tk
from typing import Optional, Callable

import chat_utils

CELL_SIZE = 20
WIDTH = 400
HEIGHT = 400


class SnakeGame:
    """
    Reusable Snake Tkinter UI.

    Multiplayer/score integration:
      - Uses the caller's already-open chat socket.
      - Submits score via JSON action: {"action":"snake_submit_score","score":<int>}
      - Leaderboard can be requested by {"action":"snake_leaderboard"}.

    UX change:
      - Does NOT auto-start the game on window open.
      - Provides Start Game / Quit buttons.
    """

    def __init__(
        self,
        root: tk.Misc,
        *,
        username: str,
        client_socket,
        send_json: Callable[[dict], None],
    ):
        self.root = root
        self.username = username
        self.client_socket = client_socket
        self.send_json = send_json

        self.running = False

        # -------------------------
        # UI
        # -------------------------
        # Top status + controls
        self.top_frame = tk.Frame(self.root, bg="black")
        self.top_frame.pack(fill="x")

        self.status_var = tk.StringVar(value="Press Start Game")
        self.status_label = tk.Label(
            self.top_frame, textvariable=self.status_var, fg="white", bg="black", font=("Courier New", 12)
        )
        self.status_label.pack(side="left", padx=10, pady=8)

        self.start_btn = tk.Button(
            self.top_frame,
            text="START GAME",
            font=("Courier New", 10, "bold"),
            command=self.start_game,
            width=14,
        )
        self.start_btn.pack(side="right", padx=8, pady=6)

        self.quit_btn = tk.Button(
            self.top_frame,
            text="QUIT",
            font=("Courier New", 10, "bold"),
            command=self.quit_game,
            width=10,
        )
        self.quit_btn.pack(side="right", padx=8, pady=6)

        # Canvas
        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Bind input (direction) but only act while running.
        self.root.bind("<KeyPress>", self.change_direction)
        self.canvas.focus_set()

        # -------------------------
        # Game state
        # -------------------------
        self.score = 0
        self.direction = "Right"
        self.game_over = False

        self.snake = [(100, 100), (80, 100), (60, 100)]
        self.food = self.spawn_food()

        self._tick_after_id: Optional[str] = None

        # Initial render only (no auto-loop)
        self._draw()

    # -------------------------
    # Game logic
    # -------------------------
    def spawn_food(self):
        x = random.randint(0, (WIDTH // CELL_SIZE) - 1) * CELL_SIZE
        y = random.randint(0, (HEIGHT // CELL_SIZE) - 1) * CELL_SIZE
        return (x, y)

    def change_direction(self, event):
        if not self.running or self.game_over:
            return

        key = event.keysym
        opposite = {
            "Left": "Right",
            "Right": "Left",
            "Up": "Down",
            "Down": "Up",
        }
        if key in opposite and key != opposite[self.direction]:
            self.direction = key

    def move(self):
        x, y = self.snake[0]

        if self.direction == "Left":
            x -= CELL_SIZE
        elif self.direction == "Right":
            x += CELL_SIZE
        elif self.direction == "Up":
            y -= CELL_SIZE
        elif self.direction == "Down":
            y += CELL_SIZE

        new_head = (x, y)

        # Collision: wall or self
        if (
            x < 0
            or x >= WIDTH
            or y < 0
            or y >= HEIGHT
            or new_head in self.snake
        ):
            self.end_game()
            return

        self.snake = [new_head] + self.snake

        if new_head == self.food:
            self.score += 1
            self.food = self.spawn_food()
        else:
            self.snake.pop()

    def start_game(self):
        if self.running:
            return
        if self.game_over:
            # For now, keep it simple: require closing and reopening for restart.
            self.status_var.set("Game ended. Close and reopen to play again.")
            return

        self.running = True
        self.start_btn.config(state="disabled")
        self.status_var.set(f"Running... {self.username} Score: {self.score}")
        self._tick()

    def _tick(self):
        if not self.running:
            return
        if self.game_over:
            return

        self.move()
        self._draw()

        if self.running and not self.game_over:
            self._tick_after_id = self.root.after(150, self._tick)

    def end_game(self):
        self.game_over = True
        self.running = False

        self.status_var.set(f"GAME OVER - {self.username} Score: {self.score}")

        # Submit via server protocol (best effort)
        try:
            self.send_json({"action": "snake_submit_score", "score": self.score})
        except Exception:
            pass

        # Stop start button to avoid confusion
        self.start_btn.config(state="disabled")

    def quit_game(self):
        # Stop loop + close window
        self.running = False
        if self._tick_after_id is not None:
            try:
                self.root.after_cancel(self._tick_after_id)
            except Exception:
                pass
            self._tick_after_id = None

        # Close the window (caller created it as Toplevel)
        try:
            self.root.destroy()
        except Exception:
            pass

    # -------------------------
    # Rendering
    # -------------------------
    def _draw(self):
        self.canvas.delete("all")

        for x, y in self.snake:
            self.canvas.create_rectangle(
                x,
                y,
                x + CELL_SIZE,
                y + CELL_SIZE,
                fill="green",
                outline="",
            )

        fx, fy = self.food
        self.canvas.create_rectangle(fx, fy, fx + CELL_SIZE, fy + CELL_SIZE, fill="red", outline="")

        self.canvas.create_text(
            50,
            10,
            fill="white",
            text=f"Score: {self.score}",
            anchor="nw",
            font=("Courier New", 12),
        )

        if not self.running and not self.game_over:
            self.canvas.create_text(
                WIDTH // 2,
                HEIGHT // 2,
                fill="white",
                text="Press START GAME",
                font=("Courier New", 16, "bold"),
                justify="center",
            )

        if self.game_over:
            self.canvas.create_text(
                WIDTH // 2,
                HEIGHT // 2,
                fill="white",
                text="GAME OVER",
                font=("Courier New", 18, "bold"),
                justify="center",
            )

        # Keep status synced
        if self.game_over:
            self.status_var.set(f"GAME OVER - {self.username} Score: {self.score}")
        elif self.running:
            self.status_var.set(f"Running... {self.username} Score: {self.score}")

    # Optional external API
    def request_leaderboard(self):
        self.send_json({"action": "snake_leaderboard"})
