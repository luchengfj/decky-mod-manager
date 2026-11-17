"""Local no-network verification helper (not a production module)."""
import os
import sys
import json
import glob
import compileall

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def main():
    ok = compileall.compile_dir(os.path.join(ROOT, "deckymod"), quiet=1)
    ok = compileall.compile_file(os.path.join(ROOT, "main.py"), quiet=1) and ok
    print("compileall:", "OK" if ok else "FAIL")
    bad = []
    files = [p for p in glob.glob(os.path.join(ROOT, "**", "*.json"), recursive=True)
             if "node_modules" not in p and "dist" not in p]
    for p in files:
        try:
            with open(p, encoding="utf-8") as f:
                json.load(f)
        except Exception as e:  # noqa
            bad.append((p, str(e)))
    print("json files:", len(files), "bad:", len(bad))
    for b in bad:
        print("  BAD", b)
    return 0 if (ok and not bad) else 1


if __name__ == "__main__":
    sys.exit(main())
