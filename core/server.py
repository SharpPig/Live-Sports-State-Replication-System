"""
Core HTTP + WebSocket server. Internal-only.

All HTTP endpoints require the CORE_ADMIN_KEY header.
WebSocket /replicate requires the CORE_REPLICA_KEY as a query param.
External reads should go through replicas.

Endpoints:
  POST   /state         — write a key       (admin)
  GET    /state/{key}   — read a key         (admin)
  GET    /state         — read all keys      (admin)
  DELETE /state/{key}   — delete a key       (admin)
  GET    /metrics       — operational stats  (admin)
  WS     /replicate     — replica stream     (replica key)
"""

import asyncio
import json
import os
import time
from dataclasses import asdict
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .state import StateMachine, Op
from .log import get_logger

log = get_logger("core.server")

ADMIN_KEY = os.environ.get("CORE_ADMIN_KEY", "admin-secret")
REPLICA_KEY = os.environ.get("CORE_REPLICA_KEY", "replica-secret")

# ---------------------------------------------------------------------------
# Models
# ----------------------------------------------
# -----------------------------

class WriteRequest(BaseModel):
    key: str
    value: Any
    end_game: bool = False

class EntryResponse(BaseModel):
    key: str
    value: Any
    version: int
    ts: float
    ended_at: float

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="core")
sm = StateMachine(wal_path="logs/wal_primary.jsonl")


@app.get("/")
async def health():
    """Health check (no auth required)"""
    return {"service": "core", "status": "healthy", "ts": time.time()}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Block all HTTP requests without a valid admin key."""
    # Allow health check without auth
    if request.url.path == "/":
        return await call_next(request)

    key = request.headers.get("X-Admin-Key", "")
    if key != ADMIN_KEY:
        log.warning("auth rejected  path=%s  ip=%s", request.url.path, request.client.host)
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    return await call_next(request)


@app.post("/state", response_model=EntryResponse)
async def put_state(req: WriteRequest):
    entry = await sm.put(req.key, req.value, end_game=req.end_game)
    return EntryResponse(key=entry.key, value=entry.value, version=entry.version, ts=entry.ts, ended_at=entry.ended_at)


@app.get("/state/{key}", response_model=EntryResponse)
async def get_state(key: str):
    entry = sm.get(key)
    if entry is None:
        raise HTTPException(404, f"game not found: {key}")
    return EntryResponse(key=entry.key, value=entry.value, version=entry.version, ts=entry.ts, ended_at=entry.ended_at)


@app.get("/state")
async def get_all_state():
    return {k: asdict(v) for k, v in sm.snapshot().items()}


@app.delete("/state/{key}")
async def delete_state(key: str):
    if not await sm.delete(key):
        raise HTTPException(404, f"game not found: {key}")
    return {"deleted": key}


@app.get("/metrics")
async def metrics():
    return {
        "state_keys": sm.size,
        "version_ceiling": sm.version_ceiling,
        "connected_replicas": len(sm._subscribers),
        "history_depth": len(sm._history),
        "ts": time.time(),
    }


@app.get("/wal/sync")
async def check_wal_sync():
    """Check if WAL files are in sync."""
    if hasattr(sm._wal, 'check_sync'):
        is_synced = sm._wal.check_sync()
        return {"synced": is_synced, "ts": time.time()}
    else:
        return {"synced": True, "message": "Single WAL mode", "ts": time.time()}


@app.post("/wal/sync/primary")
async def sync_wal_from_primary():
    """Force sync secondary WAL from primary."""
    if hasattr(sm._wal, 'sync_from_primary'):
        sm._wal.sync_from_primary()
        return {"message": "Secondary WAL synced from primary", "ts": time.time()}
    else:
        return {"message": "Single WAL mode", "ts": time.time()}


@app.post("/wal/sync/secondary")
async def sync_wal_from_secondary():
    """Force sync primary WAL from secondary."""
    if hasattr(sm._wal, 'sync_from_secondary'):
        sm._wal.sync_from_secondary()
        return {"message": "Primary WAL synced from secondary", "ts": time.time()}
    else:
        return {"message": "Single WAL mode", "ts": time.time()}


# ---------------------------------------------------------------------------
# WebSocket replication endpoint
# ---------------------------------------------------------------------------

@app.websocket("/replicate")
async def ws_replicate(ws: WebSocket, token: str = Query(default="")):
    if token != REPLICA_KEY:
        log.warning("replica auth rejected  ip=%s", ws.client.host)
        await ws.close(code=4003, reason="forbidden")
        return

    await ws.accept()

    # 1. Send full snapshot so the replica starts from a known state.
    snapshot = sm.snapshot()
    for key, entry in snapshot.items():
        msg = Op(
            action="snapshot",
            key=key,
            value=entry.value,
            version=entry.version,
            ts=entry.ts,
            op_id=entry.op_id,
            ended_at=entry.ended_at,
        )
        await ws.send_text(json.dumps(msg.to_dict()))
    log.info("snapshot sent  keys=%d", len(snapshot))

    # 2. Subscribe to live ops.
    queue = sm.subscribe()
    try:
        while True:
            op: Op = await queue.get()
            await ws.send_text(json.dumps(op.to_dict()))
    except WebSocketDisconnect:
        log.info("replica disconnected normally")
    except Exception as e:
        log.warning("replica connection lost  reason=%s", e)
    finally:
        sm.unsubscribe(queue)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    log.info("starting core server  port=8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
