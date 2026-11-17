# Declared vs read: the descriptor keys nothing consults

Round 50, Round 51 and Round 52 all had the same shape: a field existed, the
code looked like it honoured it, and nothing read it. `refuse_if_game_running`
was `true` while the only implementation read an environment variable nobody
sets. `E_RECOVERY_PENDING` was documented in a docstring and never raised.
`Mods/` was assumed to exist. Each was found by accident.

So this round asked the question mechanically instead: **of every leaf key in
`registry/games/stardew.json`, which are actually read by the backend?**

## What the audit found

`152` leaf keys. `111` are read by `deckymod/*.py` or `main.py`. `41` are not
mentioned in either the backend or the frontend.

That `41` is not 41 bugs. Reading the list separates it into three kinds:

| Kind | Examples | Verdict |
| --- | --- | --- |
| Prose for humans | `engine_note`, `loader_detection.on_external_manager`, `mod_package.field_map_note`, `capabilities_note` | Fine. They document the file. |
| Read generically | `capabilities.*` (14 keys) | Fine. `registry.require()` looks the name up in a dict, so no literal appears anywhere. The audit's `\b` name search cannot see that. |
| **Declared but ignored** | `loader_detection.external_manager_markers` | **A real defect.** See below. |

## The one real defect

`registry/games/stardew.json` declares:

```json
"loader_detection": {
  "external_manager_markers": [".mm_deployed", "Mods_Core"]
}
```

And `deckymod/file_drop.py` had:

```python
def detect_external_manager(game_root, mod_root):
    marker = os.path.join(mod_root, ".mm_deployed")
    core = os.path.join(game_root, "Mods_Core")
    return os.path.exists(marker) or os.path.isdir(core)
```

The same two strings, written twice, in a module whose docstring calls itself
game-agnostic. Because they agreed, nothing failed. The consequences are worth
spelling out:

* A descriptor for a **different** game could name its own marker, and the
  plugin would ignore it and keep looking for Amethyst's. That game's mod tree
  would be written into while the descriptor appeared to protect it.
* The key is the only place the rule is documented, so a reader concludes the
  behaviour is configurable. It was not.

## Why no test caught it

Every existing test planted `.mm_deployed` and asserted `E_EXTERNAL_MANAGER`.
That proves the engine refuses — it cannot distinguish "refused because the
descriptor said so" from "refused because a constant said so", because both
produced the same string. `deckymod/file_drop.py` had no direct test at all.

The new file `tests/test_external_markers.py` (14 cases) closes that by
testing the layer that had none, including the two negative cases that the
old design got wrong:

* a user mod folder **named** `Mods_Core` (inside `Mods/`) must NOT mark the
  tree as foreign — otherwise the plugin silently goes read-only for someone
  who did nothing wrong;
* a descriptor declaring its own marker must **replace** the defaults, not add
  to them.

## The fix

`detect_external_manager(game_root, mod_root, markers=None)` — the list is now
a parameter, and `None`/`[]` fall back to the historical pair so no existing
descriptor changes behaviour. `smapi.py` grows `_external_markers()` which
reads `loader_detection.external_manager_markers`, and both call sites pass it.

WHERE a name is searched is part of the evidence, not an implementation
detail: a marker is a **file** inside `Mods/` or a **directory** beside it in
the game root. The first draft of the fix checked `exists()` in both places,
and the `Mods_Core`-as-a-mod-folder test failed immediately — the fix had
introduced the exact false positive it was meant to avoid.

## Device proof that the descriptor decides

Two halves on the real machine. B2 and B3 use the **same tree**; only the
marker list differs.

```
=== B1. tree whose marker is .othermgr (NOT the Amethyst pair)
B1_FALLBACK_DETECTS    False        <- the hard-coded pair cannot see it
B1_DECLARED_DETECTS    True         <- the parameter works

=== B2. same shape, through the ENGINE, descriptor declares .othermgr
B2_UNINSTALL_CODE      E_EXTERNAL_MANAGER

=== B3. control: same tree, descriptor declares nothing recognisable
B3_UNINSTALL_CODE      E_MOD_NOT_FOUND
B3_NOT_EXTERNAL        True
```

B2 refusing is not the interesting part. B3 is: identical filesystem, no
refusal, because the shipped descriptor names the Amethyst pair. The refusal
in B2 came from the descriptor's list, which is the whole point.

The live plugin is unchanged, as it must be:

```
A_OK                 True
A_READ_ONLY          False
A_MODS               30
A_DESC_MARKERS       ['.mm_deployed', 'Mods_Core']
```

## Deliberately not done

`safety.refuse_if_external_manager` is also unread — and stays unread. The
marker check runs **unconditionally**, which is strictly stricter than the
descriptor's `true`. Honouring a descriptor that said `false` would turn an
always-on refusal into a switch that permits writing into another manager's
tree. An unread flag can only ever be a no-op, never a size.

## What this round did not fix

The `download_sources.github.api_host` / `asset_hosts` keys are in the same
category: declared in the descriptor, hard-coded as `API_HOST` / `ASSET_HOSTS`
in `deckymod/github_source.py`. They are left alone on purpose — those are
security allow-lists whose *values* happen to match, and making them
descriptor-driven would let a JSON edit change where the plugin downloads
from. Recorded in `docs/NEXT_FEATURES.md` rather than changed quietly.

## Bounds

| What | Value |
| --- | --- |
| new modules | 1 test file |
| new error codes | 0 (`errors.py` stays 51) |
| new RPCs | 0 (26 public) |
| changed signatures | 1 (`detect_external_manager` gains an optional arg) |
| descriptor keys now read | 1 |

## Proven / not proven

**Proven** — the audit's counts (`152` / `111` / `41`) on this tree; the false
positive on `Mods_Core`-as-a-folder; that the engine passes the descriptor's
list (AST-asserted, so a caller reverting to the 2-arg form fails the test);
the B1/B2/B3 device sequence above.

**Not proven** — that no *other* game's descriptor would hit a similar
constant. Only one game is described today, and the audit only examines that
one file.
