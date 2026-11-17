"""Registry loader + capability gate (§2).

Loads registry/registry.json and the referenced descriptor files. Enforces:
  * exactly one enabled descriptor in MVP (max_enabled_games_in_mvp: 1)
  * status must equal capability_gate.enabled_game_status ("enabled")
  * any operation whose required capability is false -> E_CAPABILITY_DISABLED

There is NO universal one-click install: the gate is checked on every call.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from .errors import ModError

DEFAULT_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "registry", "registry.json")


class Registry:
    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or os.path.dirname(os.path.dirname(__file__))
        self.registry_path = os.path.join(self.base_dir, "registry", "registry.json")
        self.raw = self._load_json(self.registry_path)
        self.descriptors: Dict[str, dict] = {}
        for gid, meta in self.raw.get("descriptors", {}).items():
            path = os.path.join(self.base_dir, *meta["file"].split("/"))
            self.descriptors[gid] = self._load_json(path)
        self.loaders: Dict[str, dict] = {}
        for lid, path in self.raw.get("loader_catalog", {}).items():
            fp = os.path.join(self.base_dir, *path.split("/"))
            self.loaders[lid] = self._load_json(fp)

    @staticmethod
    def _load_json(path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ModError("E_UNKNOWN", detail=f"registry load failed {path}: {e}")

    def gate(self) -> dict:
        return self.raw.get("capability_gate", {})

    def _pinned_game(self) -> str | None:
        """Regression pin: DECKYMOD_GAME_ID forces ONE descriptor to be the
        active game regardless of registry.json status. Used ONLY by the 33
        historical synthetic-tree tests (which set it to 'rimworld') so that
        switching the production active_game to 'stardew' does not break them.
        In production this env var is unset and the registry.json enabled
        descriptor(s) decide."""
        return os.environ.get("DECKYMOD_GAME_ID") or None

    def enabled_games(self) -> List[str]:
        pinned = self._pinned_game()
        if pinned:
            return [pinned] if pinned in self.descriptors else []
        g = self.gate()
        want = g.get("enabled_game_status", "enabled")
        return [gid for gid, d in self.descriptors.items() if d.get("status") == want]

    def get_game(self, game_id: str) -> dict:
        d = self.descriptors.get(game_id)
        if not d:
            raise ModError("E_CAPABILITY_DISABLED", detail=f"unknown game id: {game_id}")
        pinned = self._pinned_game()
        if pinned == game_id:
            # pinned descriptor is treated as enabled (regression mode)
            return d
        g = self.gate()
        if g.get("refuse_if_status_not_enabled", True) and d.get("status") != g.get("enabled_game_status", "enabled"):
            raise ModError("E_CAPABILITY_DISABLED", detail=f"{game_id} status={d.get('status')} (planned)")
        return d

    def assert_enabled_count(self):
        g = self.gate()
        max_n = g.get("max_enabled_games_in_mvp", 1)
        enabled = self.enabled_games()
        if len(enabled) > max_n:
            raise ModError("E_CAPABILITY_DISABLED", detail=f"{len(enabled)} enabled games > max {max_n}")
        if not enabled:
            raise ModError("E_CAPABILITY_DISABLED", detail="no enabled game descriptor")
        return enabled

    def require(self, game_id: str, capability: str) -> dict:
        """Check the capability gate for one operation. Returns the descriptor."""
        d = self.get_game(game_id)
        caps = d.get("capabilities", {})
        if self.gate().get("refuse_if_capability_false", True) and not caps.get(capability, False):
            raise ModError("E_CAPABILITY_DISABLED", detail=f"capability {capability}=false for {game_id}")
        return d

    def single_enabled_game(self) -> str:
        return self.assert_enabled_count()[0]

    def active_descriptor(self) -> tuple[str, dict]:
        """Return (game_id, descriptor) for the one active game (pinned or
        registry.json-enabled). Useful for descriptor-driven callers."""
        gid = self.single_enabled_game()
        return gid, self.get_game(gid)

    def appid_for(self, game_id: str) -> int:
        d = self.get_game(game_id)
        return int(d["identity"]["appid"])

    def catalog(self) -> List[dict]:
        """P0 (round 2): pure read-only browse-by-category game catalog.

        Reads ONLY descriptor identity/capabilities/status from already-loaded
        in-memory descriptors. It NEVER calls get_game / require /
        active_descriptor (those enforce the capability gate and raise for
        planned games), NEVER resolves any mod_root or state_file, NEVER hits
        the network or filesystem, and NEVER mutates state.

        This is the "Plane 1" display catalog: showing more games here does NOT
        lift the single-active-game write gate (max_enabled_games_in_mvp: 1).
        Planned / unsupported descriptors are returned with enabled=False so
        the UI can render them as a grey "catalog-only, not installable" row.
        All values are JSON-safe primitives (str / int / bool / None / list /
        dict); loaders tolerate both string ids and dict-shaped entries.
        """
        g = self.gate()
        enabled_status = g.get("enabled_game_status", "enabled")
        active = self.raw.get("active_game")
        out: List[dict] = []
        for gid, d in self.descriptors.items():
            if not isinstance(d, dict):
                continue
            ident = d.get("identity")
            if not isinstance(ident, dict):
                ident = {}
            status = str(d.get("status") or "planned")
            caps = d.get("capabilities")
            if not isinstance(caps, dict):
                caps = {}
            loaders = d.get("loaders")
            if not isinstance(loaders, list):
                loaders = []
            norm_loaders: List[str] = []
            for l in loaders:
                if isinstance(l, str):
                    norm_loaders.append(l)
                elif isinstance(l, dict):
                    norm_loaders.append(str(l.get("id") or l.get("name") or "loader"))
                else:
                    norm_loaders.append(str(l))
            raw_appid = ident.get("appid")
            try:
                appid = int(raw_appid) if raw_appid is not None else None
            except (ValueError, TypeError):
                appid = None
            is_enabled = status == enabled_status
            out.append({
                "id": str(gid),
                "name": str(ident.get("name") or d.get("display_label") or gid),
                "appid": appid,
                "platform": str(ident.get("platform") or "unknown"),
                "status": status,
                "enabled": is_enabled,
                "active": gid == active,
                "operable": is_enabled,
                "engine": str(d.get("engine") or "unknown"),
                "display_label": str(d.get("display_label") or gid),
                "loaders": norm_loaders,
                "capabilities": {str(k): bool(v) for k, v in caps.items()},
            })
        return out
