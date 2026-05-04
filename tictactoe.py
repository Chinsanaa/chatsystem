import tkinter as tk

class TicTacToe:
    def __init__(self, root):
        self.root = root
        self.root.title("Tic Tac Toe (2 Player)")

        self.board = [""] * 9
        self.current_player = "X"
        self.game_over = False

        self.buttons = []

        for i in range(9):
            btn = tk.Button(
                root,
                text="",
                font=("Arial", 20),
                width=5,
                height=2,
                command=lambda i=i: self.make_move(i)
            )
            btn.grid(row=i//3, column=i%3)
            self.buttons.append(btn)

        self.status = tk.Label(root, text="Player X turn", font=("Arial", 14))
        self.status.grid(row=3, column=0, columnspan=3)

    def make_move(self, i):
        if self.board[i] == "" and not self.game_over:
            self.board[i] = self.current_player
            self.buttons[i].config(text=self.current_player)

            if self.check_winner():
                self.status.config(text=f"Player {self.current_player} wins!")
                self.game_over = True
                return

            if "" not in self.board:
                self.status.config(text="Draw!")
                self.game_over = True
                return

            self.current_player = "O" if self.current_player == "X" else "X"
            self.status.config(text=f"Player {self.current_player} turn")

    def check_winner(self):
        wins = [
            [0,1,2],[3,4,5],[6,7,8],
            [0,3,6],[1,4,7],[2,5,8],
            [0,4,8],[2,4,6]
        ]

        for a, b, c in wins:
            if self.board[a] == self.board[b] == self.board[c] != "":
                return True
        return False


root = tk.Tk()
game = TicTacToe(root)
root.mainloop()