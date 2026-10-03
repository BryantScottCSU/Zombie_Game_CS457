Prompts for creating FSM flowchart in Mermaid.ai

Prompt 1 (giving it the current technical spec I had made up to that point, and explaining the game in english from the server perspective: ### 1.1 Game Overview - 
**Chosen Game:** Zombie House - **Player Capacity:** 2 Players (Simulated via 2 CML Client nodes) - **Game Summary:** One player controls survivors in a house, another a horde of 
zombies trying to get in. The players must survive until dawn to be rescued! ### 1.2 Core Game Rules & Win/Draw Conditions - **Turn Mechanics:** Each round the players both get one turn, 
starting with the zombies. The zombies have a set number of moves (4 as of now I have not play tested yet, this may change), and can spawn zombies, move zombies, or 'cash' moves to spawn a special 
zombie later. The survior player then gets their moves, less than the zombies (at this time I'm thinking 3). They can repair barricades, shoot out a window at a zombie on a certain lane, or 
change lanes (each window has its own lane, like plants vs zombies). - **Victory Condition:** The zombies win if a window is climbed through. If a window is broken and a zombie reaches it, 
they climb through and win, unless a survior is there, in which case the zombie is killed automatically. The survivors win if they survive enough rounds, say 15 (WIP may change during playtesting). 
- **Draw/Tie Condition:** I do not think a draw is possible given the above rules. --- ## 2. Application-Layer Messaging Protocol Blueprint (Sprint 1 Deliverable) ### 2.1 Message Transport & Serialization Format
- - **Transport Protocol:** TCP - **Serialization Format:** Structured JSON - **Framing Mechanism:** Newline-Delimited JSON ### 2.2 Message Schema Definitions #### Message Types: 1. CONNECT (Client -> Server):
  - Request to join the game room. 2. LOBBY_WAIT (Server -> Client): Notification that server is waiting for Player 2. 3. GAME_START (Server -> Clients): Game initiated, assigns roles
  - (First player to connect chooses role). 4. ACT (Client -> Server): Player action, role dependent, for survivors: Shoot, repair, move. For Zombies: spawn zombie, cash zombie, spawn special.
  - 5. STATE_UPDATE (Server -> Clients): Broadcast current game board / state and active player turn. 6. GAME_OVER (Server -> Clients): Victory / Draw notification with final scores.
    6. 7. ERROR (Server -> Client): Invalid move or malformed packet error. #### Example JSON Protocol Schema:
    8. ```json { "msg_type": "ACT", "player_id": "Player_1", "player_role": "zombie" "payload": { "spawn_rows": [1, 3], "cash": 2 }, "timestamp": 1727000000 }
    { "msg_type": "ACT", "player_id": "Player_1", "player_role": "survivor", "payload": { "move_survivor_1": 1 "move_survior_2": 0 "shoot_survior_1": 1 "shoot_survior_1": 0 "repair_survivor_1": 0 repair_survivor_2": 1 }, "timestamp": 1727000000 }
    The idea of the game: The zombie player moves first, the human second each round. The house the humans are in has 3 windows, the yard has 3 rows. The zombies automatically advance 1 space each round,
    and the zombie player can spawn zombies or cash them to save for a special zombie, which it can spawn once its cashed 4 regular zombies. The humans can repair windows, which have 2 health each, or shoot,
    or move to another window. There are only 2 survivors. A regular zombie dies to 1 shot, a special to 5. The zombies get 4 moves per round, the humans 3. If the humans survive 20 rounds they win.
    If a zombie reaches a window, it takes damage each turn including the turn where the zombie reaches it. If the window is broken and a zombie reaches it and a human is standing on the lane the window occupies,
    the zombie dies (no move cost to the human team). The window can no longer be repaired. If a zombie reaches the window and no human is there, the zombies win.

Prompt 2, adding more server related functions explicitly, ensuring the chart shows the handling of disconnects: We must add to this. If a player disconnects intentionally, using an DISCONNECT 
command, the opponent wins automatically. The server will then reclaim the resources used for hosting each player. Refer again to the detailed SOW I included at the beginning of my first message 
for more info about how the game is structured and how the server will work.

Prompt 3, Adding the same logic for unexpected client drops: Now handle unexpected disconnects the same way
