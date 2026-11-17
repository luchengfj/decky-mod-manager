"""Error codes and JSON-safe exception type.

Every user-visible failure is one of these codes. The frontend shows a
friendly message + the code in small text + a log path; raw tracebacks are
never surfaced (see envelope.py / main.py). Constraint-enforcement messages
must NOT contain 'steamos-readonly disable', 'sudo', or 'flatpak override'
instructions (§5.2).
"""

from __future__ import annotations

# code -> (category, short user-facing message, whether rollback is offered)
ERRORS = {
    # --- bridge / backend ---
    "E_BACKEND_UNREACHABLE": ("bridge", "Backend is not reachable. Reopen the plugin or restart the Steam Deck.", False),
    "E_BRIDGE": ("bridge", "Communication with the plugin backend failed.", False),
    "E_UNKNOWN": ("internal", "An unexpected error occurred. See the log for details.", False),

    # --- capability / game selection ---
    "E_GAME_NOT_FOUND": ("discovery", "The configured game was not found in any Steam library.", False),
    "E_GAME_AMBIGUOUS": ("discovery", "The configured game was found in more than one Steam library; cannot choose automatically.", False),
    "E_CAPABILITY_DISABLED": ("capability", "This action is not available in this version.", False),
    "E_GAME_RUNNING": ("safety", "The game is running. Close it before changing mods.", False),
    "E_FLATPAK_PERMISSION": ("environment", "Flatpak Steam uses an isolated library path. This build does not manage it.", False),
    "E_LOADER_REQUIRED": ("planned", "This sample game does not need a loader. (Reserved for planned games.)", False),
    "E_PROTON_PREFIX_MISSING": ("planned", "This sample game does not need a Proton prefix. (Reserved for planned games.)", False),
    # --- stardew / SMAPI detect-only (2026-11-14) ---
    "E_LOADER_MISSING": ("environment", "SMAPI was not detected. This plugin does NOT install SMAPI; install it yourself or fix the launch options.", False),
    "E_LAUNCH_OPTIONS_MISSING": ("environment", "The Steam launch options do not point at SMAPI. This plugin does NOT edit launch options.", False),
    "E_EXTERNAL_MANAGER": ("safety", "Another mod manager owns this Mods folder (symlink deployment detected). Read-only mode: install/enable/uninstall/rollback are refused to avoid damaging it.", False),
    "E_MANIFEST_UNSAFE": ("import", "The SMAPI manifest.json is missing required fields or has an invalid UniqueID.", False),

    # --- target resolution (round 52) ---
    # Reusing E_DUPLICATE here was a real bug: its message says "already
    # installed, use Replace", which is the opposite of "there is nothing by
    # that name". Three different operations (uninstall / disable / enable)
    # hit it, and a user type-checking the name will meet it more than once.
    "E_MOD_NOT_FOUND": ("discovery", "No installed mod matches this name. Refresh the list; it may have been removed already.", False),

    # --- inbox / import ---
    "E_INBOX_MISSING": ("import", "The import folder does not exist.", False),
    "E_INBOX_EMPTY": ("import", "No ZIP files found in the import folder.", False),
    "E_INBOX_UNREADABLE": ("import", "A file in the import folder could not be read.", False),
    "E_PATH_INVALID": ("safety", "The given path is not allowed.", False),
    "E_PATH_ESCAPE": ("safety", "The path points outside an allowed folder.", False),
    "E_NOT_ALLOWED_ROOT": ("safety", "The target is outside the allowed write locations.", False),
    "E_BAD_ARCHIVE": ("import", "The file is not a valid ZIP archive.", False),
    "E_ZIP_BOMB": ("import", "The archive is too large or too highly compressed to import safely.", False),
    "E_ZIP_SLIP": ("import", "The archive contains a path that escapes the mod folder.", False),
    "E_UNSAFE_ENTRY": ("import", "The archive contains an unsafe entry (link, device, or forbidden file type).", False),
    "E_DUPLICATE_ENTRY": ("import", "The archive contains duplicate file names.", False),
    "E_MANIFEST_MISSING": ("import", "About/About.xml was not found in the archive.", False),
    "E_MANIFEST_INVALID": ("import", "About/About.xml could not be parsed.", False),
    "E_ID_INVALID": ("import", "The mod's packageId is missing or invalid.", False),
    "E_FIELD_MISSING": ("import", "A required field is missing from About.xml.", False),

    # --- conflict ---
    "E_DUPLICATE": ("conflict", "This mod (same packageId) is already installed. Use Replace instead.", False),
    "E_FILE_COLLISION": ("conflict", "A folder with this name already exists and is not managed by this plugin.", False),

    # --- filesystem / permissions ---
    "E_ACCESS": ("fs", "Permission denied while writing. The location may be read-only.", False),
    "E_READONLY_FS": ("fs", "The target filesystem is read-only; no files were changed.", False),
    "E_NO_SPACE": ("fs", "Not enough free space to complete the operation.", False),
    "E_CROSS_DEVICE": ("fs", "The staging and target are on different filesystems; operation refused.", False),
    "E_FS_NO_POSIX": ("info", "This drive (e.g. microSD/exFAT) has no POSIX permissions; ownership checks were skipped.", False),
    "E_ROOT_OWNED": ("fs", "A target file is owned by another user; refusing to change its permissions.", False),
    "E_STATE_OWNED": ("fs", "The game state file is owned by another user; refusing to edit it.", False),
    "E_STATE_SYMLINK": ("safety", "The game state file is a symbolic link; refusing to edit it.", False),
    "E_STAGING_IN_MODS": ("safety", "Staging/quarantine must not be placed inside the Mods folder.", False),
    "E_INODE_MISMATCH": ("safety", "Files changed between the safety check and the write; operation aborted.", False),

    # --- state file ---
    "E_CORE_MISSING": ("state", "Core (ludeon.rimworld) is missing or not first in ModsConfig.xml; refusing to edit.", False),
    "E_STATE_CORRUPT": ("state", "ModsConfig.xml could not be parsed; refusing to edit it.", False),
    "E_STATE_EXTERNAL": ("state", "ModsConfig.xml was changed outside this plugin (or by the game on quit). Refresh and retry.", False),
    "E_STATE_MISSING": ("state", "ModsConfig.xml was not found at the expected location.", False),

    # --- transaction / rollback ---
    "E_VERIFY_FAILED": ("txn", "The post-write verification did not match what was planned.", True),
    "E_OP_FAILED": ("txn", "The operation failed and was rolled back where possible.", True),
    "E_RECOVERY_PENDING": ("txn", "A previous operation did not finish. Use Recover / Rollback first.", True),
    "E_ROLLBACK_FAILED": ("txn", "Automatic rollback could not finish. Your data is preserved in the quarantine folder; see the log.", True),
    "E_QUARANTINE_FULL": ("txn", "The quarantine folder is full; uninstall was refused.", False),
}


class ModError(Exception):
    """A single, JSON-safe, user-facing error."""

    def __init__(self, code: str, *, detail: str = "", context=None, rollback_available=None):
        super().__init__(code)
        if code not in ERRORS:
            code = "E_UNKNOWN"
            if not detail:
                detail = "Unknown error code."
        self.code = code
        self.category, self.message, default_rollback = ERRORS[code]
        self.detail = detail
        self.context = context or {}
        self.rollback_available = default_rollback if rollback_available is None else bool(rollback_available)


def make_error(code: str, **kw) -> ModError:
    return ModError(code, **kw)
