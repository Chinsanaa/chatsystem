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

    def new_client(self, sock):
        # add to all sockets and to new clients
        # Keep new sockets in blocking mode so the initial login handshake
        # (which uses myrecv and expects blocking sockets) works reliably.
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

    def _safe_send(self, sock, text):
        """Send text to sock, but handle broken pipes / closed sockets gracefully."""
        try:
            mysend(sock, text)
            return True
        except (BrokenPipeError, ConnectionResetError):
            # socket is dead — try to logout/cleanup
            try:
                self.logout(sock)
            except Exception:
                pass
            return False
        except Exception:
            # best-effort: drop socket
            try:
                self._drop_socket(sock)
            except Exception:
                pass
            return False

    def login(self, sock):
        # read the msg that should have login code plus username
        try:
            msg = json.loads(myrecv(sock))
            if len(msg) > 0:

                action = msg.get("action")
                # Allow signup/forgot during initial handshake (before login)
                if action == "signup":
                    name = msg.get("name", "").strip()
                    password = msg.get("password", "")
                    if not name or not password:
                        mysend(sock, json.dumps({"action": "signup", "status": "missing-fields"}))
                        return
                    users = _load_users()
                    if name in users:
                        mysend(sock, json.dumps({"action": "signup", "status": "exists"}))
                        return
                    users[name] = {"pw_hash": _hash_password(password)}
                    _save_users(users)
                    mysend(sock, json.dumps({"action": "signup", "status": "ok"}))
                    return
                if action == "forgot":
                    name = msg.get("name", "").strip()
                    if not name:
                        mysend(sock, json.dumps({"action": "forgot", "status": "missing-fields"}))
                        return
                    users = _load_users()
                    if name not in users:
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
                        # ensure the socket is in blocking mode for myrecv
                        try:
                            sock.setblocking(1)
                        except Exception:
                            pass
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
                                self._safe_send(to_sock, json.dumps({"action": "connect", "status": "request", "from": from_name}))
                else:
                    msg = json.dumps({"action": "connect", "status": "no-user"})
                mysend(from_sock, msg)
            elif action == "signup":
                # signup expects name and password (email removed)
                name = msg.get("name", "").strip()
                password = msg.get("password", "")
                if not name or not password:
                    mysend(from_sock, json.dumps({"action": "signup", "status": "missing-fields"}))
                    return
                users = _load_users()
                if name in users:
                    mysend(from_sock, json.dumps({"action": "signup", "status": "exists"}))
                    return
                users[name] = {"pw_hash": _hash_password(password)}
                _save_users(users)
                mysend(from_sock, json.dumps({"action": "signup", "status": "ok"}))
            elif action == "forgot":
                # forgot expects name only; returns temp password
                name = msg.get("name", "").strip()
                if not name:
                    mysend(from_sock, json.dumps({"action": "forgot", "status": "missing-fields"}))
                    return
                users = _load_users()
                if name not in users:
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
                    self._safe_send(to_sock, json.dumps({
                        "action": "exchange",
                        "from": display_from,
                        "message": message
                    }))

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
            # file action removed
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
