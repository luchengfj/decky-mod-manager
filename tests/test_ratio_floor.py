"""Round 27: the compression-ratio guard must reject bombs, not game assets.

A real Stardew content pack was refused with ``E_ZIP_BOMB ratio 101`` because
its map files are sparse 158 KB ``.btr`` blobs that compress ~390:1. The ratio
itself was never the danger — the uncompressed SIZE is. So the guard now only
considers entries at or above ``ratio_floor_bytes``.

These tests pin both halves of that sentence: a small sparse asset passes, and
a genuinely oversized bomb is still stopped (by the ratio rule above the floor,
and by the absolute cap regardless of ratio).
"""
import os
import unittest
import uuid
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from deckymod import archive  # noqa: E402
from deckymod.errors import ModError  # noqa: E402


def _tmpdir():
    """os.makedirs, not tempfile.mkdtemp: mkdtemp makes a 0o700 directory that
    the Windows sandbox then refuses to write into."""
    p = os.path.join(ROOT, ".decky-test-tmp", "r27ratio_" + uuid.uuid4().hex[:8])
    os.makedirs(p, exist_ok=True)
    return p


def _zip_with(path, members):
    """members: list of (name, bytes). Stored as deflate so ratios are real."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return path


class TestSmallSparseAssetIsAccepted(unittest.TestCase):
    """The exact shape that was wrongly refused: tiny, highly compressible."""

    def test_offending_ratio_passes_when_output_is_small(self):
        d = _tmpdir()
        p = os.path.join(d, "sparse.zip")
        # 158 KB of zeros compresses to a few hundred bytes: ratio ~390.
        blob = b"\x00" * 158551
        _zip_with(p, [("Maps/Town-Theater.btr", blob)])
        info = archive.inspect_zip(p, dict(archive.DEFAULT_LIMITS))
        self.assertEqual(info["entry_count"], 1)
        ratio = blob.__len__() / max(1, info["_zf_entries"][0].compress_size)
        self.assertGreater(ratio, archive.DEFAULT_LIMITS["max_compression_ratio"],
                           "fixture must actually exceed the ratio cap")

    def test_ratio_below_the_floor_is_ignored_even_when_extreme(self):
        d = _tmpdir()
        p = os.path.join(d, "tiny.zip")
        _zip_with(p, [("a.bin", b"\x00" * 4096)])
        info = archive.inspect_zip(p, dict(archive.DEFAULT_LIMITS))
        self.assertEqual(info["entry_count"], 1)


class TestRealBombsAreStillStopped(unittest.TestCase):
    def test_large_entry_over_the_ratio_cap_is_refused(self):
        d = _tmpdir()
        p = os.path.join(d, "bomb.zip")
        # 4 MiB of zeros: above ratio_floor_bytes AND above the ratio cap.
        _zip_with(p, [("big.bin", b"\x00" * (4 * 1024 * 1024))])
        with self.assertRaises(ModError) as cm:
            archive.inspect_zip(p, dict(archive.DEFAULT_LIMITS))
        self.assertEqual(cm.exception.code, "E_ZIP_BOMB")

    def test_total_uncompressed_cap_still_applies_regardless_of_ratio(self):
        d = _tmpdir()
        p = os.path.join(d, "many.zip")
        lim = dict(archive.DEFAULT_LIMITS)
        lim["max_uncompressed_bytes"] = 1024
        # Each member is small enough to dodge the ratio rule (below the floor)
        # but together they blow the absolute cap.
        _zip_with(p, [("f%d.bin" % i, b"x" * 512) for i in range(4)])
        with self.assertRaises(ModError) as cm:
            archive.inspect_zip(p, lim)
        self.assertEqual(cm.exception.code, "E_ZIP_BOMB")

    def test_floor_can_be_disabled_explicitly(self):
        """limits are merged over DEFAULT_LIMITS, so omitting the key cannot
        opt out — a caller that wants the old strict rule must set 0."""
        d = _tmpdir()
        p = os.path.join(d, "nofloor.zip")
        _zip_with(p, [("s.bin", b"\x00" * 158551)])
        lim = dict(archive.DEFAULT_LIMITS)
        lim["ratio_floor_bytes"] = 0
        with self.assertRaises(ModError) as cm:
            archive.inspect_zip(p, lim)
        self.assertEqual(cm.exception.code, "E_ZIP_BOMB")

    def test_partial_limits_dict_still_inherits_the_floor(self):
        """A caller passing only one limit must not silently lose the floor."""
        d = _tmpdir()
        p = os.path.join(d, "partial.zip")
        _zip_with(p, [("s.bin", b"\x00" * 158551)])
        info = archive.inspect_zip(p, {"max_entries": 4096})
        self.assertEqual(info["entry_count"], 1)


if __name__ == "__main__":
    unittest.main()
