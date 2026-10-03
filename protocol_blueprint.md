## 2. Application-Layer Messaging Protocol Blueprint (Sprint 1 Deliverable)

### 2.1 Message Transport & Serialization Format
- **Transport Protocol:** TCP
- **Serialization Format:** JSON
- **Framing Mechanism:** Newline-delimited

### 2.2 Message Schema Definitions

#### Message Types:
1. `CONNECT` (Client -> Server): Request to join the game room.
2. `LOBBY_WAIT` (Server -> Client): Notification that server is waiting for Player 2.
3. `GAME_START` (Server -> Clients): Game initiated, assigns roles, first player to connect selects role, second player gets other role.
4. `ACT` (Client -> Server): Player action. Different for each role. Both roles send an act message with details of the moves they made.
5. `STATE_UPDATE` (Server -> Clients): Broadcast current game board / state and active player turn.
6. `GAME_OVER` (Server -> Clients): Victory / Draw notification.
7. `DISCONNECT` (Client -> Server): A player has chosen to disconnect, their opponent wins the game.
8. `ERROR` (Server -> Client): Invalid move or malformed packet error.

#### Example JSON Protocol Schema:
```json

{
  "msg_type": "ACT",
  "player_id": "Player_1",
  "player_role": "zombie"
  "payload": {
    "spawn_rows": [1, 3],
    "spawn": 2
    "cash": 2
  },
  "timestamp": 1727000000
}
{
  "msg_type": "ACT",
  "player_id": "Player_1",
  "player_role": "survivor",
  "payload": {
    "move_survivor_1": 1
    "move_survior_2": 0
    "shoot_survior_1": 1
    "shoot_survior_1": 0
    "repair_survivor_1": 0
    repair_survivor_2": 1
  },
  "timestamp": 1727000000
}
