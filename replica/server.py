"""
Replica HTTP server.

Serves read-only endpoints for the dashboard and other clients.
Maintains a local copy of the core state via WebSocket replication.
"""

import asyncio
import json
import os
from dataclasses import asdict
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .replicator import Replicator
from .log import get_logger

log = get_logger("replica.server")

app = FastAPI(title="replica")
replicator = Replicator()


@app.get("/")
async def health():
    """Health check."""
    return {"service": "replica", "status": "healthy", "ts": asyncio.get_event_loop().time()}


@app.get("/state")
async def get_all_state():
    """Get all current state."""
    return {k: asdict(v) for k, v in replicator.snapshot().items()}


@app.get("/state/{key}")
async def get_state(key: str):
    """Get a specific key."""
    entry = replicator.get(key)
    if entry is None:
        raise HTTPException(404, f"key not found: {key}")
    return asdict(entry)


@app.get("/metrics")
async def metrics():
    """Operational metrics."""
    return {
        "state_keys": replicator.size,
        "core_connected": replicator.is_connected,
        "last_op_at": replicator.last_op_at,
        "ts": asyncio.get_event_loop().time(),
    }


@app.get("/api/games")
async def get_games():
    """Dashboard-friendly games endpoint."""
    snapshot = replicator.snapshot()
    games = []
    
    for key, entry in snapshot.items():
        value = entry.get("value", {})
        if value.get("home") and value.get("away"):
            home = value.get("home", "TBD")
            away = value.get("away", "TBD")
            score = value.get("score", [0, 0])
            home_odds = value.get("home_odds", "EVEN")
            away_odds = value.get("away_odds", "EVEN")
            
            ended_at = entry.get("ended_at", 0.0)
            is_ended = ended_at > 0
            
            games.append({
                "id": key,
                "title": f"{home} vs {away}",
                "home_score": score[0] if len(score) > 0 else 0,
                "away_score": score[1] if len(score) > 1 else 0,
                "home_odds": home_odds,
                "away_odds": away_odds,
                "version": entry.get("version", 0),
                "lag_ms": (asyncio.get_event_loop().time() - entry.get("ts", 0)) * 1000,
                "ended_at": ended_at,
                "is_ended": is_ended,
                "sort_key": ended_at if ended_at > 0 else entry.get("ts", 0.0),
            })
    
    # Sort by ending time (ended games first, newest first), then by title
    games.sort(key=lambda g: (-g["sort_key"], g["title"]))
    return {"games": games}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup():
    """Start replication background task when the server starts."""
    asyncio.create_task(replicator.run())
    log.info("replication task started")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

#Limiting for the next 1000, ports.
#Which means we can have no more than 1000 replicas on this ip/port.
def find_available_port(start_port: int = 8002, max_attempts: int = 1000) -> int:
    """Find the next available port starting from start_port."""
    import socket
    
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return port
        except OSError:
            continue
    
    raise RuntimeError(f"No available ports found between {start_port} and {start_port + max_attempts - 1}")


if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment or find next available
    if "PORT" in os.environ:
        port = int(os.environ["PORT"])
        log.info("using specified port  port=%d", port)
    else:
        port = find_available_port()
        log.info("found available port  port=%d", port)
    
    uvicorn.run(app, host="0.0.0.0", port=port)
