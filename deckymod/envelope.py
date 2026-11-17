"""The single JSON-safe response envelope used by EVERY backend callable.

Frontend contract (§5.2):
  { ok: bool, code: str|null, message: str, detail: str,
    data: any|null, rollback_available: bool, log_path: str, ts: str }

No Python object ever leaks: envelope() passes the whole payload through
json_safe.to_json_safe() (allow_nan=False) and json.dumps it with
allow_nan=False as a final gate.
"""

from __future__ import annotations

import datetime
from typing import Any

from .json_safe import to_json_safe

LOG_PATH_HINT = "${DECKY_PLUGIN_LOG_DIR}/deckymod.log"


def _ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def envelope(
    ok: bool,
    *,
    data: Any = None,
    code: str | None = None,
    message: str = "",
    detail: str = "",
    rollback_available: bool = False,
    log_path: str = LOG_PATH_HINT,
) -> dict:
    payload = {
        "ok": bool(ok),
        "code": code,
        "message": message,
        "detail": detail,
        "data": data,
        "rollback_available": bool(rollback_available),
        "log_path": log_path,
        "ts": _ts(),
    }
    # Hard JSON-safety gate: normalize then serialize-and-reparse so that a
    # stray Path/set/bytes can never reach the frontend bridge.
    safe = to_json_safe(payload)
    import json
    return json.loads(json.dumps(safe, allow_nan=False, ensure_ascii=False))


def ok(data: Any = None, **kw) -> dict:
    return envelope(True, data=data, **kw)


def err(code: str, *, detail: str = "", message: str = "", rollback_available=None, data=None) -> dict:
    from .errors import ERRORS, ModError
    e = ModError(code, detail=detail, rollback_available=rollback_available)
    return envelope(
        False,
        code=e.code,
        message=message or e.message,
        detail=detail,
        data=data,
        rollback_available=e.rollback_available,
    )
