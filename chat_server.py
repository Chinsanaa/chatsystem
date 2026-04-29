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

                if msg["action"] == "login":
                    name = msg["name"]
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
                # connect to the peer
                elif self.group.is_member(to_name):
                    if self.group.members.get(to_name) == grp.S_TALKING:
                        msg = json.dumps(
                            {"action": "connect", "status": "busy"})
                    else:
                        self.group.connect(from_name, to_name)
                        the_guys = self.group.list_me(from_name)
                        msg = json.dumps(
                            {"action": "connect", "status": "success"})
                        for g in the_guys[1:]:
                            to_sock = self.logged_name2sock[g]
                            mysend(to_sock, json.dumps(
                                {"action": "connect", "status": "request", "from": from_name}))
                else:
                    msg = json.dumps(
                        {"action": "connect", "status": "no-user"})
                mysend(from_sock, msg)
# ==============================================================================
# handle messeage exchange: IMPLEMENT THIS
# ==============================================================================
            elif action == "exchange":
                from_name = self.logged_sock2name[from_sock]
                message = msg.get("message")
                if not isinstance(message, str):
                    self._send_error(from_sock, "missing exchange message")
                    return
                """
                Finding the list of people to send to and index message
                """
                # IMPLEMENTATION
                # ---- start your code ---- #
                # Store each chat line in sender's searchable index.
                line = text_proc(message, from_name)
                self.indices[from_name].add_msg_and_index(line)

                # ---- end of your code --- #

                the_guys = self.group.list_me(from_name)[1:]
                for g in the_guys:
                    to_sock = self.logged_name2sock[g]

                    # IMPLEMENTATION
                    # ---- start your code ---- #
                    mysend(
                        to_sock, json.dumps({"action": "exchange", "from": from_name, "message": message}))

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