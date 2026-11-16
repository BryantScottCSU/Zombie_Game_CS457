#!/usr/bin/env python3
"""Zombie House game client.

A background thread reads newline-delimited JSON frames from the server and
queues them; the main thread draws the board and reads commands when it is
this player's turn.

Usage:
    python3 client.py -i server.scott.edu -p 8080
"""

import argparse
import os
import queue
import socket
import sys
import threading

from protocol import (
    ACT, CONNECT, DISCONNECT, ERROR, GAME_OVER, GAME_START, LOBBY_WAIT,
    STATE_UPDATE, LineReader, ProtocolError, decode_message, encode_message,
)

ZOMBIE = "zombie"
SURVIVOR = "survivor"
CONNECT_TIMEOUT = 10  # seconds
CELL_WIDTH = 7

ZOMBIE_HELP = """\
Zombie commands (each costs 1 move):
  spawn <lane>      Spawn a regular zombie at the far end of a lane (1-3)
  special <lane>    Spend 4 cash to spawn a special zombie (5 HP)
  cash              Bank this move toward a special zombie
  end               End your turn early (remaining moves are lost)
Other: help, board, quit"""

SURVIVOR_HELP = """\
Survivor commands (each costs 1 move):
  move <survivor> <lane>   Move survivor 1 or 2 to another window (lane 1-3)
  shoot <survivor>         Shoot the nearest zombie in that survivor's lane
  repair <survivor>        Repair +1 the window in that survivor's lane
  end                      End your turn early (remaining moves are lost)
Other: help, board, quit"""


# ---------------------------------------------------------------------- #
# Command-line arguments and connection setup
# ---------------------------------------------------------------------- #
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
        description="Zombie House client. Connects to a Zombie House server and plays "
                    "as the zombies or the survivors.",
        epilog="Example: python3 client.py -i server.scott.edu -p 8080",
    )
    parser.add_argument("-i", "--host", dest="hostname", metavar="HOSTNAME", required=True,
                        help="server DNS hostname (e.g. server.scott.edu)")
    parser.add_argument("-p", "--port", type=port_number, required=True,
                        help="server TCP port")
    return parser.parse_args(argv)


def resolve_hostname(hostname):
    """Resolve the server name via DNS, exiting cleanly (status 1) on failure."""
    try:
        return socket.gethostbyname(hostname)
    except (socket.gaierror, socket.herror, UnicodeError) as exc:
        print(f"[ERROR] Unable to resolve DNS hostname '{hostname}'.")
        print("Please check your Cisco router DNS configuration ('ip dns server' / 'ip host') "
              "or verify domain spelling.")
        print(f"        Details: {exc}")
        sys.exit(1)


def connect_to_server(server_ip, port, hostname):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT)
    try:
        sock.connect((server_ip, port))
    except ConnectionRefusedError:
        print(f"[ERROR] Connection refused by {hostname} ({server_ip}:{port}). "
              "Is server.py running on that port?")
        sys.exit(1)
    except socket.timeout:
        print(f"[ERROR] Timed out connecting to {hostname} ({server_ip}:{port}). "
              "Check routing between the subnets and any firewalls.")
        sys.exit(1)
    except OSError as exc:
        print(f"[ERROR] Could not connect to {hostname} ({server_ip}:{port}): {exc}")
        sys.exit(1)
    sock.settimeout(None)
    return sock


def ask(prompt):
    """input() that treats end-of-input like Ctrl+C."""
    try:
        return input(prompt)
    except EOFError:
        raise KeyboardInterrupt from None


# ---------------------------------------------------------------------- #
# Board rendering
# ---------------------------------------------------------------------- #
def clear_screen():
    if os.name == "nt":
        os.system("cls")
    else:
        print("\033[2J\033[H", end="")


def role_title(role):
    return "ZOMBIES" if role == ZOMBIE else "SURVIVORS"


def cell_text(zombies):
    regular = sum(1 for z in zombies if z["type"] == "regular")
    parts = []
    if regular:
        parts.append("z" if regular == 1 else f"{regular}z")
    parts.extend(f"Z{z['hp']}" for z in zombies if z["type"] == "special")
    text = " ".join(parts) or "."
    return text if len(text) <= CELL_WIDTH else text[:CELL_WIDTH - 1] + "+"


def window_text(window):
    if window["broken"]:
        return "[  ] OPEN"
    filled = "#" * window["health"] + "." * (window["max_health"] - window["health"])
    return f"[{filled}] {window['health']}/{window['max_health']}"


def render_board(state, my_role, player_id, opponent_name):
    depth = state["yard_depth"]
    lines = []
    bar = "=" * 78
    lines.append(bar)
    lines.append(f"  ZOMBIE HOUSE   |   Round {state['round']}/{state['max_rounds']}   |   "
                 f"You: {role_title(my_role)} ({player_id})   |   vs {opponent_name}")
    lines.append(bar)

    cols = [str(n) for n in range(depth, 0, -1)] + ["@WIN"]
    header = " " * 9 + "".join(c.center(CELL_WIDTH) for c in cols)
    lines.append(" " * 9 + "YARD  (zombies walk this way -->)".ljust(CELL_WIDTH * depth)
                 + "        WINDOW      HOUSE")
    lines.append(header)

    for window in state["windows"]:
        lane = window["lane"]
        cells = []
        for position in list(range(depth, 0, -1)) + [0]:
            here = [z for z in state["zombies"] if z["lane"] == lane and z["position"] == position]
            cells.append(cell_text(here).center(CELL_WIDTH))
        defenders = " ".join(f"S{s['id']}" for s in state["survivors"] if s["lane"] == lane)
        lines.append(f" Lane {lane} |" + "".join(cells) + f"| {window_text(window):<10} | {defenders}")

    lines.append("")
    lines.append(" Legend: z = zombie, 3z = three zombies, Z5 = special zombie with 5 HP, "
                 "S1/S2 = survivors")
    lines.append("-" * 78)

    stats = state["stats"]
    lines.append(f" SCORE  Zombies spawned: {stats['zombies_spawned']} "
                 f"(specials {stats['specials_spawned']})   Killed: {stats['zombies_killed']}   "
                 f"Shots: {stats['shots_fired']}   Repairs: {stats['repairs']}   "
                 f"Windows broken: {stats['windows_broken']}")
    lines.append(f"        Zombie cash: {state['zombie_cash']}/{state['special_cost']}   "
                 f"Rounds left after this one: {state['max_rounds'] - state['round']}")
    lines.append("-" * 78)
    lines.append(" Recent events:")
    for entry in state["log"][-5:]:
        lines.append(f"   {entry}")
    lines.append("-" * 78)

    if state["phase"] != "GAME_OVER":
        active = state["active_role"]
        if active == my_role:
            lines.append(f" >>> YOUR TURN ({role_title(my_role)}) - {state['moves_left']} move(s) left. "
                         "Type 'help' for commands.")
        else:
            lines.append(f" Waiting for {opponent_name} ({role_title(active)}) - "
                         f"{state['moves_left']} move(s) left...")
    clear_screen()
    print("\n".join(lines), flush=True)


# ---------------------------------------------------------------------- #
# Command parsing
# ---------------------------------------------------------------------- #
class CommandError(Exception):
    pass


def parse_number(token, name, low, high):
    try:
        value = int(token)
    except ValueError:
        raise CommandError(f"{name} must be a number from {low} to {high}.") from None
    if not low <= value <= high:
        raise CommandError(f"{name} must be from {low} to {high}.")
    return value


def parse_command(text, role, rules):
    """Turn a typed command into an ACT payload, or a local keyword string."""
    words = text.strip().lower().split()
    if not words:
        raise CommandError("Type a command, or 'help'.")
    cmd, args = words[0], words[1:]
    if cmd in ("help", "?", "h"):
        return "help"
    if cmd in ("quit", "exit", "q"):
        return "quit"
    if cmd in ("board", "b", "refresh"):
        return "board"
    if cmd in ("end", "pass"):
        return {"action": "end_turn"}

    lanes, survivors = rules["lanes"], rules["survivors"]
    if role == ZOMBIE:
        if cmd == "spawn" and len(args) == 1:
            return {"action": "spawn", "lane": parse_number(args[0], "Lane", 1, lanes)}
        if cmd == "special" and len(args) == 1:
            return {"action": "spawn_special", "lane": parse_number(args[0], "Lane", 1, lanes)}
        if cmd == "cash" and not args:
            return {"action": "cash"}
    else:
        if cmd == "move" and len(args) == 2:
            return {"action": "move",
                    "survivor": parse_number(args[0], "Survivor", 1, survivors),
                    "lane": parse_number(args[1], "Lane", 1, lanes)}
        if cmd in ("shoot", "repair") and len(args) == 1:
            return {"action": cmd, "survivor": parse_number(args[0], "Survivor", 1, survivors)}
    raise CommandError(f"Unrecognised command '{text.strip()}'. Type 'help' for commands.")


# ---------------------------------------------------------------------- #
# Client
# ---------------------------------------------------------------------- #
class GameClient:
    def __init__(self, sock, hostname):
        self.sock = sock
        self.hostname = hostname
        self.reader = LineReader(sock)
        self.inbox = queue.Queue()
        self.player_id = None
        self.role = None
        self.opponent_name = "opponent"
        self.rules = None
        self.state = None
        self.awaiting_input = False
        self.print_lock = threading.Lock()

    def send(self, msg_type, payload=None):
        data = encode_message(msg_type, payload, self.player_id, self.role)
        try:
            self.sock.sendall(data)
        except OSError:
            pass  # the reader thread will report the lost connection

    # Background thread ------------------------------------------------- #
    def reader_loop(self):
        try:
            while True:
                line = self.reader.read_line()
                if line is None:
                    break
                try:
                    message = decode_message(line)
                except ProtocolError:
                    continue  # ignore a garbled frame rather than crash
                if self.awaiting_input and message["msg_type"] == GAME_OVER:
                    # The user is sitting at a prompt; announce the result now.
                    self.show_game_over(message["payload"])
                    self.sock.close()
                    os._exit(0)
                self.inbox.put(message)
        except (OSError, ProtocolError):
            pass
        if self.awaiting_input:
            print("\n[ERROR] Lost connection to the server.", flush=True)
            os._exit(1)
        self.inbox.put(None)

    # Main thread ------------------------------------------------------- #
    def next_message(self):
        while True:
            try:
                return self.inbox.get(timeout=0.5)  # timeout keeps Ctrl+C responsive
            except queue.Empty:
                continue

    def run(self, player_name, preferred_role):
        threading.Thread(target=self.reader_loop, daemon=True).start()
        self.send(CONNECT, {"player_name": player_name, "preferred_role": preferred_role})
        print(f"Connected to {self.hostname}. Joining game...", flush=True)

        while True:
            message = self.next_message()
            if message is None:
                print("[ERROR] Lost connection to the server.")
                return 1
            msg_type, payload = message["msg_type"], message["payload"]

            if msg_type == LOBBY_WAIT:
                self.player_id = payload.get("player_id")
                self.role = payload.get("role")
                print(f"You are {self.player_id}, playing the {role_title(self.role)}.")
                print("Waiting for Player 2...", flush=True)

            elif msg_type == GAME_START:
                self.player_id = payload["player_id"]
                self.role = payload["role"]
                self.rules = payload["rules"]
                self.opponent_name = payload.get("opponent_name", "opponent")
                print(f"Game starting! You are the {role_title(self.role)}.", flush=True)

            elif msg_type == STATE_UPDATE:
                self.state = payload
                self.show_board()
                if self.is_my_turn():
                    self.take_turn()

            elif msg_type == ERROR:
                print(f"[SERVER] {payload.get('message', 'Unknown error')}", flush=True)
                if payload.get("fatal"):
                    return 1
                if self.is_my_turn():
                    self.take_turn()  # state is unchanged; try again

            elif msg_type == GAME_OVER:
                self.show_game_over(payload)
                return 0

    def is_my_turn(self):
        return (self.state is not None and self.state["phase"] != "GAME_OVER"
                and self.state["active_role"] == self.role)

    def show_board(self):
        with self.print_lock:
            render_board(self.state, self.role, self.player_id, self.opponent_name)

    def show_game_over(self, payload):
        with self.print_lock:
            final = payload.get("final_state")
            if final:
                render_board(final, self.role, self.player_id, self.opponent_name)
            winner = payload.get("winner")
            print()
            print("*" * 78)
            print(f"  GAME OVER - {role_title(winner)} WIN!")
            print(f"  {'You won!' if winner == self.role else 'You lost.'}  {payload.get('reason', '')}")
            print("*" * 78, flush=True)

    def take_turn(self):
        """Prompt until the player issues a valid command, then send one ACT."""
        help_text = ZOMBIE_HELP if self.role == ZOMBIE else SURVIVOR_HELP
        while True:
            self.awaiting_input = True
            try:
                text = ask(f"{self.role} ({self.state['moves_left']} moves left) > ")
            finally:
                self.awaiting_input = False
            try:
                command = parse_command(text, self.role, self.rules)
            except CommandError as exc:
                print(f"  {exc}")
                continue
            if command == "help":
                print(help_text)
            elif command == "board":
                self.show_board()
            elif command == "quit":
                raise KeyboardInterrupt
            else:
                self.send(ACT, command)
                return

    def disconnect(self):
        self.send(DISCONNECT, {"reason": "player quit"})
        try:
            self.sock.close()
        except OSError:
            pass


def prompt_setup():
    name = ask("Your name: ").strip() or "Player"
    while True:
        choice = ask("If you are the first to join, play as [z]ombies or [s]urvivors? ").strip().lower()
        if choice in ("z", "zombie", "zombies"):
            return name, ZOMBIE
        if choice in ("s", "survivor", "survivors"):
            return name, SURVIVOR
        print("  Please type z or s.")


def main(argv=None):
    args = parse_args(argv)
    server_ip = resolve_hostname(args.hostname)
    print(f"Resolved {args.hostname} -> {server_ip}")
    sock = connect_to_server(server_ip, args.port, args.hostname)

    client = GameClient(sock, args.hostname)
    try:
        name, role = prompt_setup()
        status = client.run(name, role)
    except KeyboardInterrupt:
        print("\nLeaving the game. Your opponent wins by forfeit.")
        client.disconnect()
        status = 0
    try:
        sock.close()
    except OSError:
        pass
    sys.exit(status)


if __name__ == "__main__":
    main()
