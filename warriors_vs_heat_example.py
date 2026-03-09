#!/usr/bin/env python3
"""Example: Warriors vs Heat game with date-based identifier."""

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
    game_key = "warriors_vs_heat_2024_03_08"
    
    print("🏀 Warriors vs Heat Game Simulation")
    print(f"📅 Game ID: {game_key}")
    print()
    
    # 1. Game starts
    print("1. Game starts:")
    write_game(game_key, "GSW", "MIA", [0, 0], ("-110", "+110"))
    
    # 2. First few minutes
    print("\n2. First few minutes:")
    time.sleep(2)
    write_game(game_key, "GSW", "MIA", [12, 8], ("-108", "+108"))
    
    # 3. Mid first quarter
    print("\n3. Mid first quarter:")
    time.sleep(2)
    write_game(game_key, "GSW", "MIA", [22, 15], ("-106", "+106"))
    
    # 4. End first quarter
    print("\n4. End first quarter:")
    time.sleep(2)
    write_game(game_key, "GSW", "MIA", [28, 25], ("-104", "+104"))
    
    # 5. Early second quarter
    print("\n5. Early second quarter:")
    time.sleep(2)
    write_game(game_key, "GSW", "MIA", [38, 32], ("-102", "+102"))
    
    # 6. Halftime
    print("\n6. Halftime:")
    time.sleep(2)
    write_game(game_key, "GSW", "MIA", [52, 45], ("-100", "+100"))
    
    # 7. Early third quarter
    print("\n7. Early third quarter:")
    time.sleep(2)
    write_game(game_key, "GSW", "MIA", [65, 55], ("-98", "+98"))
    
    # 8. End third quarter
    print("\n8. End third quarter:")
    time.sleep(2)
    write_game(game_key, "GSW", "MIA", [78, 68], ("-96", "+96"))
    
    # 9. Early fourth quarter
    print("\n9. Early fourth quarter:")
    time.sleep(2)
    write_game(game_key, "GSW", "MIA", [92, 80], ("-94", "+94"))
    
    # 10. Final minutes
    print("\n10. Final minutes:")
    time.sleep(2)
    write_game(game_key, "GSW", "MIA", [108, 95], ("-92", "+92"))
    
    # 11. End the game
    print("\n11. Game ended:")
    time.sleep(2)
    result = write_game(game_key, "GSW", "MIA", [118, 110], ("-90", "+90"), end_game=True)
    
    if result:
        print(f"\n🏆 Final Result: Warriors 118 - Heat 110")
        print(f"📊 Check dashboard: http://localhost:8080")

if __name__ == "__main__":
    main()
