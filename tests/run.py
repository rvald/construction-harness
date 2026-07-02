"""Minimal test runner (offline stand-in for pytest).

Discovers tests/test_*.py, runs every top-level `test_*` function, and reports
pass/fail with tracebacks. Same test signatures as pytest, so switching back to
`pytest` later requires no changes to the test files.

Run:  python tests/run.py            # all tests
      python tests/run.py spec       # only files whose name contains "spec"
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # make `src` importable


def _load(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str]) -> int:
    needle = argv[0] if argv else ""
    test_files = sorted(p for p in (ROOT / "tests").glob("test_*.py") if needle in p.name)

    passed = failed = 0
    failures: list[str] = []
    for path in test_files:
        try:
            mod = _load(path)
        except Exception:
            print(f"ERROR {path.name} (could not import)")
            failures.append(f"{path.name} (import)\n" + traceback.format_exc())
            failed += 1
            continue
        for name in sorted(dir(mod)):
            if not name.startswith("test_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            label = f"{path.name}::{name}"
            try:
                fn()
                print(f"PASS  {label}")
                passed += 1
            except Exception:
                print(f"FAIL  {label}")
                failures.append(label + "\n" + traceback.format_exc())
                failed += 1

    print("-" * 60)
    print(f"{passed} passed, {failed} failed")
    for f in failures:
        print("\n" + f)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))