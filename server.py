#!/usr/bin/env python3
"""Zombie House game server.

Concurrency model (Sprint 2): one thread per client connection. All shared
match state (the player list and the ZombieHouseGame) is only read or changed
while holding GameServer.lock, so actions from the two clients are applied one
at a time and every broadcast reflects a consistent state.

Usage:
    python3 server.py -p 8080
"""

import argparse
import socket
import sys
import threading
import time

from game import (
    ROLES, ZOMBIE, ActionError, Phase, ZombieHouseGame, other_role,
)
from protocol import (
    ACT, CONNECT, DISCONNECT, ERROR, GAME_OVER, GAME_START, LOBBY_WAIT,
    STATE_UPDATE, FrameTooLargeError, LineReader, ProtocolError,
    decode_message, encode_message,
)

MAX_NAME_LENGTH = 20


def log(text):
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


def port_number(value):
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a number") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Zombie House game server. Hosts one 2-player match at a time "
                    "(zombies vs. survivors) using newline-delimited JSON over TCP.",
        epilog="Example: python3 server.py -p 8080",
    )
    parser.add_argument("-p", "--port", type=port_number, required=True,
                        help="TCP port to listen on (binds to 0.0.0.0)")
    return parser.parse_args(argv)


class PlayerConnection:
    """One connected client socket plus the identity the server assigned it."""

    def __init__(self, sock, address):
        self.sock = sock
        self.address = address
        self.send_lock = threading.Lock()
        self.closed = False
        self.player_id = None
        self.role = None
        self.name = None

    @property
    def label(self):
        who = self.player_id or "unjoined"
        return f"{who} ({self.name or '?'}, {self.role or 'no role'}) @ {self.address[0]}:{self.address[1]}"

    def send(self, msg_type, payload=None):
        data = encode_message(msg_type, payload)
        with self.send_lock:
            if self.closed:
                return False
            try:
                self.sock.sendall(data)
                return True
            except OSError:
                return False

    def close(self):
        with self.send_lock:
            if self.closed:
                return
            self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class GameServer:
    def __init__(self, port):
        self.port = port
        self.lock = threading.Lock()
        self.players = []   # PlayerConnections in the current match (0-2)
        self.game = None    # ZombieHouseGame once two players have joined
        self.match_number = 0

    @property
    def phase(self):
        return Phase.WAITING_FOR_PLAYERS if self.game is None else self.game.phase

    # ------------------------------------------------------------------ #
    # Accept loop
    # ------------------------------------------------------------------ #
    def serve_forever(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("0.0.0.0", self.port))
        except OSError as exc:
            print(f"[ERROR] Could not listen on port {self.port}: {exc}", file=sys.stderr)
            sys.exit(1)
        listener.listen(5)
        listener.settimeout(1.0)  # wake up periodically so Ctrl+C works on every OS
        log(f"Zombie House server listening on 0.0.0.0:{self.port} (Ctrl+C to stop)")

        try:
            while True:
                try:
                    sock, address = listener.accept()
                except socket.timeout:
                    continue
                sock.settimeout(None)
                conn = PlayerConnection(sock, address)
                log(f"Connection from {address[0]}:{address[1]}")
                threading.Thread(target=self.handle_client, args=(conn,), daemon=True).start()
        except KeyboardInterrupt:
            log("Shutting down.")
        finally:
            listener.close()
            with self.lock:
                for player in self.players:
                    player.send(ERROR, {"message": "The server is shutting down.", "fatal": True})
                    player.close()

    # ------------------------------------------------------------------ #
    # Per-client thread
    # ------------------------------------------------------------------ #
    def handle_client(self, conn):
        reader = LineReader(conn.sock)
        intentional = False
        try:
            while True:
                try:
                    line = reader.read_line()
                except FrameTooLargeError as exc:
                    conn.send(ERROR, {"message": str(exc), "fatal": True})
                    break
                if line is None:
                    break
                try:
                    message = decode_message(line)
                except ProtocolError as exc:
                    log(f"Bad frame from {conn.label}: {exc}")
                    conn.send(ERROR, {"message": str(exc)})
                    continue

                msg_type = message["msg_type"]
                if msg_type == CONNECT:
                    self.handle_connect(conn, message)
                elif msg_type == ACT:
                    self.handle_act(conn, message)
                elif msg_type == DISCONNECT:
                    intentional = True
                    break
                else:
                    conn.send(ERROR, {"message": f"Clients may not send {msg_type} messages."})
        except OSError:
            pass  # connection reset or closed by the server
        finally:
            self.handle_disconnect(conn, intentional)
            conn.close()

    # ------------------------------------------------------------------ #
    # Message handlers (each takes the lock for its whole check-and-update)
    # ------------------------------------------------------------------ #
    def handle_connect(self, conn, message):
        payload = message["payload"]
        with self.lock:
            if conn in self.players:
                conn.send(ERROR, {"message": "You have already joined."})
                return
            if self.game is not None or len(self.players) >= 2:
                conn.send(ERROR, {"message": "A match is already in progress. Please try again later.",
                                  "fatal": True})
                log(f"Rejected {conn.address[0]}:{conn.address[1]}: match in progress")
                conn.close()
                return

            name = str(payload.get("player_name") or "").strip()[:MAX_NAME_LENGTH]
            if not self.players:
                preferred = payload.get("preferred_role")
                conn.role = preferred if preferred in ROLES else ZOMBIE
                conn.player_id = "Player_1"
                conn.name = name or conn.player_id
                self.players.append(conn)
                log(f"{conn.label} joined; waiting for Player 2")
                conn.send(LOBBY_WAIT, {
                    "player_id": conn.player_id,
                    "role": conn.role,
                    "message": "Waiting for Player 2...",
                })
                return

            first = self.players[0]
            conn.role = other_role(first.role)
            conn.player_id = "Player_2"
            conn.name = name or conn.player_id
            self.players.append(conn)
            self.game = ZombieHouseGame()
            self.match_number += 1
            log(f"{conn.label} joined; match #{self.match_number} starting")

            for player, opponent in ((first, conn), (conn, first)):
                player.send(GAME_START, {
                    "player_id": player.player_id,
                    "role": player.role,
                    "opponent_name": opponent.name,
                    "opponent_role": opponent.role,
                    "rules": self.game.rules(),
                })
            self._broadcast(STATE_UPDATE, self.game.to_state())

    def handle_act(self, conn, message):
        with self.lock:
            if conn not in self.players:
                conn.send(ERROR, {"message": "Send CONNECT before ACT."})
                return
            if self.game is None:
                conn.send(ERROR, {"message": "The game has not started yet. Waiting for Player 2."})
                return
            # The connection decides who the sender is; claimed fields must match it.
            if message.get("player_id") != conn.player_id or message.get("player_role") != conn.role:
                conn.send(ERROR, {"message": f"Identity mismatch: this connection is "
                                             f"{conn.player_id} ({conn.role})."})
                return
            try:
                self.game.apply_action(conn.role, message["payload"])
            except ActionError as exc:
                conn.send(ERROR, {"message": str(exc), "moves_left": self.game.moves_left})
                return

            self._broadcast(STATE_UPDATE, self.game.to_state())
            if self.game.phase == Phase.GAME_OVER:
                log(f"Match #{self.match_number} over: {self.game.winner} win ({self.game.win_reason})")
                self._broadcast(GAME_OVER, self._game_over_payload())
                self._end_match()

    def handle_disconnect(self, conn, intentional):
        with self.lock:
            if conn not in self.players:
                return  # never joined, or the match already ended
            self.players.remove(conn)
            how = "left the game" if intentional else "lost connection"
            log(f"{conn.label} {how}")
            if self.game is None:
                return  # was waiting in the lobby; nothing else to clean up

            self.game.forfeit(conn.role, f"{conn.name} ({conn.role}) {how}. Their opponent wins by forfeit.")
            log(f"Match #{self.match_number} over: {self.game.winner} win by forfeit")
            self._broadcast(GAME_OVER, self._game_over_payload())
            self._end_match()

    # ------------------------------------------------------------------ #
    # Helpers (caller must hold self.lock)
    # ------------------------------------------------------------------ #
    def _broadcast(self, msg_type, payload):
        for player in self.players:
            player.send(msg_type, payload)

    def _game_over_payload(self):
        return {
            "winner": self.game.winner,
            "reason": self.game.win_reason,
            "final_state": self.game.to_state(),
        }

    def _end_match(self):
        """Release both players and reset to WAITING_FOR_PLAYERS for the next match."""
        for player in self.players:
            player.close()
        self.players = []
        self.game = None
        log("Resources released. Waiting for players for the next match.")


def main(argv=None):
    args = parse_args(argv)
    GameServer(args.port).serve_forever()


if __name__ == "__main__":
    main()
