#!/usr/bin/env python3
"""Run the browser end-to-end suites against throwaway demo servers.

    processing/venv/bin/python3 tests/e2e/run.py              # every suite
    processing/venv/bin/python3 tests/e2e/run.py bookmarks    # one suite
    processing/venv/bin/python3 tests/e2e/run.py --fresh      # re-render/re-analyse the demo games

Needs Playwright in processing/venv (pip install -r tests/requirements.txt;
playwright install chromium). Never touches videos/: every suite gets a fresh
copy of the synthetic demo library and its own Vite server on a free port.
"""
import argparse
import importlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import CHROMIUM_ARGS, Checks, demo_server, log, prepare_demo_library  # noqa: E402

SUITES = ("player", "bookmarks")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("suites", nargs="*", help=f"suites to run: {', '.join(SUITES)} (default: all)")
    ap.add_argument("--fresh", action="store_true", help="re-analyse the demo games first")
    args = ap.parse_args()
    unknown = [s for s in args.suites if s not in SUITES]
    if unknown:
        ap.error(f"unknown suite(s): {', '.join(unknown)}; choose from {', '.join(SUITES)}")
    from playwright.sync_api import sync_playwright

    library = prepare_demo_library(fresh=args.fresh)
    results = []
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        for name in args.suites or SUITES:
            log(f"=== suite: {name} ===")
            checks = Checks(name)
            with demo_server(library) as (base, run_dir):
                try:
                    importlib.import_module(f"test_{name}").run(base, run_dir, checks, browser)
                except Exception as e:  # a crash is a failure, with context
                    checks.check(f"suite ran to the end ({type(e).__name__}: {e})", False)
            results.append(checks)
        browser.close()
    print()
    failed = 0
    for c in results:
        n_fail = len(c.failed)
        failed += n_fail
        print(f"{c.suite:10} {len(c.results) - n_fail}/{len(c.results)} passed")
        for name, _, detail in c.failed:
            print(f"   FAIL {name}" + (f"  [{detail}]" if detail else ""))
    print(f"total {sum(len(c.results) for c in results) - failed}/{sum(len(c.results) for c in results)} in {time.time() - t0:.0f}s")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
