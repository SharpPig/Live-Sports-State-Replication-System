"""
Replicator — maintains a WebSocket connection to core and applies ops
to a local in-memory copy of the state.

Handles reconnection with exponential back-off. Designed to be started
as a background asyncio task by the server.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import websockets

from .log import get_logger

log = get_logger("replica.replicator")


@dataclass
class Entry:
    key: str
    value: Any
    version: int
    ts: float            # timestamp from core
    op_id: str
    ended_at: float      # timestamp when game ended (0 if active)
    received_at: float   # local wall-clock when we applied it


class Replicator:
    """Consumes the core's op stream and maintains local state."""

    def __init__(self, core_ws_url: str = "ws://localhost:8001/replicate", replica_key: str = "replica-secret"):
        # Append token as query param for auth
        sep = "&" if "?" in core_ws_url else "?"
        self.core_ws_url = f"{core_ws_url}{sep}token={replica_key}"
        self.state: Dict[str, Entry] = {}
        self.is_connected = False
        self.ops_applied = 0
        self.last_op_at: float = 0.0
        self._lock = asyncio.Lock()

    # -- public reads (no lock needed for dict reads in CPython) ----------

    def get(self, key: str) -> Optional[Entry]:
        return self.state.get(key)

    def snapshot(self) -> Dict[str, Entry]:
        return dict(self.state)

    @property
    def size(self) -> int:
        return len(self.state)

    # -- replication loop -------------------------------------------------

    async def run(self):
        """Connect to core and stream ops. Reconnects on failure."""
        backoff = 1
        max_backoff = 30
        attempt = 0

        while True:
            attempt += 1
            try:
                log.info("connecting  attempt=%d  url=%s", attempt, self.core_ws_url)
                async with websockets.connect(self.core_ws_url) as ws:
                    self.is_connected = True
                    backoff = 1
                    attempt = 0
                    log.info("connected  state_keys=%d", self.size)

                    async for raw in ws:
                        await self._apply(raw)

                # clean close — core went away
                log.warning("connection closed by core  state_keys=%d", self.size)

            except asyncio.CancelledError:
                log.info("replicator cancelled  ops_applied=%d", self.ops_applied)
                break
            except Exception as e:
                log.warning("connection error  reason=%s  attempt=%d  retry_in=%ds", e, attempt, backoff)

            self.is_connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    # -- apply a single op -----------------------------------------------

    async def _apply(self, raw: str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.error("bad json from core, skipping")
            return

        action = msg.get("action")
        key = msg.get("key")
        now = time.time()

        async with self._lock:
            if action in ("put", "snapshot"):
                self.state[key] = Entry(
                    key=key,
                    value=msg["value"],
                    version=msg["version"],
                    ts=msg["ts"],
                    op_id=msg["op_id"],
                    ended_at=msg.get("ended_at", 0.0),
                    received_at=now,
                )
            elif action == "delete":
                self.state.pop(key, None)
            else:
                log.warning("unknown action=%s, skipping", action)
                return

            self.ops_applied += 1
            self.last_op_at = now

        if action == "snapshot":
            log.debug("sync  key=%s  v=%d", key, msg.get("version", 0))
        else:
            lag_ms = (now - msg.get("ts", now)) * 1000
            log.info("apply  action=%s  key=%s  v=%d  lag=%.1fms  total_ops=%d",
                     action, key, msg.get("version", 0), lag_ms, self.ops_applied)
