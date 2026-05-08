"""chat_server.py

Simple TCP chat server for the ICDS project. The server implements a
small JSON-based control protocol with framed messages (see chat_utils).

Key responsibilities:
- Accept new client sockets and perform a login/signup/forgot handshake
- Maintain mappings between logged-in usernames and their sockets
- Forward chat "exchange" messages between group members
- Persist per-user search indices and a simple JSON-backed user store

This module is intentionally lightweight for educational/demo use. It
avoids external frameworks and focuses on clarity.
"""

import time
import socket
import select
import indexer
import json
import pickle as pkl
import os
import hashlib
import logging
from logging.handlers import RotatingFileHandler
from chat_utils import *
import chat_group as grp


# Configure module logger with a rotating file and console output. This
# provides persistent logs under chat_server.log and reasonable defaults
# for interactive debugging. Users can adjust the level as needed.
logger = logging.getLogger('chat_server')
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    try:
        fh = RotatingFileHandler('chat_server.log', maxBytes=5 * 1024 * 1024, backupCount=3)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        # If file handler cannot be created (permission issues), continue with console only.
        logger.debug('Could not create RotatingFileHandler; continuing without file logging')


# Simple JSON-backed user store (demo only). Passwords are hashed with SHA-256.
# In a production system you should use a proper KDF (bcrypt/scrypt/PBKDF2) and
# per-user salts.
USERS_FILE = 'users.json'


def _load_users():
    """Load and return the users dictionary from USERS_FILE.

    Returns an empty dict if the file does not exist or cannot be parsed.
    The users dict maps usernames to a small dict with a "pw_hash" key.
    """
    try:
        if not os.path.exists(USERS_FILE):
            return {}
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        # If the file is unreadable, return an empty dict to allow new signups.
        return {}


def _save_users(users):
    """Persist the users dict to disk.

    Writes to a temporary file then atomically replaces USERS_FILE. This
    reduces risk of corrupting the store if the process is killed while
    writing.
    """
    try:
        tmp = USERS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=2)
        os.replace(tmp, USERS_FILE)
    except Exception:
        # Best-effort save; if it fails there's not much the server can do here.
        pass


def _hash_password(password):
    """Return the SHA-256 hex digest for the provided password.

    Security note: SHA-256 without a per-user salt and a slow KDF is NOT
    appropriate for production. This function exists for demo purposes
    only. Consider using bcrypt or hashlib.pbkdf2_hmac with a salt.
    """
    if password is None:
        password = ''
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def _generate_temp_password():
    """Generate an easy-to-copy temporary password.

    We use a 6-digit numeric code which is simple to type or paste. In a
    production system this would be delivered securely (email/SMS) and
    expire after a short time.
    """
    import random
    return "{:06d}".format(random.randint(0, 999999))


class Server:
    def __init__(self):
        self.new_clients = []  # list of new sockets of which the user id is not known
        self.logged_name2sock = {}  # dictionary mapping username to socket
        self.logged_sock2name = {}  # dict mapping socket to user name
        self.all_sockets = []
        self.group = grp.Group()
    # start server — bind/listen wrapped to give a clear error if the
    # configured address is already in use. We print a small startup
    # message to assist local debugging/tools that run the server.
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server.bind(SERVER)
            self.server.listen(5)
            self.all_sockets.append(self.server)
            logger.info(f"Server listening on {self.server.getsockname()}")
        except OSError as e:
            # Surface a helpful message for the operator and re-raise so
            # external supervisors/tests can handle the failure.
            logger.error(f"Failed to bind server on {SERVER}: {e}")
            raise
        # initialize past chat indices
        self.indices = {}
        # sonnet
        self.sonnet = indexer.PIndex("AllSonnets.txt")

    def new_client(self, sock):
        """Register a newly-accepted socket.

        New sockets are kept in the `new_clients` list until the client
        completes the login/signup/forgot handshake. We keep them in
        blocking mode because the handshake uses framed blocking reads.
        """
        self.new_clients.append(sock)
        self.all_sockets.append(sock)
        logger.debug(f"New client socket registered: {sock.fileno()}")

    def _drop_socket(self, sock):
        """Best-effort cleanup for sockets that are not fully logged in.

        This removes the socket from internal lists and closes it. It's
        used when a handshake fails or when unexpected exceptions occur
        while the socket is still unauthenticated.
        """
        if sock in self.new_clients:
            self.new_clients.remove(sock)
        if sock in self.all_sockets:
            self.all_sockets.remove(sock)
        try:
            sock.close()
        except Exception:
            pass
        logger.debug(f"Dropped socket: {getattr(sock, 'fileno', lambda: 'n/a')()}" )

    def _send_error(self, sock, reason):
        """Send a standardized error payload to a client socket.

        This is best-effort — network errors during error reporting are
        ignored because the connection is already in a bad state.
        """
        try:
            mysend(sock, json.dumps({"action": "error", "reason": reason}))
        except Exception:
            pass
        logger.debug(f"Sent error to socket {getattr(sock, 'fileno', lambda: 'n/a')()}: {reason}")

    def _safe_send(self, sock, text):
        """Send `text` to `sock` handling common connection errors.

        Returns True on success. On broken pipes or connection resets we
        attempt to log out the associated user. For all other exceptions
        we drop the socket as a best-effort cleanup.
        """
        try:
            mysend(sock, text)
            return True
        except (BrokenPipeError, ConnectionResetError) as e:
            # socket is dead — try to logout/cleanup
            logger.info(f"Broken connection when sending to socket {getattr(sock, 'fileno', lambda: 'n/a')()}: {e}")
            try:
                self.logout(sock)
            except Exception:
                pass
            return False
        except Exception as e:
            # best-effort: drop socket
            logger.exception(f"Unexpected error sending to socket {getattr(sock, 'fileno', lambda: 'n/a')()}")
            try:
                self._drop_socket(sock)
            except Exception:
                pass
            return False

    def login(self, sock):
        """Perform the initial login/signup/forgot handshake for `sock`.

        The client is expected to send a single framed JSON message with an
        "action" of one of: signup, forgot, or login. Signup/forgot are
        allowed before the client is considered authenticated.
        """
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
                        logger.info(f"Signup attempt for existing user: {name}")
                        return
                    users[name] = {"pw_hash": _hash_password(password)}
                    _save_users(users)
                    mysend(sock, json.dumps({"action": "signup", "status": "ok"}))
                    logger.info(f"Created new user: {name}")
                    return
                if action == "forgot":
                    name = msg.get("name", "").strip()
                    if not name:
                        mysend(sock, json.dumps({"action": "forgot", "status": "missing-fields"}))
                        return
                    users = _load_users()
                    if name not in users:
                        mysend(sock, json.dumps({"action": "forgot", "status": "no-match"}))
                        logger.info(f"Forgot request for unknown user: {name}")
                        return
                    import random
                    temp = "{:08d}".format(random.randint(0, 99999999))
                    users[name]["pw_hash"] = _hash_password(temp)
                    _save_users(users)
                    mysend(sock, json.dumps({"action": "forgot", "status": "ok", "temp": temp}))
                    logger.info(f"Issued temporary password for user: {name}")
                    return

                if msg["action"] == "login":
                    name = msg.get("name", "").strip()
                    password = msg.get("password", "")
                    # Verify account exists and password matches before
                    # accepting the login. This enforces the signup/login
                    # semantics introduced by the user account store.
                    users = _load_users()
                    if name not in users:
                        mysend(sock, json.dumps({"action": "login", "status": "no-account"}))
                        logger.info(f"Login attempt for unknown user: {name}")
                        return
                    # If password stored, verify hash matches
                    expected = users.get(name, {}).get("pw_hash")
                    if expected is not None and expected != _hash_password(password):
                        mysend(sock, json.dumps({"action": "login", "status": "bad-password"}))
                        logger.info(f"Bad password for user: {name}")
                        return
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
                        # load chat history of that user (if present)
                        if name not in self.indices.keys():
                            try:
                                self.indices[name] = pkl.load(
                                    open(name + '.idx', 'rb'))
                            except IOError:  # chat index does not exist, then create one
                                self.indices[name] = indexer.Index(name)
                        self.group.join(name)
                        mysend(sock, json.dumps(
                            {"action": "login", "status": "ok"}))
                        logger.info(f"User logged in: {name}")
                    else:  # a client under this name has already logged in
                        mysend(sock, json.dumps(
                            {"action": "login", "status": "duplicate"}))
                        logger.info(f"Duplicate login attempt for user: {name}")
                else:
                    self._drop_socket(sock)
            else:  # client died unexpectedly
                self.logout(sock)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.exception('Login handshake failed due to malformed message')
            self._drop_socket(sock)
        except Exception:
            logger.exception('Unexpected error during login handshake')
            self._drop_socket(sock)

    def logout(self, sock):
        """Log out the user associated with `sock` and cleanup.

        If the socket belonged to a logged-in user, their in-memory index
        is persisted to disk and internal mappings are cleaned up.
        """
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
        logger.debug(f"Logged out socket: {getattr(sock, 'fileno', lambda: 'n/a')()}")

# ==============================================================================
# main command switchboard
# ==============================================================================
    def handle_msg(self, from_sock):
        """Main per-client message dispatch.

        Called when a logged-in socket has data to read. Messages are JSON
        objects with an "action" key. This function validates the action
        and routes to the appropriate handler code blocks.
        """
        msg = myrecv(from_sock)
        if len(msg) > 0:
            # ==============================================================================
            # handle connect request this is implemented for you
            # ==============================================================================
            try:
                msg = json.loads(msg)
            except json.JSONDecodeError:
                self._send_error(from_sock, "invalid json")
                logger.debug(f"Invalid JSON from socket {getattr(from_sock, 'fileno', lambda: 'n/a')()}: {msg}")
                return

            action = msg.get("action")
            if not action:
                self._send_error(from_sock, "missing action")
                return

            # -------------------- connect --------------------
            if action == "connect":
                to_name = msg.get("target", "").strip()
                if not to_name:
                    self._send_error(from_sock, "missing connect target")
                    logger.debug(f"Connect with missing target from {getattr(from_sock, 'fileno', lambda: 'n/a')()}")
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
                            to_sock = self.logged_name2sock.get(g)
                            if to_sock:
                                self._safe_send(to_sock, json.dumps({"action": "connect", "status": "request", "from": from_name}))
                else:
                    msg = json.dumps(
                        {"action": "connect", "status": "no-user"})
                mysend(from_sock, msg)
                logger.debug(f"Connect response to {from_name}: {msg}")
            # -------------------- signup --------------------
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
                    logger.info(f"Signup attempt for existing user: {name}")
                    return
                users[name] = {"pw_hash": _hash_password(password)}
                _save_users(users)
                mysend(from_sock, json.dumps({"action": "signup", "status": "ok"}))
                logger.info(f"Created new user: {name}")
            # -------------------- forgot --------------------
            elif action == "forgot":
                # forgot expects name only; returns temp password
                name = msg.get("name", "").strip()
                if not name:
                    mysend(from_sock, json.dumps({"action": "forgot", "status": "missing-fields"}))
                    return
                users = _load_users()
                if name not in users:
                    mysend(from_sock, json.dumps({"action": "forgot", "status": "no-match"}))
                    logger.info(f"Forgot request for unknown user: {name}")
                    return
                # generate a temporary password (insecure but OK for demo)
                import random, string
                temp = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
                users[name]["pw_hash"] = _hash_password(temp)
                _save_users(users)
                mysend(from_sock, json.dumps({"action": "forgot", "status": "ok", "temp": temp}))
                logger.info(f"Issued temporary password for user: {name}")
# ==============================================================================
# handle messeage exchange: IMPLEMENT THIS
# ==============================================================================
            # -------------------- exchange --------------------
            # Broadcast an "exchange" message to all members the sender
            # is currently connected with. We also index the message for
            # the sender to support later search queries.
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
                # Index the message for the sender so it is searchable later.
                try:
                    self.indices[from_name].add_msg_and_index(line)
                except Exception:
                    logger.exception(f"Failed to index message for user: {from_name}")

                # ---- end of your code --- #

                the_guys = self.group.list_me(from_name)[1:]
                for g in the_guys:
                    to_sock = self.logged_name2sock[g]
                    sent_ok = self._safe_send(to_sock, json.dumps({
                        "action": "exchange",
                        "from": display_from,
                        "message": message
                    }))
                    if not sent_ok:
                        logger.info(f"Failed to forward exchange from {from_name} to {g}")

                    # ---- end of your code --- #

# ==============================================================================
# the "from" guy has had enough (talking to "to")!
# ==============================================================================
            # -------------------- disconnect --------------------
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
                    logger.debug(f"Notified {g} that others left the chat")
# ==============================================================================
#                 listing available peers: IMPLEMENT THIS
# ==============================================================================
            # -------------------- list --------------------
            # Return a list of all users (stringified). Kept simple for
            # the demo; could be improved to return structured JSON.
            elif action == "list":

                # IMPLEMENTATION
                # ---- start your code ---- #
                
                msg = str(self.group.list_all())
                logger.debug(f"List request from socket {getattr(from_sock, 'fileno', lambda: 'n/a')()}")

                # ---- end of your code --- #
                mysend(from_sock, json.dumps(
                    {"action": "list", "results": msg}))
            # file action removed
# ==============================================================================
#             retrieve a sonnet : IMPLEMENT THIS
# ==============================================================================
            # -------------------- poem --------------------
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
                logger.debug(f"Poem request handled for socket {getattr(from_sock, 'fileno', lambda: 'n/a')()}")
# ==============================================================================
#                 time
# ==============================================================================
            # -------------------- time --------------------
            elif action == "time":
                ctime = time.strftime('%d.%m.%y,%H:%M', time.localtime())
                mysend(from_sock, json.dumps(
                    {"action": "time", "results": ctime}))
                logger.debug(f"Time request from socket {getattr(from_sock, 'fileno', lambda: 'n/a')()}")
# ==============================================================================
#                 search: : IMPLEMENT THIS
# ==============================================================================
            # -------------------- search --------------------
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
                logger.debug(f"Search by {from_name} for '{target}' returned {len(hits)} hits")

                # ---- end of your code --- #
                mysend(from_sock, json.dumps(
                    {"action": "search", "results": search_rslt}))
            else:
                self._send_error(from_sock, "unknown action")
                logger.warning(f"Unknown action from socket {getattr(from_sock, 'fileno', lambda: 'n/a')()}: {action}")

# ==============================================================================
#                 the "from" guy really, really has had enough
# ==============================================================================

        else:
            # client died unexpectedly
            logger.info(f"Client socket disconnected: {getattr(from_sock, 'fileno', lambda: 'n/a')()}")
            self.logout(from_sock)

# ==============================================================================
# main loop, loops *forever*
# ==============================================================================
    def run(self):
        """Main server loop.

        Uses select to multiplex between the listening socket, new client
        sockets (awaiting login), and logged-in client sockets. The loop
        runs until the process receives a KeyboardInterrupt or the server
        socket is closed.
        """
        try:
            while True:
                read, write, error = select.select(self.all_sockets, [], [])
                # Handle messages from logged-in clients first
                for logc in list(self.logged_name2sock.values()):
                    if logc in read:
                        self.handle_msg(logc)
                # Handle handshake steps from new clients
                for newc in self.new_clients[:]:
                    if newc in read:
                        self.login(newc)
                # Accept new connections
                if self.server in read:
                    sock, address = self.server.accept()
                    self.new_client(sock)
        except KeyboardInterrupt:
            pass
        finally:
            # Persist any in-memory indices for logged-in users to disk
            try:
                for name in list(self.indices.keys()):
                    try:
                        pkl.dump(self.indices[name], open(name + '.idx', 'wb'))
                        logger.info(f"Persisted index for user: {name}")
                    except Exception:
                        logger.exception(f"Failed to persist index for user: {name}")
            except Exception:
                logger.exception('Error while persisting indices during shutdown')
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
