# Is the game running? — and why the answer had to stop being an environment variable

Goal item 6 asked what the plugin still needs. This page records a gap that was
worse than a missing feature: a **promise the code did not keep**.

## The gap

`registry/games/stardew.json` has said

```json
"safety": { "refuse_if_game_running": true, ... }
```

since Round 39. Four destructive operations consult it —
`_install_inner`, `_set_enabled_inner`, `_uninstall_inner`, `_rollback_inner` —
and each begins with `self._check_not_running()`.

That function was three lines:

```python
marker = os.environ.get("DECKYMOD_GAME_RUNNING")
if marker and marker.lower() in ("1", "true", "yes"):
    raise ModError("E_GAME_RUNNING", detail="DECKYMOD_GAME_RUNNING is set")
```

Nothing in production sets that variable. It is a **test seam** — the synthetic
trees in `tests/` set it so the refusal path can be exercised. So the flag was
`true`, the call sites were all present and correct, and the check never fired on
a real device. The plugin would uninstall a mod while the game had its `.dll`
files open.

This is the one failure in this plugin that a rollback cannot repair: a game that
loses files it loaded can write a corrupt save before it exits.

## What the device actually allows

Measured before writing any code:

| Question | Answer on this Deck |
| --- | --- |
| How is `/proc` mounted? | `proc /proc proc rw,nosuid,nodev,noexec,relatime` |
| How many processes are listed? | 322 |
| How many expose a readable `cmdline` to uid 1000? | 320 |
| Can a foreign-uid process be read? | yes — `1 root :: /sbin/init splash`, `1279 root :: /home/deck/homebrew/services/PluginLoader` |

A previous note in this repo said "/proc is unreadable". That was about a
**different file**: the plugin cannot read its own
`/proc/self/environ`, because the setuid drop clears `dumpable`. `cmdline` is a
separate file with separate permissions, and it is readable.

The decisive property is not the permissive mount though. The game runs as the
**same user** as the plugin, and `hidepid=2` hides *other users'* processes,
never your own. So a same-uid game stays visible even on a hardened mount. This
check does not depend on this device happening to be lax.

## What was built

`deckymod/procs.py` — read-only, ~170 lines, no writes anywhere (asserted by an
AST test).

Two narrow signals, and deliberately only two:

- the **basename of `argv[0]`** is one of the descriptor's
  `running_process_markers`, or
- **`argv[0]` lies inside `GAME_ROOT`**.

Both read `argv[0]` only. A terminal whose working directory is `Mods/`, or whose
arguments mention the game, is not the game — that is the case a substring search
would get wrong, and it is why the marker is compared against the executable name
rather than the whole command line.

`unknown` is a first-class answer. If `/proc` cannot be listed at all, the state
is `unknown`, not `stopped`:

> "I could not check" and "it is not running" are different claims, and only one
> of them is safe to act on.

The plugin's own pid is skipped. Its `argv` mentions the game folder (it is
passed as an argument), and counting that would make every write refuse forever.

## Where it shows up

| Surface | What appears |
| --- | --- |
| `status().state.running` | `{state, pid, match, scanned, detail}` |
| refuse path | `E_GAME_RUNNING` with the evidence: `the game is running (pid 1403326: /tmp/StardewModdingAPI)` |
| panel | one line: "The game is running — close it before changing mods." / "Whether the game is running could not be checked." |

`unknown` deliberately does **not** refuse. Refusing on it would mean the plugin
silently does nothing on any host whose `/proc` is restricted, which is a worse
failure than the one this round fixes. The journal and `post_commit_verify` are
what cover the remaining window.

## Proven on the device

Nothing was installed, enabled, or deleted by the probe; it made a process whose
`argv[0]` looks like the launcher (`exec -a`, no file created, game folder
untouched), asked the plugin, then removed it.

```
=== A. nothing running
A STATE=stopped PID= MATCH= SCANNED=326

=== B. fake launcher alive (argv[0] basename marker)
B STATE=running PID=1403326 MATCH=/tmp/StardewModdingAPI SCANNED=326
B DESCRIBE='the game is running (pid 1403326: /tmp/StardewModdingAPI)'
B PLUGIN_STATE=running PLUGIN_PID=1403326
GATE_OK=False CODE=E_GAME_RUNNING
GATE_DETAIL=the game is running (pid 1403326: /tmp/StardewModdingAPI)

=== C. fake executable inside GAME_ROOT (path branch)
C STATE=running PID=1403331 MATCH=/home/deck/.local/share/Steam/steamapps/common/Stardew Valley/Stardew Valley SCANNED=325
C PLUGIN_STATE=running PLUGIN_PID=1403331

=== D. after cleanup
D STATE=stopped PID= MATCH= SCANNED=325
D PLUGIN_STATE=stopped
```

B proves the marker branch, C proves the path branch, and `GATE_OK=False` proves
a real write was **refused** — which is the thing the old code could never do.

An independent scan of `/proc` in the same run found `PROC_HITS 0`, so `stopped`
was not a lucky guess.

## Tests

| File | Cases | What it settles |
| --- | --- | --- |
| `tests/test_procs.py` | 17 | the decision logic, against faked `/proc` (Windows has none) |
| `tests/test_running_gate.py` | 9 | the gate is **wired** — every destructive op refuses on a real engine and a real tree |

Two layers on purpose. A correct detector nothing calls is exactly the bug this
round exists to fix, so the second file drives `StardewEngine` and asserts the
error a user would see.

Full suite: `Ran 595 tests / OK (skipped=9)`.

## Not proven

- A real Stardew Valley process (the game is not launched during these runs; the
  positive case uses an `exec -a` stand-in with the same `argv[0]` shape).
- A host where `/proc` is genuinely hidden — the `unknown` path is exercised with
  a fake lister, not with `hidepid` enabled.
- Windows: `is_running()` correctly returns `unknown` there (no `/proc`), which
  is why the gate tests fake the module.
