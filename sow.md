# CS 457 Project Statement of Work (SOW) & Protocol Specification Template

**Student Name:** Conner Scott
**Date:** 9/20/2026
**Course:** CS 457 - Computer Networks  
**Target Server Domain:** `server.scott.edu`  

---

## 1. Game Selection & Scope (Sprint 0)

> Planning is going to be an iterative process through the sprints so you don't have to have all the details now. Focus on big overview concepts. You will be updating the SOW as we plan.
> You have a lot of freedom to choose a game. There are a couple caveats.  

> - It must run in the console. The lab nodes won't be able to handle extensive graphics.
> - It has to be self-contained. You can use a internet-connector to download you code, but because the architecture must run 5 nodes you won't be able to run 
> - You are encouraged to use python, but I'm not going to make it a strict requirement. The instructor and TA's ability to help with C or Rust, etc will be diminished in other languages.

### 1.1 Game Overview
- **Chosen Game:** Zombie House
- **Player Capacity:** 2 Players (Simulated via 2 CML Client nodes)
- **Game Summary:** One player controls survivors in a house, another a horde of zombies trying to get in. The players must survive until dawn to be rescued!

### 1.2 Core Game Rules & Win/Draw Conditions
- **Turn Mechanics:** Each round the players both get one turn, starting with the zombies. The zombies have a set number of moves (4 as of now I have not play tested yet, this may change), and can spawn zombies, move zombies, or 'cash' moves to spawn a special zombie later. The survior player then gets their moves, less than the zombies (at this time I'm thinking 3). They can repair barricades, shoot out a window at a zombie on a certain lane, or change lanes (each window has its own lane, like plants vs zombies). 
- **Victory Condition:** The zombies win if a window is climbed through. If a window is broken and a zombie reaches it, they climb through and win, unless a survior is there, in which case the zombie is killed automatically. The survivors win if they survive enough rounds, say 15 (WIP may change during playtesting). 
- **Draw/Tie Condition:** I do not think a draw is possible given the above rules.

---

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
7. `ERROR` (Server -> Client): Invalid move or malformed packet error.

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
```

---

### 2.3 Game State Machine (FSM) Design (Sprint 1 Deliverable)
- **State Transitions:** <img width="3901" height="8192" alt="Zombie Survival Action Flow-2026-10-03-191201" src="https://github.com/user-attachments/assets/f7ad3bae-4f26-4853-8864-6f48c8907341" />



---

## 3. Game Behavior & Server Concurrency Architecture (Sprint 2 Deliverable)

### 3.1 Server Concurrency Strategy
- **Architecture Choice:** Multi-Threading (`threading.Thread`) - I have chosen multi threading. The coding is simpler, and while it is less scalable, I only need 2 players at a time and simple turn based mechanics. 
- **Synchronization Logic:** To prevent race conditions and maintain state between turns, threading.lock will be used. This will allow us to mutate the gamestate safely. Since both players take their turn one at a time, state management should be simple, and easier to implement using multi threading. 

### 3.2 State & Score Synchronization Across Clients
- **Turn Enforcement:** Detail how the server validates active player ID before processing moves and broadcasts updated turn notifications to all clients.
- **Score & Board Synchronization:** Describe how state broadcasts keep client screens synchronized in real time.

```mermaid
sequenceDiagram
    participant Z as Zombie Client
    participant S as Authoritative Server
    participant H as Survivor Client

    Note over Z,H: TCP with newline-delimited JSON<br/>Server owns board state, round, active role, and move budgets
    S-->>Z: GAME_START — role: zombie
    S-->>H: GAME_START — role: survivor

    loop Each round while match is active — maximum 20 rounds
        Note over Z,H: Disconnect handling interrupts any phase below
        
        break Disconnect or Connection Loss
            S->>S: Stop processing actions and declare opponent winner
            S-->>Z: GAME_OVER if still connected
            S-->>H: GAME_OVER if still connected
            S->>S: Close connections and release player and match resources
        end

        S->>S: Set active role to zombie; grant 4 moves
        S-->>Z: STATE_UPDATE — board, round, active role, moves remaining
        S-->>H: STATE_UPDATE — same authoritative state

        loop Until 4 zombie moves are spent or match finishes
            Z->>S: ACT — spawn regular, cash move, or spawn special
            S->>S: Parse complete JSON line and validate required fields
            S->>S: Verify player identity against connection and assigned role
            S->>S: Check match active, zombie turn, and remaining move budget
            S->>S: Validate action, target lane, and parameters
            Note right of S: Special spawn requires 4 saved cash<br/>Cash action saves toward a special zombie
            alt Any validation fails
                S-->>Z: ERROR — validation reason
                Note right of S: Keep board, cash, and move budget unchanged<br/>Do not broadcast a state change
            else All checks pass
                S->>S: Apply action and deduct move cost atomically
                S->>S: Update authoritative board and cash balance
                S-->>Z: STATE_UPDATE — complete updated state
                S-->>H: STATE_UPDATE — identical state snapshot
                Note over Z,H: Both clients replace their displayed state<br/>with the server snapshot
            end
            opt Survivor submits ACT during zombie turn
                H->>S: ACT
                S-->>H: ERROR — not your turn
                Note right of S: No state change or move consumed
            end
        end

        S->>S: Advance zombies 1 space and resolve window damage and entry
        Note right of S: A survivor guarding a broken window kills arriving zombies<br/>Broken windows cannot be repaired
        
        break Zombie enters broken window unguarded
            S-->>Z: GAME_OVER — zombies win
            S-->>H: GAME_OVER — zombies win
            S->>S: Release player and match resources
        end

        S->>S: Set active role to survivor; grant 3 moves
        S-->>Z: STATE_UPDATE — resolved board, round, active role, moves remaining
        S-->>H: STATE_UPDATE — same authoritative state

        loop Until 3 survivor moves are spent
            H->>S: ACT — shoot, repair, or move survivor
            S->>S: Parse complete JSON line and validate required fields
            S->>S: Verify player identity against connection and assigned role
            S->>S: Check match active, survivor turn, and remaining move budget
            S->>S: Validate survivor, action, target, and lane constraints
            Note right of S: Shoot requires a valid zombie in the survivor's lane<br/>Repair requires an unbroken window below 2 health<br/>Move requires a valid destination window
            alt Any validation fails
                S-->>H: ERROR — validation reason
                Note right of S: Keep board and move budget unchanged<br/>Do not broadcast a state change
            else All checks pass
                S->>S: Apply action and deduct move cost atomically
                S->>S: Update survivor positions, window health, or zombie health
                Note right of S: Regular zombie dies after 1 shot<br/>Special zombie dies after 5 shots
                S-->>Z: STATE_UPDATE — complete updated state
                S-->>H: STATE_UPDATE — identical state snapshot
            end
            opt Zombie submits ACT during survivor turn
                Z->>S: ACT
                S-->>Z: ERROR — not your turn
                Note right of S: No state change or move consumed
            end
        end

        alt Round 20 completed
            S-->>Z: GAME_OVER — survivors win
            S-->>H: GAME_OVER — survivors win
            S->>S: Release player and match resources
        else More rounds remain
            S->>S: Increment round; return turn to zombies
        end
    end
```
--- 

## 4. Coding & AI Implementation Plan (Sprint 3)

- **Permitted AI Tools:** [e.g., GitHub Copilot, ChatGPT, Claude]
- **AI Prompting & Constraint Strategy:** Explain how you will constrain AI models to generate code (in Python or your chosen language) that adheres strictly to the protocol blueprint and FSM designed in Sprints 1 & 2.
- **Implementation Risk Management:** Detail your plan to leverage past programming experience and manage time to ensure code completion on schedule.

---

## 5. CML Multi-Subnet Topology & Wireshark Deployment Plan (Sprint 4 & 5 Deliverable)

> For now you can use the topology below. We may update this when we get to defining subnets.

### 5.1 Subnet & Router Design
- **Subnet A (Client 1):** `192.168.10.0/24` (Interface `Gi0/1` on Router R1)
- **Subnet B (Client 2):** `192.168.11.0/24` (Interface `Gi0/2` on Router R1)
- **Subnet C (Game Server):** `192.168.20.0/24` (Interface `Gi0/1` on Router R2)
- **Router Backbone:** `10.0.0.0/30` (Interface `Gi0/0` on R1 <-> `Gi0/0` on R2)

### 5.2 DHCP Pools & DNS Configuration Plan
- **Router R1 DHCP Pool 1 (`CLIENT1_POOL`):** Leases `192.168.10.10` - `192.168.10.50`, gateway `192.168.10.1`, DNS `10.0.0.2`.
- **Router R1 DHCP Pool 2 (`CLIENT2_POOL`):** Leases `192.168.11.10` - `192.168.11.50`, gateway `192.168.11.1`, DNS `10.0.0.2`.
- **Router R2 Authoritative DNS:** Configured with `ip dns server` and static host mapping `server.[yourlastname].edu` -> `192.168.20.100`.

### 5.3 Deployment Strategy & Wireshark Trace Capture
- **CML Deployment Strategy:** Deploy `server.py` onto Subnet C node (`192.168.20.100`) behind Router R2, and `client.py` onto Subnet A and Subnet B nodes behind Router R1.
- **Cisco Infrastructure Configuration:** Router R1 DHCP pools (`CLIENT1_POOL`, `CLIENT2_POOL`) and Router R2 authoritative DNS (`ip host server.[lastname].edu 192.168.20.100`).
- **Wireshark Trace Capture Plan:** Capture DHCP DORA exchange (`dhcp_negotiation.pcap`) and DNS query/response resolution (`dns_lookup.pcap`).
