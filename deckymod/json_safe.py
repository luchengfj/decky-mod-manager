"""JSON-safe normalization across the Python<->JS bridge (§1 / §7 V3).

Decky's callable() serializes return values with the stdlib json encoder.
These are the KNOWN unsafe types and the EXPLICIT conversion policy:

  pathlib.Path / os.DirEntry  -> str                 (PosixPath -> TypeError otherwise)
  bytes / bytearray           -> {"__b64__":..., "len":...}  (never raw / never latin-1 guess)
  set / frozenset             -> sorted list        (deterministic)
  datetime/date/time          -> .isoformat()
  Decimal                     -> str               (no float precision loss)
  NaN / Infinity float        -> None + sentinel   (allow_nan=False would raise)
  int > 2^53 (SteamID64!)     -> str               (JS Number loses precision)
  dict keys not str           -> str(key)
  mapping / namedtuple / dataclass -> dict via vars()/._asdict() when possible
  arbitrary objects           -> {"__repr__": repr(obj)}  (never silent default=str)

We NEVER use json.dumps(default=str): that hides Path/bytes bugs and turns
SteamID64 into a lossy float. Every outbound payload goes through here.
"""

from __future__ import annotations

import base64
import datetime
import decimal
import math
import os
from collections.abc import Mapping
from pathlib import Path

JS_MAX_SAFE_INT = 2 ** 53 - 1


def to_json_safe(value, _depth: int = 0):
    if _depth > 40:
        return {"__truncated__": True}

    # primitives
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        # SteamID64 is a 64-bit decimal string: return as str, not a JS Number.
        return value if -JS_MAX_SAFE_INT <= value <= JS_MAX_SAFE_INT else str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, str):
        return value

    # bytes -> explicit base64 object (never guess an encoding)
    if isinstance(value, (bytes, bytearray, memoryview)):
        b = bytes(value)
        return {"__b64__": base64.b64encode(b).decode("ascii"), "len": len(b)}

    # pathlib / DirEntry
    if isinstance(value, (Path, os.DirEntry)):
        return str(value)

    # datetime
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()

    if isinstance(value, decimal.Decimal):
        return str(value)

    # sets -> sorted deterministic list
    if isinstance(value, (set, frozenset)):
        return sorted((to_json_safe(v, _depth + 1) for v in value), key=lambda x: repr(x))

    # namedtuple
    if hasattr(value, "_asdict") and callable(value._asdict):
        return {str(k): to_json_safe(v, _depth + 1) for k, v in value._asdict().items()}

    # dataclass / simple object with __dict__
    if hasattr(value, "__dict__") and not isinstance(value, type):
        try:
            return {str(k): to_json_safe(v, _depth + 1) for k, v in vars(value).items() if not k.startswith("__")}
        except Exception:
            pass

    # mapping (dict keys coerced to str)
    if isinstance(value, Mapping):
        return {str(k): to_json_safe(v, _depth + 1) for k, v in value.items()}

    # any other sequence
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v, _depth + 1) for v in value]

    return {"__repr__": repr(value)}
