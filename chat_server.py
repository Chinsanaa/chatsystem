"""
Created on Tue Jul 22 00:47:05 2014

@author: alina, zzhang
"""

import time
import socket
import select
import indexer
import json
import pickle as pkl
import scoreboard as sb
from uuid import uuid4
from chat_utils import *
import chat_group as grp
import os
import hashlib


# Simple user database (JSON) helpers
USERS_FILE = 'users.json'

def _load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)

def _hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode('utf-8')).hexdigest()


class Server:
    def __init__(self):
        self.new_clients = []  # list of new sockets of which the user id is not known
        self.logged_name2sock = {}  # dictionary mapping username to socket
        self.logged_sock2name = {}  # dict mapping socket to user name
        self.all_sockets = []
        self.group = grp.Group()
        # start server
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(SERVER)
        self.server.listen(5)
        self.all_sockets.append(self.server)
        # initialize past chat indices
        self.indices = {}
        # sonnet
        self.sonnet = indexer.PIndex("AllSonnets.txt")

        # ------------------------------------------------------------------
        # Games state (in-memory)
        # ------------------------------------------------------------------

        # Snake leaderboard is stored in scoreboard.py (module-level).
        # For tic-tac-toe we keep per-session state in-memory here.
        self.ttt_games = {}  # game_id -> game_state dict
        self.ttt_player_to_game_id = {}  # player_name -> game_id
        # inviter_name -> {"target": target_name, "game_id": game_id}
        self.ttt_pending_challenges = {}

    def new_client(self, sock):
        # add to all sockets and to new clients
        sock.setblocking(0)
        self.new_clients.append(sock)
        self.all_sockets.append(sock)

    def _drop_socket(self, sock):
        """Best-effort cleanup for sockets that are not fully logged in."""
        if sock in self.new_clients:
            self.new_clients.remove(sock)
        if sock in self.all_sockets:
            self.all_sockets.remove(sock)
        try:
            sock.close()
        except Exception:
            pass

    def _send_error(self, sock, reason):
        try:
            mysend(sock, json.dumps({"action": "error", "reason": reason}))
        except Exception:
            pass

    def login(self, sock):
        # read the msg that should have login code plus username
        try:
            msg = json.loads(myrecv(sock))
            if len(msg) > 0:

                action = msg.get("action")
                # Allow signup/forgot during initial handshake (before login)
                if action == "signup":
                    name = msg.get("name", "").strip()
                    email = msg.get("email", "").strip()
                    password = msg.get("password", "")
                    if not name or not email or not password:
                        mysend(sock, json.dumps({"action": "signup", "status": "missing-fields"}))
                        return
                    users = _load_users()
                    if name in users:
                        mysend(sock, json.dumps({"action": "signup", "status": "exists"}))
                        return
                    users[name] = {"email": email, "pw_hash": _hash_password(password)}
                    _save_users(users)
                    mysend(sock, json.dumps({"action": "signup", "status": "ok"}))
                    return
                if action == "forgot":
                    name = msg.get("name", "").strip()
                    email = msg.get("email", "").strip()
                    if not name or not email:
                        mysend(sock, json.dumps({"action": "forgot", "status": "missing-fields"}))
                        return
                    users = _load_users()
                    if name not in users or users[name].get("email") != email:
                        mysend(sock, json.dumps({"action": "forgot", "status": "no-match"}))
                        return
                    import random, string
                    temp = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
                    users[name]["pw_hash"] = _hash_password(temp)
                    _save_users(users)
                    mysend(sock, json.dumps({"action": "forgot", "status": "ok", "temp": temp}))
                    return

                if msg["action"] == "login":
                    # require name and password; only allow existing accounts
                    name = msg.get("name", "").strip()
                    password = msg.get("password", "")
                    users = _load_users()
                    # require an existing account
                    if name not in users:
                        mysend(sock, json.dumps({"action": "login", "status": "no-account"}))
                        return
                    # check password match
                    stored = users[name]
                    if _hash_password(password) != stored.get("pw_hash"):
                        mysend(sock, json.dumps({"action": "login", "status": "bad-password"}))
                        return
                    # continue with original duplicate/login logic
                    if self.group.is_member(name) != True:
                        # move socket from new clients list to logged clients
                        self.new_clients.remove(sock)
                        # add into the name to sock mapping
                        self.logged_name2sock[name] = sock
                        self.logged_sock2name[sock] = name
                        # load chat history of that user
                        if name not in self.indices.keys():
                            try:
                                self.indices[name] = pkl.load(
                                    open(name + '.idx', 'rb'))
                            except IOError:  # chat index does not exist, then create one
                                self.indices[name] = indexer.Index(name)
                        self.group.join(name)
                        mysend(sock, json.dumps(
                            {"action": "login", "status": "ok"}))
                    else:  # a client under this name has already logged in
                        mysend(sock, json.dumps(
                            {"action": "login", "status": "duplicate"}))
                else:
                    self._drop_socket(sock)
            else:  # client died unexpectedly
                self.logout(sock)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._drop_socket(sock)
        except Exception:
            self._drop_socket(sock)

    def logout(self, sock):
        # remove sock from all lists
        if sock in self.logged_sock2name:
            name = self.logged_sock2name[sock]
            if name in self.indices:
                pkl.dump(self.indices[name], open(name + '.idx', 'wb'))
                del self.indices[name]
            if name in self.logged_name2sock:
                del self.logged_name2sock[name]
            del self.logged_sock2name[sock]
            self.group.leave(name)

        if sock in self.new_clients:
            self.new_clients.remove(sock)
        if sock in self.all_sockets:
            self.all_sockets.remove(sock)
        try:
            sock.close()
        except Exception:
            pass

# ==============================================================================
# main command switchboard
# ==============================================================================
    def handle_msg(self, from_sock):
        # read msg code
        msg = myrecv(from_sock)
        if len(msg) > 0:
            # ==============================================================================
            # handle connect request this is implemented for you
            # ==============================================================================
            try:
                msg = json.loads(msg)
            except json.JSONDecodeError:
                self._send_error(from_sock, "invalid json")
                return

            action = msg.get("action")
            if not action:
                self._send_error(from_sock, "missing action")
                return

            if action == "connect":
                to_name = msg.get("target", "").strip()
                if not to_name:
                    self._send_error(from_sock, "missing connect target")
                    return
                from_name = self.logged_sock2name[from_sock]
                if to_name == from_name:
                    msg = json.dumps({"action": "connect", "status": "self"})
                # connect to the peer: check actual logged-in users first
                elif to_name in self.logged_name2sock:
                    # if the peer is already talking, mark busy
                    if self.group.members.get(to_name) == grp.S_TALKING:
                        msg = json.dumps({"action": "connect", "status": "busy"})
                    else:
                        # create or join group
                        self.group.connect(from_name, to_name)
                        the_guys = self.group.list_me(from_name)
                        msg = json.dumps({"action": "connect", "status": "success"})
                        # notify other members (the_guys[1:]) with a request
                        for g in the_guys[1:]:
                            to_sock = self.logged_name2sock.get(g)
                            if to_sock:
                                mysend(to_sock, json.dumps({"action": "connect", "status": "request", "from": from_name}))
                else:
                    msg = json.dumps({"action": "connect", "status": "no-user"})
                mysend(from_sock, msg)
            elif action == "signup":
                # signup expects name, email, password
                name = msg.get("name", "").strip()
                email = msg.get("email", "").strip()
                password = msg.get("password", "")
                if not name or not email or not password:
                    mysend(from_sock, json.dumps({"action": "signup", "status": "missing-fields"}))
                    return
                users = _load_users()
                if name in users:
                    mysend(from_sock, json.dumps({"action": "signup", "status": "exists"}))
                    return
                users[name] = {"email": email, "pw_hash": _hash_password(password)}
                _save_users(users)
                mysend(from_sock, json.dumps({"action": "signup", "status": "ok"}))
            elif action == "forgot":
                # forgot expects name and email, returns temp password
                name = msg.get("name", "").strip()
                email = msg.get("email", "").strip()
                if not name or not email:
                    mysend(from_sock, json.dumps({"action": "forgot", "status": "missing-fields"}))
                    return
                users = _load_users()
                if name not in users or users[name].get("email") != email:
                    mysend(from_sock, json.dumps({"action": "forgot", "status": "no-match"}))
                    return
                # generate a temporary password (insecure but OK for demo)
                import random, string
                temp = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
                users[name]["pw_hash"] = _hash_password(temp)
                _save_users(users)
                mysend(from_sock, json.dumps({"action": "forgot", "status": "ok", "temp": temp}))
# ==============================================================================
# handle messeage exchange: IMPLEMENT THIS
# ==============================================================================
            elif action == "exchange":
                from_name = self.logged_sock2name[from_sock]  # real socket owner
                message = msg.get("message")
                if not isinstance(message, str):
                    self._send_error(from_sock, "missing exchange message")
                    return

                # Optional sender label from client (used for bot messages).
                # If absent/invalid, fall back to the real user.
                display_from = msg.get("from", from_name)
                if not isinstance(display_from, str) or not display_from.strip():
                    display_from = from_name

                """
                Finding the list of people to send to and index message
                """
                # IMPLEMENTATION
                # ---- start your code ---- #
                # Store each chat line in sender's searchable index.
                # Use display_from so bot replies render/search properly.
                line = text_proc(message, display_from)
                self.indices[from_name].add_msg_and_index(line)

                # ---- end of your code --- #

                the_guys = self.group.list_me(from_name)[1:]
                for g in the_guys:
                    to_sock = self.logged_name2sock[g]

                    # IMPLEMENTATION
                    # ---- start your code ---- #
                    mysend(
                        to_sock,
                        json.dumps(
                            {
                                "action": "exchange",
                                "from": display_from,
                                "message": message
                            }
                        )
                    )

                    # ---- end of your code --- #

# ==============================================================================
# the "from" guy has had enough (talking to "to")!
# ==============================================================================
            elif action == "disconnect":
                from_name = self.logged_sock2name[from_sock]
                the_guys = self.group.list_me(from_name)
                self.group.disconnect(from_name)
                the_guys.remove(from_name)
                if len(the_guys) == 1:  # only one left
                    g = the_guys.pop()
                    to_sock = self.logged_name2sock[g]
                    mysend(to_sock, json.dumps(
                        {"action": "disconnect", "msg": "everyone left, you are alone"}))
# ==============================================================================
#                 listing available peers: IMPLEMENT THIS
# ==============================================================================
            elif action == "list":

                # IMPLEMENTATION
                # ---- start your code ---- #
                
                msg = str(self.group.list_all())

                # ---- end of your code --- #
                mysend(from_sock, json.dumps(
                    {"action": "list", "results": msg}))
# ==============================================================================
#             retrieve a sonnet : IMPLEMENT THIS
# ==============================================================================
            elif action == "poem":

                # IMPLEMENTATION
                # ---- start your code ---- #
                poem = ""
                try:
                    poem_idx = int(msg.get("target"))
                    poem = self.sonnet.get_poem(poem_idx)
                    if isinstance(poem, list):
                        poem = "\n".join(poem)
                except (ValueError, KeyError, TypeError):
                    poem = ""

                # ---- end of your code --- #

                mysend(from_sock, json.dumps(
                    {"action": "poem", "results": poem}))
# ==============================================================================
#                 time
# ==============================================================================
            elif action == "time":
                ctime = time.strftime('%d.%m.%y,%H:%M', time.localtime())
                mysend(from_sock, json.dumps(
                    {"action": "time", "results": ctime}))
# ==============================================================================
#                 search: : IMPLEMENT THIS
# ==============================================================================
            elif action == "search":
                target = msg.get("target")
                if not isinstance(target, str):
                    self._send_error(from_sock, "missing search target")
                    return

                # IMPLEMENTATION
                # ---- start your code ---- #
                from_name = self.logged_sock2name[from_sock]
                hits = self.indices[from_name].search(target)
                search_rslt = "\n".join([x[1] for x in hits])

                # ---- end of your code --- #
                mysend(from_sock, json.dumps(
                    {"action": "search", "results": search_rslt}))
            else:
                self._send_error(from_sock, "unknown action")

            # ==============================================================================
            # Snake / Scoreboard (JSON protocol)
            # ==============================================================================
            elif action == "snake_leaderboard":
                try:
                    leaderboard = sb.get_leaderboard()
                except Exception as e:
                    leaderboard = f"Error building leaderboard: {e}"
                mysend(from_sock, json.dumps({"action": "snake_leaderboard", "results": leaderboard}))

            elif action == "snake_submit_score":
                from_name = self.logged_sock2name[from_sock]
                score = msg.get("score")
                try:
                    score_int = int(score)
                except Exception:
                    self._send_error(from_sock, "missing/invalid snake score")
                    return

                sb.update_score(from_name, score_int)
                try:
                    leaderboard = sb.get_leaderboard()
                except Exception:
                    leaderboard = ""
                mysend(from_sock, json.dumps({
                    "action": "snake_submit_score",
                    "status": "ok",
                    "score": score_int,
                    "leaderboard": leaderboard
                }))

            # ==============================================================================
            # Tic Tac Toe Multiplayer (JSON protocol)
            # ==============================================================================
            elif action == "ttt_invite":
                inviter = self.logged_sock2name[from_sock]
                target = msg.get("target", "").strip()
                if not target or target == inviter:
                    self._send_error(from_sock, "invalid ttt_invite target")
                    return
                if target not in self.logged_name2sock:
                    self._send_error(from_sock, "target not online")
                    return
                if target in self.ttt_pending_challenges:
                    self._send_error(from_sock, "target already has a pending challenge")
                    return

                game_id = uuid4().hex
                self.ttt_pending_challenges[target] = {"from": inviter, "game_id": game_id}

                # X = inviter, O = target
                mysend(from_sock, json.dumps({
                    "action": "ttt_invite",
                    "status": "sent",
                    "game_id": game_id,
                    "to": target,
                    "your_symbol": "X"
                }))

                target_sock = self.logged_name2sock[target]
                mysend(target_sock, json.dumps({
                    "action": "ttt_challenge",
                    "game_id": game_id,
                    "from": inviter,
                    "your_symbol": "O",
                }))

            elif action == "ttt_decline":
                decliner = self.logged_sock2name[from_sock]
                game_id = msg.get("game_id")
                if not isinstance(game_id, str) or not game_id:
                    self._send_error(from_sock, "missing ttt_decline game_id")
                    return

                pending = self.ttt_pending_challenges.get(decliner)
                if not pending or pending.get("game_id") != game_id:
                    self._send_error(from_sock, "no such pending challenge for decline")
                    return

                inviter = pending.get("from")
                # clear pending first
                del self.ttt_pending_challenges[decliner]

                inviter_sock = self.logged_name2sock.get(inviter)
                if inviter_sock:
                    mysend(inviter_sock, json.dumps({
                        "action": "ttt_declined",
                        "game_id": game_id,
                        "from": inviter,
                        "to": decliner,
                        "reason": "declined"
                    }))

                mysend(from_sock, json.dumps({
                    "action": "ttt_declined",
                    "game_id": game_id,
                    "status": "ok"
                }))

            elif action == "ttt_accept":
                accepter = self.logged_sock2name[from_sock]
                game_id = msg.get("game_id")
                if not isinstance(game_id, str) or not game_id:
                    self._send_error(from_sock, "missing ttt_accept game_id")
                    return
                pending = self.ttt_pending_challenges.get(accepter)
                if not pending or pending.get("game_id") != game_id:
                    self._send_error(from_sock, "no such pending challenge for accept")
                    return

                inviter = pending.get("from")
                if inviter not in self.logged_name2sock:
                    self._send_error(from_sock, "inviter not online anymore")
                    return

                # Create game state
                game_state = {
                    "game_id": game_id,
                    "board": [""] * 9,
                    "players": {"X": inviter, "O": accepter},
                    "turn": "X",
                    "winner": None,
                    "draw": False,
                    "status": "playing",
                }
                self.ttt_games[game_id] = game_state
                self.ttt_player_to_game_id[inviter] = game_id
                self.ttt_player_to_game_id[accepter] = game_id

                # clear pending
                del self.ttt_pending_challenges[accepter]

                inviter_sock = self.logged_name2sock[inviter]
                accepter_sock = self.logged_name2sock[accepter]

                # Broadcast start/state
                for player_name, sock in [(inviter, inviter_sock), (accepter, accepter_sock)]:
                    symbol = "X" if player_name == inviter else "O"
                    mysend(sock, json.dumps({
                        "action": "ttt_start",
                        "game_id": game_id,
                        "board": game_state["board"],
                        "players": game_state["players"],
                        "turn": game_state["turn"],
                        "winner": game_state["winner"],
                        "draw": game_state["draw"],
                        "status": game_state["status"],
                        "your_symbol": symbol,
                    }))

            elif action == "ttt_move":
                mover = self.logged_sock2name[from_sock]
                game_id = msg.get("game_id")
                index = msg.get("index")

                if not isinstance(game_id, str) or not game_id:
                    self._send_error(from_sock, "missing ttt_move game_id")
                    return
                if not isinstance(index, int):
                    self._send_error(from_sock, "missing/invalid ttt_move index")
                    return
                if game_id not in self.ttt_games:
                    self._send_error(from_sock, "unknown ttt game_id")
                    return

                game_state = self.ttt_games[game_id]
                if game_state.get("status") != "playing":
                    self._send_error(from_sock, "game is not active")
                    return

                players = game_state["players"]
                your_symbol = None
                if mover == players["X"]:
                    your_symbol = "X"
                elif mover == players["O"]:
                    your_symbol = "O"
                else:
                    self._send_error(from_sock, "you are not part of this game")
                    return

                if your_symbol != game_state["turn"]:
                    self._send_error(from_sock, "not your turn")
                    return

                if index < 0 or index > 8:
                    self._send_error(from_sock, "index out of range")
                    return

                if game_state["board"][index] != "":
                    self._send_error(from_sock, "cell already taken")
                    return

                # Apply move
                game_state["board"][index] = your_symbol

                wins = [
                    (0, 1, 2), (3, 4, 5), (6, 7, 8),
                    (0, 3, 6), (1, 4, 7), (2, 5, 8),
                    (0, 4, 8), (2, 4, 6),
                ]
                winner = None
                for a, b, c in wins:
                    if game_state["board"][a] and game_state["board"][a] == game_state["board"][b] == game_state["board"][c]:
                        winner = game_state["board"][a]
                        break

                if winner:
                    game_state["winner"] = winner
                    game_state["draw"] = False
                    game_state["status"] = "finished"
                else:
                    if "" not in game_state["board"]:
                        game_state["winner"] = None
                        game_state["draw"] = True
                        game_state["status"] = "finished"
                    else:
                        game_state["winner"] = None
                        game_state["draw"] = False
                        game_state["turn"] = "O" if game_state["turn"] == "X" else "X"

                # Broadcast updated state
                x_name = players["X"]
                o_name = players["O"]
                for player_name in [x_name, o_name]:
                    if player_name not in self.logged_name2sock:
                        continue
                    sock = self.logged_name2sock[player_name]
                    symbol = "X" if player_name == x_name else "O"
                    mysend(sock, json.dumps({
                        "action": "ttt_state",
                        "game_id": game_id,
                        "board": game_state["board"],
                        "players": game_state["players"],
                        "turn": game_state.get("turn", None),
                        "winner": game_state["winner"],
                        "draw": game_state["draw"],
                        "status": game_state["status"],
                        "your_symbol": symbol,
                    }))

                if game_state["status"] == "finished":
                    # remove from active mapping after broadcasting
                    for nm in [x_name, o_name]:
                        if nm in self.ttt_player_to_game_id and self.ttt_player_to_game_id[nm] == game_id:
                            del self.ttt_player_to_game_id[nm]
                    # keep game state in self.ttt_games for now (optional)

            elif action == "ttt_leave":
                leaver = self.logged_sock2name[from_sock]
                game_id = msg.get("game_id")
                if not isinstance(game_id, str) or not game_id:
                    self._send_error(from_sock, "missing/invalid ttt_leave game_id")
                    return
                if game_id not in self.ttt_games:
                    self._send_error(from_sock, "unknown ttt game_id")
                    return

                game_state = self.ttt_games[game_id]
                if leaver not in [game_state["players"]["X"], game_state["players"]["O"]]:
                    self._send_error(from_sock, "you are not part of this game")
                    return

                other = game_state["players"]["O"] if leaver == game_state["players"]["X"] else game_state["players"]["X"]
                other_sock = self.logged_name2sock.get(other)
                if other_sock:
                    mysend(other_sock, json.dumps({
                        "action": "ttt_abort",
                        "game_id": game_id,
                        "reason": "opponent_left"
                    }))

                # cleanup mapping
                for nm in [game_state["players"]["X"], game_state["players"]["O"]]:
                    if nm in self.ttt_player_to_game_id and self.ttt_player_to_game_id[nm] == game_id:
                        del self.ttt_player_to_game_id[nm]
                if game_id in self.ttt_games:
                    del self.ttt_games[game_id]

            else:
                self._send_error(from_sock, "unknown action")

# ==============================================================================
#                 the "from" guy really, really has had enough
# ==============================================================================

        else:
            # client died unexpectedly
            self.logout(from_sock)

# ==============================================================================
# main loop, loops *forever*
# ==============================================================================
    def run(self):
        try:
            while(1):
                read, write, error = select.select(self.all_sockets, [], [])
                for logc in list(self.logged_name2sock.values()):
                    if logc in read:
                        self.handle_msg(logc)
                for newc in self.new_clients[:]:
                    if newc in read:
                        self.login(newc)
                if self.server in read:
                    # new client request
                    sock, address = self.server.accept()
                    self.new_client(sock)
        except KeyboardInterrupt:
            pass
        finally:
            for sock in list(self.all_sockets):
                try:
                    sock.close()
                except Exception:
                    pass
            self.all_sockets = []


def main():
    server = Server()
    server.run()


if __name__ == '__main__':
    main()
