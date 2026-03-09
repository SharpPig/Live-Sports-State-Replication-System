"""
Write-Ahead Log (WAL) for core state persistence.

Every mutation is appended to a log file before being applied in memory.
On restart, the log is replayed to rebuild state. This gives durability
without the complexity of a full database.

Format: one JSON object per line (newline-delimited JSON).
"""

import json
import os
from pathlib import Path
from typing import List, Optional

from .log import get_logger

log = get_logger("core.wal")


class WAL:
    """Write-ahead log for durability and recovery."""
    
    def __init__(self, path: str = "logs/wal_primary.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = None

    def open(self):
        """Open the WAL file for appending."""
        self._file = open(self.path, "a")
        log.info("opened  path=%s  size=%d bytes", self.path, self.path.stat().st_size)

    def close(self):
        if self._file:
            self._file.close()
            self._file = None

    def append(self, op: dict):
        """Append an operation to the WAL. Must be called before in-memory apply."""
        line = json.dumps(op, separators=(",", ":"))
        self._file.write(line + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

    def replay(self) -> List[dict]:
        """Read all ops from the WAL file. Used on startup to rebuild state."""
        if not self.path.exists():
            log.info("no wal file found, starting fresh")
            return []

        ops = []
        corrupt = 0
        with open(self.path, "r") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    ops.append(json.loads(line))
                except json.JSONDecodeError:
                    corrupt += 1
                    log.warning("corrupt entry at line %d, skipping", lineno)

        log.info("replayed  ops=%d  corrupt=%d  path=%s", len(ops), corrupt, self.path)
        return ops

    def truncate(self):
        """Clear the WAL. Used after snapshotting if you want compaction."""
        if self._file:
            self._file.close()
        with open(self.path, "w") as f:
            f.truncate(0)
        self._file = open(self.path, "a")
        log.info("truncated  path=%s", self.path)


class DualWAL:
    """Redundant write-ahead log writing to two file locations."""
    
    def __init__(self, primary_path: str = "logs/wal_primary.jsonl", backup_path: str = "logs/wal_secondary.jsonl"):
        self.primary = WAL(primary_path)
        self.backup = WAL(backup_path)
        self._path = primary_path
    
    def open(self):
        """Open both WAL files and recover missing ones."""
        # Check if we need to recover from the other file
        if not self.primary.path.exists() and self.backup.path.exists():
            log.info("primary WAL missing, recovering from backup")
            self._recover_from_backup()
        elif not self.backup.path.exists() and self.primary.path.exists():
            log.info("backup WAL missing, recovering from primary")
            self._recover_from_primary()
        
        self.primary.open()
        self.backup.open()
    
    def close(self):
        """Close both WAL files."""
        self.primary.close()
        self.backup.close()
    
    def append(self, op_dict: dict):
        """Append to both WAL files."""
        try:
            # Write to primary first
            self.primary.append(op_dict)
            # Then write to backup
            self.backup.append(op_dict)
        except Exception as e:
            log.error("dual WAL write failed  error=%s", e)
            raise
    
    def replay(self) -> List[dict]:
        """Replay from primary WAL, fallback to backup if needed."""
        # Check if primary exists and is readable
        if self.primary.path.exists() and self.primary.path.stat().st_size > 0:
            try:
                ops = self.primary.replay()
                log.info("primary WAL replayed  ops=%d", len(ops))
                return ops
            except Exception as e:
                log.warning("primary WAL replay failed, trying backup  error=%s", e)
        
        # Try backup WAL
        if self.backup.path.exists() and self.backup.path.stat().st_size > 0:
            try:
                ops = self.backup.replay()
                log.info("backup WAL replayed  ops=%d", len(ops))
                return ops
            except Exception as e:
                log.error("backup WAL replay failed  error=%s", e)
        
        log.warning("no WAL data found, starting empty")
        return []
    
    def _recover_from_backup(self):
        """Recover primary WAL from backup."""
        try:
            # Copy backup to primary
            with open(self.backup.path, 'r') as src:
                with open(self.primary.path, 'w') as dst:
                    dst.write(src.read())
            log.info("recovered primary WAL from backup  size=%d bytes", self.primary.path.stat().st_size)
        except Exception as e:
            log.error("failed to recover primary WAL from backup  error=%s", e)
            raise
    
    def _recover_from_primary(self):
        """Recover backup WAL from primary."""
        try:
            # Copy primary to backup
            with open(self.primary.path, 'r') as src:
                with open(self.backup.path, 'w') as dst:
                    dst.write(src.read())
            log.info("recovered backup WAL from primary  size=%d bytes", self.backup.path.stat().st_size)
        except Exception as e:
            log.error("failed to recover backup WAL from primary  error=%s", e)
            raise
    
    def check_sync(self) -> bool:
        """Check if primary and secondary WALs are in sync."""
        try:
            primary_ops = self.primary.replay()
            secondary_ops = self.backup.replay()
            
            # Compare number of operations
            if len(primary_ops) != len(secondary_ops):
                log.warning("WAL sync mismatch  primary_ops=%d  secondary_ops=%d", 
                           len(primary_ops), len(secondary_ops))
                return False
            
            # Compare last operation timestamps
            if primary_ops and secondary_ops:
                primary_ts = primary_ops[-1].get("ts", 0)
                secondary_ts = secondary_ops[-1].get("ts", 0)
                
                if primary_ts != secondary_ts:
                    log.warning("WAL timestamp mismatch  primary_ts=%f  secondary_ts=%f", 
                               primary_ts, secondary_ts)
                    return False
            
            log.info("WAL files are in sync  ops=%d", len(primary_ops))
            return True
            
        except Exception as e:
            log.error("WAL sync check failed  error=%s", e)
            return False
    
    def sync_from_primary(self):
        """Sync secondary WAL from primary."""
        try:
            log.info("syncing secondary WAL from primary")
            with open(self.primary.path, 'r') as src:
                with open(self.backup.path, 'w') as dst:
                    dst.write(src.read())
            log.info("secondary WAL synced from primary  size=%d bytes", 
                    self.backup.path.stat().st_size)
        except Exception as e:
            log.error("failed to sync secondary WAL from primary  error=%s", e)
            raise
    
    def sync_from_secondary(self):
        """Sync primary WAL from secondary."""
        try:
            log.info("syncing primary WAL from secondary")
            with open(self.backup.path, 'r') as src:
                with open(self.primary.path, 'w') as dst:
                    dst.write(src.read())
            log.info("primary WAL synced from secondary  size=%d bytes", 
                    self.primary.path.stat().st_size)
        except Exception as e:
            log.error("failed to sync primary WAL from secondary  error=%s", e)
            raise
    
    @property
    def path(self) -> Path:
        return self.primary.path
