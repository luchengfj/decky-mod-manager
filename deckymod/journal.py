"""Journal + snapshots + recovery (§4 / §5.2 E_RECOVERY_PENDING).

All journal/snapshot/log state lives in DECKY-managed dirs (review #4):
  ${DECKY_DATA}/journal/<game>.jsonl        append-only JSONL
  ${DECKY_DATA}/snapshots/<TXN_ID>/         per-transaction state-file backup
  ${DECKY_PLUGIN_LOG_DIR}/deckymod.log      human-readable log

The QUARANTINE (uninstalled mod directories) is the ONE approved exception:
it lives on W2's filesystem (GAME_ROOT/.decky-quarantine/<TXN_ID>/) so the
whole-directory rename does not raise EXDEV(18). journal records both the
original path and the quarantine path + txn id.

Transaction state machine:
  PREPARED -> APPLYING -> COMMITTED | ROLLED_BACK | ROLLBACK_FAILED

If a PREPARED/APPLYING transaction is found on open -> E_RECOVERY_PENDING
and the UI offers Recover / Rollback.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Dict, List, Optional

from .errors import ModError
from .json_safe import to_json_safe


def new_txn_id() -> str:
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:8]


class Journal:
    def __init__(self, decky_data: str, log_dir: str, game_id: str = "rimworld"):
        self.decky_data = decky_data
        self.log_dir = log_dir
        self.game_id = game_id
        self.journal_dir = os.path.join(decky_data, "journal")
        self.snapshot_root = os.path.join(decky_data, "snapshots")
        self.journal_path = os.path.join(self.journal_dir, f"{game_id}.jsonl")
        self.log_path = os.path.join(log_dir, "deckymod.log")
        os.makedirs(self.journal_dir, exist_ok=True)
        os.makedirs(self.snapshot_root, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)

    # ---- low level ----
    def _append(self, record: dict):
        record = to_json_safe(record)
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True)
        with open(self.journal_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
        self.log(f"journal {record.get('event')} txn={record.get('txn')}")

    def log(self, msg: str):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}\n")
        except OSError:
            pass

    def read_all(self) -> List[dict]:
        if not os.path.isfile(self.journal_path):
            return []
        out = []
        with open(self.journal_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def events(self, txn: str) -> List[dict]:
        return [r for r in self.read_all() if r.get("txn") == txn]

    def state(self, txn: str) -> Optional[str]:
        """Last known state for a transaction."""
        st = None
        for r in self.events(txn):
            if r.get("event") in ("PREPARED", "APPLYING", "COMMITTED", "ROLLED_BACK", "ROLLBACK_FAILED"):
                st = r["event"]
        return st

    def pending(self) -> List[str]:
        """Transactions left in PREPARED / APPLYING (recovery needed)."""
        states: Dict[str, str] = {}
        for r in self.read_all():
            e = r.get("event")
            if e in ("PREPARED", "APPLYING", "COMMITTED", "ROLLED_BACK", "ROLLBACK_FAILED"):
                states[r["txn"]] = e
        return [t for t, s in states.items() if s in ("PREPARED", "APPLYING")]

    # ---- transaction lifecycle ----
    def begin(self, txn: str, op: str, plan: dict):
        self._append({"event": "PREPARED", "txn": txn, "op": op, "plan": plan})

    def applying(self, txn: str):
        self._append({"event": "APPLYING", "txn": txn})

    def committed(self, txn: str, detail: dict | None = None):
        self._append({"event": "COMMITTED", "txn": txn, "detail": detail or {}})

    def rolled_back(self, txn: str, detail: dict | None = None):
        self._append({"event": "ROLLED_BACK", "txn": txn, "detail": detail or {}})

    def rollback_failed(self, txn: str, detail: dict | None = None):
        self._append({"event": "ROLLBACK_FAILED", "txn": txn, "detail": detail or {}})

    # ---- snapshots ----
    def snapshot_dir(self, txn: str) -> str:
        d = os.path.join(self.snapshot_root, txn)
        os.makedirs(d, exist_ok=True)
        return d

    def write_snapshot(self, txn: str, name: str, data: bytes) -> str:
        d = self.snapshot_dir(txn)
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        self._append({"event": "SNAPSHOT", "txn": txn, "path": p, "bytes": len(data)})
        return p

    def read_snapshot(self, txn: str, name: str) -> bytes:
        p = os.path.join(self.snapshot_dir(txn), name)
        try:
            with open(p, "rb") as f:
                return f.read()
        except OSError as e:
            raise ModError("E_ROLLBACK_FAILED", detail=f"snapshot missing: {p} ({e})")

    # ---- derived views ----
    def installed(self) -> Dict[str, dict]:
        """Reconstruct the managed-mod table from committed events.

        Keyed by packageId. An uninstall moves the dir to quarantine and is
        recorded; the journal keeps original + quarantine paths for rollback.
        """
        mods: Dict[str, dict] = {}
        ever_installed = set()
        for r in self.read_all():
            e = r.get("event")
            if e == "MOD_INSTALLED":
                pid = r.get("packageId")
                if pid:
                    ever_installed.add(pid)
                    mods[pid] = {
                        "packageId": pid, "name": r.get("name"), "version": r.get("version"),
                        "enabled": False, "dir": r.get("dir"), "txn": r.get("txn"),
                        "installed_at": r.get("ts"),
                    }
            elif e == "MOD_ENABLED":
                if r.get("packageId") in mods:
                    mods[r["packageId"]]["enabled"] = True
            elif e == "MOD_DISABLED":
                if r.get("packageId") in mods:
                    mods[r["packageId"]]["enabled"] = False
            elif e == "MOD_UNINSTALLED":
                mods.pop(r.get("packageId"), None)
            elif e == "MOD_ROLLBACK_RESTORED":
                # Round 21 (found on the device): rolling back the uninstall of a
                # mod the plugin never installed used to ADD it to this table, so
                # one rollback silently turned a pre-existing mod into a
                # "plugin-managed" one and the UI started claiming ownership of
                # the user's own folder.
                #
                # The rule is therefore: a restore only re-establishes ownership
                # if the plugin ever installed that id in the first place. We look
                # at prior MOD_INSTALLED rows rather than trusting a flag on the
                # event, because pre-fix journals carry restore rows with no flag
                # at all and must not keep poisoning the table.
                pid = r.get("packageId")
                if r.get("unmanaged"):
                    continue
                if not pid or pid not in ever_installed:
                    continue
                mods[pid] = {**r.get("mod", {}), "packageId": pid, "enabled": r.get("enabled", False)}
        return mods

    def record(self, event: str, txn: str, **fields):
        self._append({"event": event, "txn": txn, **fields})

    def history(self, limit: int = 50) -> List[dict]:
        rows = self.read_all()
        return rows[-limit:][::-1]
