"""
Simple web dashboard displaying game scores from replicas.
Shows real-time updates as games change.
"""

import asyncio
import json
import os
import random
from pathlib import Path
from typing import Dict, Any, List, Tuple

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .log import get_logger

log = get_logger("dashboard.app")

app = FastAPI(title="Scores Dashboard")
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Dynamic replica discovery
def get_replica_urls() -> List[str]:
    """Discover all running replica servers by checking ports."""
    import socket
    
    replica_urls = []
    
    # Check ports 8002-9002 (1000 possible replicas), excluding dashboard port
    dashboard_port = 8080
    for port in range(8002, 9002):
        if port == dashboard_port:
            continue  # Skip dashboard port
        
        try:
            # Quick port check
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)  # Fast timeout
                result = s.connect_ex(('localhost', port))
                if result == 0:
                    replica_urls.append(f"http://localhost:{port}")
        except:
            continue
    
    return replica_urls


# Get current replica URLs (will be called dynamically)
def get_current_replicas() -> List[str]:
    return get_replica_urls()

# Cache for game data
games_cache: Dict[str, Any] = {}
last_update = 0
cache_timestamp = 0
CACHE_DURATION = 1.0


async def fetch_from_replicas() -> Tuple[Dict[str, Any], str]:
    """Fetch game data from a random replica, return data and selected URL."""
    # Get current running replicas
    replica_urls = get_current_replicas()
    
    if not replica_urls:
        log.warning("no running replicas found")
        return {}, "none"
    
    log.info("discovered replicas  count=%d  urls=%s", len(replica_urls), replica_urls)
    
    # Shuffle URLs to pick randomly
    shuffled_urls = replica_urls.copy()
    random.shuffle(shuffled_urls)
    
    async with aiohttp.ClientSession() as session:
        for replica_url in shuffled_urls:
            try:
                async with session.get(f"{replica_url}/state", timeout=2.0) as response:
                    if response.status == 200:
                        data = await response.json()
                        log.info("fetched from replica  url=%s  games=%d", replica_url, len(data))
                        return data, replica_url
            except Exception as e:
                log.warning("replica fetch failed  url=%s  error=%s", replica_url, e)
                continue
        
        log.warning("all replicas failed, using cache")
        return games_cache, "none"


def format_game_data(raw_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert raw state into display-friendly game list."""
    games = []
    for key, entry in raw_state.items():
        # Show all entries that look like games (have home/away teams)
        value = entry.get("value", {})
        if value.get("home") and value.get("away"):
            home = value.get("home", "TBD")
            away = value.get("away", "TBD")
            
            # Determine status
            ended_at = entry.get("ended_at", 0.0)
            is_ended = ended_at > 0
            
            # Sort: ended games first (by ended_at), then active games (by last update)
            sort_key = ended_at if ended_at > 0 else entry.get("ts", 0.0)
            
            games.append({
                "id": key,
                "title": f"{home} vs {away}",  # X vs Y format
                "home": home,
                "away": away,
                "home_score": value.get("score", [0, 0])[0],
                "away_score": value.get("score", [0, 0])[1],
                "home_odds": value.get("home_odds", "+110"),  # Default moneyline
                "away_odds": value.get("away_odds", "-110"),  # Default moneyline
                "version": entry.get("version", 0),
                "lag_ms": round(entry.get("lag_ms", 0), 1),
                "updated_at": entry.get("ts", 0),
                "ended_at": ended_at,
                "is_ended": is_ended,
                "sort_key": sort_key,
            })
    
    # Sort by ending time (ended games first, newest first), then by title
    games.sort(key=lambda g: (-g["sort_key"], g["title"]))
    return games


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    global games_cache, last_update, cache_timestamp
    
    current_time = asyncio.get_event_loop().time()
    cache_age = current_time - cache_timestamp
    
    # Always use cache if we have data, even if expired
    if games_cache:
        raw_state = games_cache
        selected_replica = "cached"
        
        # Only refresh cache if expired
        if cache_age >= CACHE_DURATION:
            try:
                new_raw_state, new_replica = await fetch_from_replicas()
                games_cache = new_raw_state
                cache_timestamp = current_time
                log.info("refreshed cache  replica=%s  games=%d", new_replica, len(new_raw_state))
            except Exception as e:
                log.warning("cache refresh failed  error=%s  using_stale_cache", e)
    else:
        # First load - fetch from replicas
        raw_state, selected_replica = await fetch_from_replicas()
        games_cache = raw_state
        cache_timestamp = current_time
        log.info("initial cache load  replica=%s  games=%d", selected_replica, len(raw_state))
    
    games = format_game_data(raw_state)
    
    # Calculate stats
    total_games = len(games)
    
    context = {
        "request": request,
        "games": games,
        "total_games": total_games,
        "last_update": cache_timestamp,
        "selected_replica": selected_replica,
        "cache_age": round(current_time - cache_timestamp, 1),
    }
    
    return templates.TemplateResponse("dashboard.html", context)


@app.get("/api/games")
async def api_games():
    """JSON API for game data (for AJAX updates)."""
    raw_state, _ = await fetch_from_replicas()
    games = format_game_data(raw_state)
    return {
        "games": games,
        "total": len(games),
        "timestamp": asyncio.get_event_loop().time()
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "replicas": len(REPLICA_URLS)}


if __name__ == "__main__":
    import uvicorn
    log.info("starting dashboard  port=8080")
    uvicorn.run(app, host="0.0.0.0", port=8080)
