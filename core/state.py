"""
Core state machine. Owns the authoritative in-memory dataset.

State is a dict of string keys to versioned entries. Every mutation
increments the version and records a timestamp, so replicas can detect
ordering and staleness.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from .log import get_logger
from .wal import WAL, DualWAL

log = get_logger("core.state")


@dataclass
class Entry:
    key: str
    value: Any
    version: int
    ts: float          # unix epoch when this version was written
    op_id: str         # unique id for this mutation
    ended_at: float = 0.0    # unix epoch when game ended (0 if active)


@dataclass
class Op:
    """Wire format sent to replicas over WebSocket."""
    action: str        # "put", "delete", "snapshot"
    key: str
    value: Any
    version: int
    ts: float
    op_id: str
    ended_at: float = 0.0    # unix epoch when game ended (0 if active)

    def to_dict(self) -> dict:
        return asdict(self)


class StateMachine:
    """Single-writer, in-memory key-value store with replication fan-out."""

    def __init__(self, history_limit: int = 1000, wal_path: str = "logs/wal_primary.jsonl", use_dual_wal: bool = True):
        self._data: Dict[str, Entry] = {}
        self._history: List[Op] = []
        self._history_limit = history_limit
        self._lock = asyncio.Lock()
        self._subscribers: List[asyncio.Queue] = []
        
        # Use DualWAL for redundancy
        if use_dual_wal:
            backup_path = wal_path.replace("_primary.", "_secondary.")
            self._wal = DualWAL(primary_path=wal_path, backup_path=backup_path)
        else:
            self._wal = WAL(path=wal_path)

        # Open WAL (this triggers recovery if needed)
        self._wal.open()
        
        # Replay WAL to rebuild state from previous run
        self._replay_wal()

    # -- recovery ---------------------------------------------------------

    def _replay_wal(self):
        """Rebuild in-memory state from the WAL on startup."""
        ops = self._wal.replay()
        for raw in ops:
            action = raw.get("action")
            key = raw.get("key")
            if action == "put":
                self._data[key] = Entry(
                    key=key,
                    value=raw["value"],
                    version=raw["version"],
                    ts=raw["ts"],
                    op_id=raw["op_id"],
                    ended_at=raw.get("ended_at", 0.0),
                )
            elif action == "delete":
                self._data.pop(key, None)

            op = Op(**{k: raw[k] for k in ("action", "key", "value", "version", "ts", "op_id", "ended_at") if k in raw})
            self._append_history(op)

        if ops:
            log.info("state recovered  keys=%d  ops_replayed=%d", len(self._data), len(ops))

        self._wal.open()

    # -- reads (lock-free; dict ops are atomic in CPython) ----------------

    def get(self, key: str) -> Optional[Entry]:
        return self._data.get(key)

    def snapshot(self) -> Dict[str, Entry]:
        return dict(self._data)

    @property
    def size(self) -> int:
        return len(self._data)

    @property
    def version_ceiling(self) -> int:
        """Highest version across all keys. Useful as a replication cursor."""
        if not self._history:
            return 0
        return self._history[-1].version

    # -- writes -----------------------------------------------------------

    async def put(self, key: str, value: Any, end_game: bool = False) -> Entry:
        async with self._lock:
            prev = self._data.get(key)
            ver = (prev.version + 1) if prev else 1
            now = time.time()
            op_id = uuid.uuid4().hex[:12]
            
            # Set ended_at if this is an end_game operation
            ended_at = now if end_game else (prev.ended_at if prev else 0.0)

            entry = Entry(key=key, value=value, version=ver, ts=now, op_id=op_id, ended_at=ended_at)

            op = Op(action="put", key=key, value=value, version=ver, ts=now, op_id=op_id, ended_at=ended_at)
            self._wal.append(op.to_dict())
            self._data[key] = entry

            self._append_history(op)
            await self._fan_out(op)

            log.info("put  key=%s  v=%d  op=%s  ended=%s  replicas=%d", 
                    key, ver, op_id, "yes" if end_game else "no", len(self._subscribers))
            return entry

    async def end_game(self, key: str, final_value: Any = None) -> Entry:
        """Mark a game as ended with final score."""
        entry = self.get(key)
        if entry is None:
            raise ValueError(f"Game not found: {key}")
        
        # Use provided final value or current value
        value = final_value if final_value is not None else entry.value
        return await self.put(key, value, end_game=True)

    async def delete(self, key: str) -> bool:
        """Delete a key from the store."""
        async with self._lock:
            if key not in self._data:
                return False
            
            entry = self._data[key]
            ver = entry.version + 1
            now = time.time()
            op_id = uuid.uuid4().hex[:12]
            op = Op(
                action="delete",
                key=key,
                value=entry.value,
                version=ver,
                ts=now,
                op_id=op_id,
                ended_at=entry.ended_at,
            )
            self._wal.append(op.to_dict())
            self._data.pop(key, None)
            self._append_history(op)
            await self._fan_out(op)

            log.info("del  key=%s  v=%d  op=%s  replicas=%d", key, ver, op_id, len(self._subscribers))
            return True

    # -- replication ------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        """Return a queue that will receive every Op from now on."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        log.info("replica subscribed  total=%d", len(self._subscribers))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)
            log.info("replica unsubscribed  total=%d", len(self._subscribers))

    def history_since(self, after_version: int) -> List[Op]:
        """Return ops newer than after_version (for catch-up)."""
        return [op for op in self._history if op.version > after_version]

    # -- internals --------------------------------------------------------

    def _append_history(self, op: Op) -> None:
        self._history.append(op)
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit:]

    async def _fan_out(self, op: Op) -> None:
        if not self._subscribers:
            return
            
        dead: List[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(op)
            except asyncio.QueueFull:
                log.warning("subscriber queue full, dropping op=%s", op.op_id)
                dead.append(q)
            except RuntimeError:
                # Queue is closed or destroyed (replica disconnected)
                log.info("removing dead subscriber queue")
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)
