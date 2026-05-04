import tkinter as tk
import random
import socket
import chat_utils
from scoreboard import update_score, get_leaderboard, reset_scores

CELL_SIZE = 20
WIDTH = 400
HEIGHT = 400


class SnakeGame:
    def __init__(self, root, username, client_socket, send_json):
        self.root = root
        self.root.title("Snake Game")
        self.username = username
        self.send_json = send_json
        self.client_socket = client_socket

        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg="black")
        self.canvas.pack()

        self.score = 0
        self.direction = "Right"
        self.game_over = False

        self.snake = [(100, 100), (80, 100), (60, 100)]
        self.food = self.spawn_food()

        self.root.bind("<KeyPress>", self.change_direction)
        self.canvas.focus_set()

        self.update()

    def spawn_food(self):
        x = random.randint(0, (WIDTH // CELL_SIZE) - 1) * CELL_SIZE
        y = random.randint(0, (HEIGHT // CELL_SIZE) - 1) * CELL_SIZE
        return (x, y)

    def change_direction(self, event):
        key = event.keysym
        opposite = {
            "Left": "Right",
            "Right": "Left",
            "Up": "Down",
            "Down": "Up"
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

        if (
            x < 0 or x >= WIDTH or
            y < 0 or y >= HEIGHT or
            new_head in self.snake
        ):
            self.end_game()
            return

        self.snake = [new_head] + self.snake

        if new_head == self.food:
            self.score += 1
            self.food = self.spawn_food()
        else:
            self.snake.pop()

    def draw(self):
        self.canvas.delete("all")

        for x, y in self.snake:
            self.canvas.create_rectangle(
                x, y, x + CELL_SIZE, y + CELL_SIZE, fill="green"
            )

        fx, fy = self.food
        self.canvas.create_rectangle(
            fx, fy, fx + CELL_SIZE, fy + CELL_SIZE, fill="red"
        )

        self.canvas.create_text(
            50, 10,
            fill="white",
            text=f"Score: {self.score}",
            anchor="nw"
        )

        if self.game_over:
            self.canvas.create_text(
                WIDTH // 2,
                HEIGHT // 2,
                fill="white",
                text="GAME OVER"
            )

    def update(self):
        if not self.game_over:
            self.move()
            self.draw()
            self.root.after(150, self.update)

    def end_game(self):
        self.game_over = True

        # Local update for immediate feedback
        update_score(self.username, self.score)
        print(get_leaderboard())

        # Send score to server via callback
        try:
            self.send_json({"action": "snake_submit_score", "score": self.score})
        except Exception as e:
            print(f"Failed to send score: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    game = SnakeGame(root)
    root.mainloop()