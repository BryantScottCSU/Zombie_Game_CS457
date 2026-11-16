"""Zombie House game rules and turn state machine.

This module has no networking code. The server owns one ZombieHouseGame per
match, calls apply_action() for every validated ACT message (while holding its
lock), and broadcasts to_state() to both clients afterwards.

Board layout (all numbers are 1-based in the protocol and on screen):
  * NUM_LANES lanes, each ending at one window of the house.
  * Each lane has YARD_DEPTH yard cells. Zombies spawn in cell YARD_DEPTH and
    walk one cell toward the house each round; position 0 means "at the window".
"""

NUM_LANES = 3
YARD_DEPTH = 5
WINDOW_MAX_HEALTH = 2
ZOMBIE_MOVES = 4
SURVIVOR_MOVES = 3
NUM_SURVIVORS = 2
MAX_ROUNDS = 20
SPECIAL_COST = 4          # cash needed to spawn a special zombie
REGULAR_HP = 1
SPECIAL_HP = 5
WINDOW_DAMAGE = 1         # damage each zombie at a window deals per advance
LOG_LENGTH = 8            # number of recent events sent to clients

ZOMBIE = "zombie"
SURVIVOR = "survivor"
ROLES = (ZOMBIE, SURVIVOR)

ZOMBIE_ACTIONS = ("spawn", "spawn_special", "cash", "end_turn")
SURVIVOR_ACTIONS = ("move", "shoot", "repair", "end_turn")


def other_role(role):
    return SURVIVOR if role == ZOMBIE else ZOMBIE


class Phase:
    """FSM states. WAITING_FOR_PLAYERS is used by the server before a game exists."""
    WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
    ZOMBIE_TURN = "ZOMBIE_TURN"
    SURVIVOR_TURN = "SURVIVOR_TURN"
    GAME_OVER = "GAME_OVER"


class ActionError(Exception):
    """An action that breaks the rules. The game state is left unchanged."""


class ZombieHouseGame:
    def __init__(self):
        self.phase = Phase.ZOMBIE_TURN
        self.round = 1
        self.active_role = ZOMBIE
        self.moves_left = ZOMBIE_MOVES
        self.cash = 0
        self.windows = {lane: WINDOW_MAX_HEALTH for lane in range(1, NUM_LANES + 1)}
        # Survivors start on the two outer lanes.
        self.survivors = {1: 1, 2: NUM_LANES}
        self.zombies = []
        self._next_zombie_id = 1
        self.winner = None
        self.win_reason = None
        self.log = []
        self.stats = {
            "zombies_spawned": 0,
            "specials_spawned": 0,
            "zombies_killed": 0,
            "shots_fired": 0,
            "repairs": 0,
            "windows_broken": 0,
        }
        self._log(f"Round 1 begins. Zombies have {ZOMBIE_MOVES} moves.")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def apply_action(self, role, payload):
        """Validate and apply one action. Raises ActionError if it is not allowed."""
        if self.phase == Phase.GAME_OVER:
            raise ActionError("The game is over.")
        if role != self.active_role:
            raise ActionError(f"It is the {self.active_role} player's turn.")
        if not isinstance(payload, dict):
            raise ActionError("ACT payload must be a JSON object.")

        action = payload.get("action")
        handlers = {
            ZOMBIE: {
                "spawn": self._spawn,
                "spawn_special": self._spawn_special,
                "cash": self._cash,
                "end_turn": self._noop,
            },
            SURVIVOR: {
                "move": self._move,
                "shoot": self._shoot,
                "repair": self._repair,
                "end_turn": self._noop,
            },
        }[role]
        handler = handlers.get(action)
        if handler is None:
            valid = ", ".join(handlers)
            raise ActionError(f"Unknown {role} action '{action}'. Valid actions: {valid}.")

        handler(payload)  # raises ActionError before changing anything if invalid

        if action == "end_turn":
            self._log(f"{role.capitalize()}s end their turn early.")
            self.moves_left = 0
        else:
            self.moves_left -= 1
        if self.moves_left == 0:
            self._end_turn()

    def forfeit(self, role, reason):
        """A player left; the other role wins immediately."""
        if self.phase == Phase.GAME_OVER:
            return
        self._game_over(other_role(role), reason)

    def to_state(self):
        return {
            "phase": self.phase,
            "round": self.round,
            "max_rounds": MAX_ROUNDS,
            "active_role": self.active_role,
            "moves_left": self.moves_left,
            "zombie_cash": self.cash,
            "special_cost": SPECIAL_COST,
            "lanes": NUM_LANES,
            "yard_depth": YARD_DEPTH,
            "windows": [
                {"lane": lane, "health": hp, "max_health": WINDOW_MAX_HEALTH, "broken": hp == 0}
                for lane, hp in self.windows.items()
            ],
            "survivors": [{"id": sid, "lane": lane} for sid, lane in self.survivors.items()],
            "zombies": [dict(z) for z in self.zombies],
            "stats": dict(self.stats),
            "log": list(self.log),
            "winner": self.winner,
            "win_reason": self.win_reason,
        }

    @staticmethod
    def rules():
        return {
            "lanes": NUM_LANES,
            "yard_depth": YARD_DEPTH,
            "window_max_health": WINDOW_MAX_HEALTH,
            "zombie_moves": ZOMBIE_MOVES,
            "survivor_moves": SURVIVOR_MOVES,
            "survivors": NUM_SURVIVORS,
            "max_rounds": MAX_ROUNDS,
            "special_cost": SPECIAL_COST,
            "regular_hp": REGULAR_HP,
            "special_hp": SPECIAL_HP,
        }

    # ------------------------------------------------------------------ #
    # Zombie actions
    # ------------------------------------------------------------------ #
    def _spawn(self, payload):
        lane = self._int_field(payload, "lane", 1, NUM_LANES)
        self._add_zombie(lane, "regular", REGULAR_HP)
        self.stats["zombies_spawned"] += 1
        self._log(f"A zombie appears at the edge of lane {lane}.")

    def _spawn_special(self, payload):
        lane = self._int_field(payload, "lane", 1, NUM_LANES)
        if self.cash < SPECIAL_COST:
            raise ActionError(f"A special zombie needs {SPECIAL_COST} cash (you have {self.cash}).")
        self.cash -= SPECIAL_COST
        self._add_zombie(lane, "special", SPECIAL_HP)
        self.stats["zombies_spawned"] += 1
        self.stats["specials_spawned"] += 1
        self._log(f"A SPECIAL zombie ({SPECIAL_HP} HP) appears in lane {lane}!")

    def _cash(self, payload):
        self.cash += 1
        self._log(f"Zombies bank a move ({self.cash}/{SPECIAL_COST} toward a special).")

    # ------------------------------------------------------------------ #
    # Survivor actions
    # ------------------------------------------------------------------ #
    def _move(self, payload):
        sid = self._int_field(payload, "survivor", 1, NUM_SURVIVORS)
        lane = self._int_field(payload, "lane", 1, NUM_LANES)
        if self.survivors[sid] == lane:
            raise ActionError(f"Survivor {sid} is already at window {lane}.")
        self.survivors[sid] = lane
        self._log(f"Survivor {sid} moves to window {lane}.")

    def _shoot(self, payload):
        sid = self._int_field(payload, "survivor", 1, NUM_SURVIVORS)
        lane = self.survivors[sid]
        targets = [z for z in self.zombies if z["lane"] == lane]
        if not targets:
            raise ActionError(f"Survivor {sid} has no zombie to shoot in lane {lane}.")
        # Nearest zombie first; ties go to the one that has been there longest.
        target = min(targets, key=lambda z: (z["position"], z["id"]))
        target["hp"] -= 1
        self.stats["shots_fired"] += 1
        if target["hp"] <= 0:
            self.zombies.remove(target)
            self.stats["zombies_killed"] += 1
            self._log(f"Survivor {sid} kills a {target['type']} zombie in lane {lane}.")
        else:
            self._log(f"Survivor {sid} hits the special zombie in lane {lane} ({target['hp']} HP left).")

    def _repair(self, payload):
        sid = self._int_field(payload, "survivor", 1, NUM_SURVIVORS)
        lane = self.survivors[sid]
        hp = self.windows[lane]
        if hp == 0:
            raise ActionError(f"Window {lane} is broken and can no longer be repaired.")
        if hp >= WINDOW_MAX_HEALTH:
            raise ActionError(f"Window {lane} is already at full health.")
        self.windows[lane] = hp + 1
        self.stats["repairs"] += 1
        self._log(f"Survivor {sid} repairs window {lane} ({hp + 1}/{WINDOW_MAX_HEALTH}).")

    def _noop(self, payload):
        pass

    # ------------------------------------------------------------------ #
    # Turn / round transitions
    # ------------------------------------------------------------------ #
    def _end_turn(self):
        if self.active_role == ZOMBIE:
            self._advance_zombies()
            if self.phase == Phase.GAME_OVER:
                return
            self.phase = Phase.SURVIVOR_TURN
            self.active_role = SURVIVOR
            self.moves_left = SURVIVOR_MOVES
            self._log(f"Survivors' turn: {SURVIVOR_MOVES} moves.")
        else:
            if self.round >= MAX_ROUNDS:
                self._game_over(SURVIVOR, f"The survivors held out for {MAX_ROUNDS} rounds. Rescue arrives at dawn!")
                return
            self.round += 1
            self.phase = Phase.ZOMBIE_TURN
            self.active_role = ZOMBIE
            self.moves_left = ZOMBIE_MOVES
            self._log(f"Round {self.round} begins. Zombies have {ZOMBIE_MOVES} moves.")

    def _advance_zombies(self):
        """All zombies step toward the house, then windows are attacked and checked."""
        for z in self.zombies:
            if z["position"] > 0:
                z["position"] -= 1
                if z["position"] == 0:
                    self._log(f"A {z['type']} zombie reaches window {z['lane']}!")
        if self.zombies:
            self._log("The horde shambles forward.")

        for lane in range(1, NUM_LANES + 1):
            at_window = [z for z in self.zombies if z["lane"] == lane and z["position"] == 0]
            if not at_window:
                continue
            # Intact windows take damage, including on the turn a zombie arrives.
            if self.windows[lane] > 0:
                new_hp = max(0, self.windows[lane] - WINDOW_DAMAGE * len(at_window))
                self.windows[lane] = new_hp
                if new_hp == 0:
                    self.stats["windows_broken"] += 1
                    self._log(f"Window {lane} is SMASHED open!")
                else:
                    self._log(f"Window {lane} is damaged ({new_hp}/{WINDOW_MAX_HEALTH}).")
            # A zombie at an open window either dies to a defender or gets in.
            if self.windows[lane] == 0:
                defenders = [sid for sid, l in self.survivors.items() if l == lane]
                if defenders:
                    for z in at_window:
                        self.zombies.remove(z)
                        self.stats["zombies_killed"] += 1
                    self._log(f"Survivor {defenders[0]} kills {len(at_window)} zombie(s) climbing through window {lane}.")
                else:
                    self._game_over(ZOMBIE, f"A zombie climbed through the undefended window in lane {lane}!")
                    return

    def _game_over(self, winner, reason):
        self.phase = Phase.GAME_OVER
        self.winner = winner
        self.win_reason = reason
        self.moves_left = 0
        self._log(reason)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _add_zombie(self, lane, ztype, hp):
        self.zombies.append({
            "id": self._next_zombie_id,
            "lane": lane,
            "position": YARD_DEPTH,
            "type": ztype,
            "hp": hp,
        })
        self._next_zombie_id += 1

    @staticmethod
    def _int_field(payload, name, low, high):
        value = payload.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ActionError(f"'{name}' must be a whole number from {low} to {high}.")
        if not low <= value <= high:
            raise ActionError(f"'{name}' must be from {low} to {high} (got {value}).")
        return value

    def _log(self, text):
        self.log.append(f"R{self.round}: {text}")
        del self.log[:-LOG_LENGTH]
