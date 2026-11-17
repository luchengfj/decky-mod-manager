# Publishing this repository

What was removed, what was kept, and why — so a future maintainer can re-run the check instead of trusting it.

## What must never be committed

| Path | Why |
| --- | --- |
| `.decky-probe/` | Contains SSH **private keys** (`ssh/deck_key`, `ssh/dshdeck2`), an old API-key dump (`r9_cred.txt`), device screenshots, and probe output with machine-specific values. Whole directory is ignored. |
| `deckymod/credentials.py` consumers' data | The runtime API key lives at `${DECKY_DATA}/nexus_api_key` **on the Deck**, never in the repo. |
| `dist/`, `*.tar`, `*.tar.gz` | Build output. Rebuilt by CI; the installable ZIP is a Release asset. |
| `journal/`, `snapshots/`, `*.log` | Real device paths and transaction history. |

`.gitignore` covers all of the above. The check that matters is not the ignore file but
`git diff --cached --name-only` — see *Verification* below.

## Personal data removed from the docs

The documentation was written while the plugin was being tested on one specific Steam Deck, so it contained
that machine's identity. Every occurrence was replaced with a placeholder:

| Was | Now | Occurrences |
| --- | --- | --- |
| the machine's LAN IPv4 | `{{DECK_IP}}` | 14 |
| the same address before a re-address | `{{OLD_DECK_IP}}` | 3 |
| the device hostname | `{{DECK_HOSTNAME}}` | 8 |
| the local helper's TCP port | `{{HELPER_PORT}}` | 55 |
| that port before it changed | `{{OLD_HELPER_PORT}}` | 10 |
| the helper application's product name | `deck-helper` | 18 |

The two **literal** identifiers — the hostname and the helper's product name — are deliberately not printed
in this file either, because a redaction guide that quotes what it redacted re-introduces it. They are held in
`.decky-probe/r39_sanitize.py` (gitignored), which is the authoritative list.

Placeholders use `{{double braces}}` on purpose: GitHub's Markdown renderer drops unknown `<angle-bracket>`
tags, which would have deleted the text instead of redacting it.

**Deliberately kept**, because removing them would destroy the evidence they support:

- Loopback addresses (`127.0.0.1`, `0.0.0.0`) — they describe a browser debug port, not a person.
- `198.18.0.0/15` — a documentation range used to describe a DNS sinkhole, not a real host.
- Public CDN and API addresses (`172.64.145.202` is Cloudflare for `api.nexusmods.com`).
- A string that *looks* like an IPv4 but is an assembly version: `StardewUI, Version=0.6.1.0`.
- Absolute build paths (`C:\ai\SD\...`, `/home/deck/...`) inside verification records, because the records
  quote commands verbatim and a rewritten command is no longer evidence. These reveal a directory layout, not
  a person.

## Verification

Run this before every push:

```bash
# 1. Nothing sensitive is staged
git diff --cached --name-only | grep -Ei 'decky-probe|\.key$|\.pem$|dshdeck|cred' || echo "clean"

# 2. No LAN addresses or helper ports left in docs
grep -rn '192\.168\.' docs/ || echo "clean"
grep -rnE ':5[0-9]{4}' docs/ || echo "clean"

# 3. No literal personal identifiers left (the patterns live in the ignored script,
#    so this file does not re-introduce them)
python3 .decky-probe/r39_leak.py docs/

# 4. The tree still builds and tests
python -m unittest discover -s tests
```

A dry run of the sanitizer is reproducible: `.decky-probe/r39_sanitize.py` prints the per-file replacement
counts; `--apply` performs them. Both are idempotent — a second run reports `REPLACEMENTS 0`.

## Credentials in the UI (not yet implemented)

If a future feature needs a per-user secret, it must follow these rules — they are the same rules the earlier
`credentials.py` enforced, and they were not relaxed by removing it:

1. **Stored locally only**, at `${DECKY_DATA}/<name>`, mode `0o600`, never in the repo and never in a log.
2. **Never echoed.** The status RPC returns `{present, path, mode_requested, mode_actual, mode_ok}` — never the
   value. Set returns `{stored, path}`. A validation call returns the *server's* answer, scrubbed of the key.
3. **Never in an error message.** Any exception text that could contain the secret is redacted before it
   reaches the QAM.
4. **Deletable**, with the deletion reported honestly (`{deleted: false, reason}` when there was nothing to
   delete).
5. **Not a password store.** Only long-lived API tokens issued by the service itself; never an account password,
   never a session cookie.
