## 3. Game Behavior & Server Concurrency Architecture (Sprint 2 Deliverable)

### 3.1 Server Concurrency Strategy
- **Architecture Choice:** Multi-Threading (`threading.Thread`) - I have chosen multi threading. The coding is simpler, and while it is less scalable, I only need 2 players at a time and simple turn based mechanics. 
- **Synchronization Logic:** To prevent race conditions and maintain state between turns, threading.lock will be used. This will allow us to mutate the gamestate safely. Since both players take their turn one at a time, state management should be simple, and easier to implement using multi threading. 

### 3.2 State & Score Synchronization Across Clients
- **Turn Enforcement:** When an ACT message arrives, our server checks the port it arrived at against the player_ID and player_role, to ensure that they match and are expected. We check state to ensure it is an in turn message by checking active_role, and act accordingly. 
- **Score & Board Synchronization:** Every valid move by either player triggers an updated state broadcast. Each client node parses JSON, clears its terminal output, and redraws the board with the updated state.

```mermaid
sequenceDiagram
    participant Z as Zombie Client
    participant S as Server
    participant H as Survivor Client

    Note over Z,H: Server controls turn order and remaining moves.<br/>Both clients display the server's state.

    loop While game is active
        S-->>Z: STATE_UPDATE — zombie turn, 4 moves
        S-->>H: STATE_UPDATE — zombie turn, 4 moves

        loop Until zombie moves are spent
            Z->>S: ACT
            S->>S: Validate sender, turn, action, and moves remaining
            alt Valid
                S->>S: Apply action and deduct move cost
                S-->>Z: STATE_UPDATE — board and moves remaining
                S-->>H: STATE_UPDATE — same state
            else Invalid
                S-->>Z: ERROR — state and moves unchanged
            end
        end

        S-->>Z: STATE_UPDATE — survivor turn, 3 moves
        S-->>H: STATE_UPDATE — survivor turn, 3 moves

        loop Until survivor moves are spent
            H->>S: ACT
            S->>S: Validate sender, turn, action, and moves remaining
            alt Valid
                S->>S: Apply action and deduct move cost
                S-->>Z: STATE_UPDATE — board and moves remaining
                S-->>H: STATE_UPDATE — same state
            else Invalid
                S-->>H: ERROR — state and moves unchanged
            end
        end
    end

    Note over Z,H: Out-of-turn actions receive ERROR without changing state.<br/>Any disconnect stops play: opponent wins, server sends GAME_OVER<br/>to the connected client and releases player and match resources.
```
--- 
