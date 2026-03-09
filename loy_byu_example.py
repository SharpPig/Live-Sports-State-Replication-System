#!/usr/bin/env python3
"""Example: LOY vs BYU game with date-based identifier."""

import requests
import time

CORE_URL = "http://localhost:8001"
ADMIN_KEY = "admin-secret"

def write_game(key: str, home: str, away: str, score: list, odds: tuple, end_game: bool = False):
    """Write/update a game."""
    payload = {
        "key": key,
        "value": {
            "home": home,
            "away": away,
            "score": score,
            "home_odds": odds[0],
            "away_odds": odds[1]
        },
        "end_game": end_game
    }
    
    response = requests.post(
        f"{CORE_URL}/state",
        headers={
            "X-Admin-Key": ADMIN_KEY,
            "Content-Type": "application/json"
        },
        json=payload
    )
    
    if response.status_code == 200:
        data = response.json()
        status = "ENDED" if data.get('ended_at', 0) > 0 else "ACTIVE"
        print(f"✅ {key} - {home} {score[0]} - {score[1]} {away} ({status})")
        return data
    else:
        print(f"❌ Error: {response.status_code} - {response.text}")
        return None

def main():
    game_key = "loy_vs_byu_2024_03_10"
    
    print("🏀 LOY vs BYU Game Simulation")
    print(f"📅 Game ID: {game_key}")
    print()
    
    # 1. Game starts
    print("1. Game starts:")
    write_game(game_key, "LOY", "BYU", [0, 0], ("+105", "-125"))
    
    # 2. First few minutes
    print("\n2. First few minutes:")
    time.sleep(2)
    write_game(game_key, "LOY", "BYU", [8, 5], ("+108", "-128"))
    
    # 3. Mid first half
    print("\n3. Mid first half:")
    time.sleep(2)
    write_game(game_key, "LOY", "BYU", [18, 15], ("+110", "-130"))
    
    # 4. Late first half
    print("\n4. Late first half:")
    time.sleep(2)
    write_game(game_key, "LOY", "BYU", [28, 22], ("+112", "-132"))
    
    # 5. Halftime
    print("\n5. Halftime:")
    time.sleep(2)
    write_game(game_key, "LOY", "BYU", [35, 30], ("+115", "-135"))
    
    # 6. Early second half
    print("\n6. Early second half:")
    time.sleep(2)
    write_game(game_key, "LOY", "BYU", [45, 40], ("+118", "-138"))
    
    # 7. Mid second half
    print("\n7. Mid second half:")
    time.sleep(2)
    write_game(game_key, "LOY", "BYU", [58, 52], ("+120", "-140"))
    
    # 8. Late second half
    print("\n8. Late second half:")
    time.sleep(2)
    write_game(game_key, "LOY", "BYU", [68, 62], ("+122", "-142"))
    
    # 9. Final minutes
    print("\n9. Final minutes:")
    time.sleep(2)
    write_game(game_key, "LOY", "BYU", [78, 75], ("+125", "-145"))
    
    # 10. Final score
    print("\n10. Final score:")
    time.sleep(2)
    write_game(game_key, "LOY", "BYU", [85, 82], ("+128", "-148"))
    
    # 11. End the game
    print("\n11. Game ended:")
    time.sleep(2)
    result = write_game(game_key, "LOY", "BYU", [88, 85], ("+130", "-150"), end_game=True)
    
    if result:
        print(f"\n🏆 Final Result: LOY 88 - BYU 85")
        print(f"📊 Check dashboard: http://localhost:8080")

if __name__ == "__main__":
    main()
