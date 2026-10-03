<img width="3901" height="8192" alt="Zombie Survival Action Flow-2026-10-03-191201" src="https://github.com/user-attachments/assets/7d70ba0a-d07d-475d-b38b-5c620c6942c2" />

Flowchart Code:

flowchart TD
    Start([Game Start]) --> ZombieTurn[Zombie Player Turn]
    ZombieTurn --> ZombieAction{Choose Action}
    ZombieAction -->|Spawn Zombie| SpawnZ[Add Regular Zombie<br/>to Row]
    ZombieAction -->|Cash Move| CashZ[Accumulate Cash<br/>toward Special]
    ZombieAction -->|Spawn Special| SpawnSpecial[Consume 4 Cash<br/>Spawn Special Zombie]
    SpawnZ --> MovesLeft{Moves Left?}
    CashZ --> MovesLeft
    SpawnSpecial --> MovesLeft
    MovesLeft -->|Yes<br/>Repeat| ZombieAction
    MovesLeft -->|No| AutoAdvance[All Zombies Advance<br/>1 Space Toward House]
    AutoAdvance --> SurvivorTurn[Survivor Player Turn]
    SurvivorTurn --> SurvivorAction{Choose Action}
    SurvivorAction -->|Repair| RepairAction[Repair Window<br/>Restore Health]
    SurvivorAction -->|Shoot| ShootAction[Shoot Zombie<br/>in Lane]
    SurvivorAction -->|Move| MoveAction[Move Survivor<br/>to Different Window]
    RepairAction --> SurvivorMovesLeft{Moves Left?}
    ShootAction --> SurvivorMovesLeft
    MoveAction --> SurvivorMovesLeft
    SurvivorMovesLeft -->|Yes<br/>Repeat| SurvivorAction
    SurvivorMovesLeft -->|No| CheckWinCondition{Check Conditions}
    CheckWinCondition -->|Zombie Reached<br/>Undefended Window| ZombieWin([Zombies Win])
    CheckWinCondition -->|Round 20<br/>Survived| SurvivorWin([Survivors Win])
    CheckWinCondition -->|Round < 20| RoundIncrement[Increment Round]
    RoundIncrement --> ZombieTurn

    ZombieTurn -.->|DISCONNECT command| Disconnect[Player Disconnect Detected]
    SurvivorTurn -.->|DISCONNECT command| Disconnect
    ZombieTurn -.->|Unexpected connection loss| Disconnect
    SurvivorTurn -.->|Unexpected connection loss| Disconnect
    Disconnect --> ReclaimResources[Server reclaims disconnected<br/>player hosting resources]
    ReclaimResources --> OpponentWin([Connected Opponent<br/>Wins Automatically])
    
    classDef zombieNode stroke:#f87171,fill:#fef2f2
    classDef survivorNode stroke:#4ade80,fill:#f0fdf4
    classDef checkNode stroke:#facc15,fill:#fefce8
    classDef winNode stroke:#a3e635,fill:#f7fee7
    
    class ZombieTurn,ZombieAction,SpawnZ,CashZ,SpawnSpecial,MovesLeft,AutoAdvance zombieNode
    class SurvivorTurn,SurvivorAction,RepairAction,ShootAction,MoveAction,SurvivorMovesLeft survivorNode
    class CheckWinCondition,RoundIncrement,Disconnect,ReclaimResources checkNode
    class ZombieWin,SurvivorWin,OpponentWin winNode
