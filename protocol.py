"""Zombie House wire protocol: newline-delimited JSON over TCP.

Every message is one JSON object on one line, terminated by "\\n":

    {"msg_type": "ACT", "player_id": "Player_1", "player_role": "zombie",
     "payload": {"action": "spawn", "lane": 2}, "timestamp": 1727000000}

json.dumps() escapes any newline inside strings, so a raw "\\n" byte can only
appear as the frame terminator.
"""

import json
import time

ENCODING = "utf-8"
MAX_MESSAGE_BYTES = 64 * 1024  # a frame larger than this is rejected

# Client -> Server
CONNECT = "CONNECT"
ACT = "ACT"
DISCONNECT = "DISCONNECT"
# Server -> Client(s)
LOBBY_WAIT = "LOBBY_WAIT"
GAME_START = "GAME_START"
STATE_UPDATE = "STATE_UPDATE"
GAME_OVER = "GAME_OVER"
ERROR = "ERROR"

CLIENT_MESSAGES = (CONNECT, ACT, DISCONNECT)
SERVER_MESSAGES = (LOBBY_WAIT, GAME_START, STATE_UPDATE, GAME_OVER, ERROR)
ALL_MESSAGES = CLIENT_MESSAGES + SERVER_MESSAGES


class ProtocolError(Exception):
    """A frame that is not valid protocol (bad JSON, wrong shape, unknown type)."""


class FrameTooLargeError(ProtocolError):
    """The peer sent more than MAX_MESSAGE_BYTES without a newline."""


def build_message(msg_type, payload=None, player_id=None, player_role=None):
    message = {"msg_type": msg_type}
    if player_id is not None:
        message["player_id"] = player_id
    if player_role is not None:
        message["player_role"] = player_role
    message["payload"] = payload if payload is not None else {}
    message["timestamp"] = int(time.time())
    return message


def encode_message(msg_type, payload=None, player_id=None, player_role=None):
    """Return the framed bytes for one message."""
    message = build_message(msg_type, payload, player_id, player_role)
    return (json.dumps(message, separators=(",", ":")) + "\n").encode(ENCODING)


def decode_message(line):
    """Parse one frame (without its newline). Raises ProtocolError if invalid."""
    try:
        message = json.loads(line.decode(ENCODING))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Malformed message (not valid JSON): {exc}") from None
    if not isinstance(message, dict):
        raise ProtocolError("Malformed message: expected a JSON object.")
    msg_type = message.get("msg_type")
    if msg_type not in ALL_MESSAGES:
        raise ProtocolError(f"Unknown msg_type: {msg_type!r}.")
    payload = message.setdefault("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("Malformed message: 'payload' must be a JSON object.")
    return message


class LineReader:
    """Reassembles newline-delimited frames from a TCP byte stream.

    TCP may split one message across several recv() calls or deliver several
    messages in one call; this buffers bytes until a full line is available.
    """

    def __init__(self, sock):
        self.sock = sock
        self.buffer = bytearray()

    def read_line(self):
        """Return the next frame as bytes, or None when the peer closes the connection."""
        while True:
            newline = self.buffer.find(b"\n")
            if newline != -1:
                line = bytes(self.buffer[:newline])
                del self.buffer[:newline + 1]
                if line.strip():
                    return line
                continue  # ignore blank lines
            if len(self.buffer) > MAX_MESSAGE_BYTES:
                raise FrameTooLargeError(f"Message exceeds {MAX_MESSAGE_BYTES} bytes.")
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self.buffer.extend(chunk)
