# Where a mod's Nexus page comes from

Round 49. The plugin can already open a Nexus mod page in the Game Mode browser
(`open_mod_page`), but until this round it could only do that for a mod id the
**user typed in**. For a mod that is already installed there was no id — and
guessing one from the folder or display name would open someone else's mod.

There is one trustworthy source: the mod's own manifest declares it.

## What real manifests actually contain

Measured on this Deck, 30 installed mod directories, `UpdateKeys` read straight
out of each `manifest.json`:

| shape | count | example |
|---|---|---|
| plain `Nexus:<digits>` | 21 | `Automate` → `Nexus:1063` |
| `Nexus:<digits>@<channel>` | 2 | `Place Furniture Outside (...) New Version 1.6` → `Nexus:21147@New` |
| other site only (github / moddrop / chucklefish) | 1 | `DestroyableBushes` also carries `github:Esca-MMC/DestroyableBushes`, `moddrop:798245` |
| two Nexus channels on one mod | 2 mods | `Xiddav's Little Red School House` → `9695@Regular`; its `- Students and Teachers` sibling → `9695@Students` |
| no `UpdateKeys` at all | 4 | `ConsoleCommands`, `SaveBackup`, `ivory.sdvhd2d`, `selph.furnituremachine` |

After wiring, the live process reports **24 of 30 directories with a Nexus id**.

## Why the strict regex was wrong

The obvious implementation is `^Nexus(\d+)$`. On this device that silently
drops two real mods, because their keys carry a channel suffix:

```
Place Furniture Outside (Furniture Anywhere Redux) New Version 1.6
    -> ['Nexus:21147@New']
Xiddav's Little Red School House
    -> ['Nexus:9695@Regular']
```

Silently is the problem. A dropped key looks exactly like "this mod declares
nothing", which is a claim the plugin is not entitled to make.

So `deckymod/updatekeys.py` parses `site:id[@channel]` generally, and keeps the
channel as a **separate field** rather than gluing it into the id: `21147@New` is
not an id, and putting it in a URL would produce a 404. `id_for(keys, "nexus")`
returns `"21147"`.

## Two shapes that look like keys and are not

- **A URL is not a key.** `https://example.com/x` matches `site:id` with
  `site="https"` unless that is refused. A shape that parses into something
  plausible but meaningless is worse than a rejection, so `http`, `https`,
  `file` and `ftp` are explicitly not sites.
- **An already-parsed list is not a raw string.** This one shipped as a real bug
  and the device caught it: `id_for()` only cleaned strings, so handing it the
  wire payload (a list of `{site,id,channel}`) returned `""` for every mod. The
  probe said `WITH_NEXUS_ID 0` while the data plainly had ids. `parse()` now
  accepts its own output, and two regression tests pin the round trip.

## Surface

| field | where | meaning |
|---|---|---|
| `update_keys` | each entry of `status().state.mods` | `[{site, id, channel}]`; **empty means the manifest declared nothing**, never a guess |
| "Declared update keys: …" | my-mods detail dialog | the raw declarations, so a user can see why a button is or is not there |
| "Open mod page" | my-mods detail dialog | shown only when a Nexus id parsed to a positive integer; calls the existing `open_mod_page` RPC, no new RPC |

## Proven

- 30 real directories parsed; 24 report a Nexus id; the 3 channel-shaped keys
  round-trip with `channel` intact (`New`, `Regular`, `Students`).
- Live process: `open_mod_page(1063)` returned
  `{"url": "https://www.nexusmods.com/stardewvalley/mods/1063", "opened": true}`
  and the CEF tab really navigated.
- 21 unit tests, including one that asserts the module contains no game literals
  (`stardew`, `413150`, `smapi`, `stardewvalley`) and performs no file writes.

## Not proven

- Nobody has pressed "Open mod page" with a gamepad. Only the RPC was proven, by
  calling it directly.
- Whether a channel-qualified key (`@Students`) points at a *different* page
  than the plain one was not checked against the site; the id is opened as-is.
- A mod whose manifest is unreadable has no keys and therefore no button. That
  is the honest outcome, not a gap to paper over.
