"""Small stdlib-only development and distribution commands."""
import json
import os
import sqlite3
import sys
import unittest

from qnaplibrary import VERSION
from qnaplibrary.server import main


def serve(args):
    # Never silently reuse a cwd-relative database when adopting the new alias.
    if not any(a in ("--help", "-h", "--version", "--data") or a.startswith("--data=")
               for a in args) and not os.environ.get("QNAPLIBRARY_DATA"):
        print("Specify --data DIR (or QNAPLIBRARY_DATA). No database was opened.", file=sys.stderr)
        return 2
    return main(args)


def doctor():
    # In-memory only: do not initialize config, secrets, or a database directory.
    with sqlite3.connect(":memory:") as db:
        try:
            db.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
            fts5 = True
        except sqlite3.OperationalError:
            fts5 = False
    supported = sys.version_info >= (3, 9)
    print(json.dumps({"app": "ResearchDataHub", "version": VERSION,
                      "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
                      "fts5": fts5, "supported": supported}))
    return 0 if supported else 1


def cli(args=None):
    args = list(sys.argv[1:] if args is None else args)
    command = args.pop(0) if args else "help"
    if command == "serve":
        return serve(args)
    if command == "doctor" and not args:
        return doctor()
    if command == "test" and not args:
        suite = unittest.defaultTestLoader.loadTestsFromName("researchdatahub.smoke")
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    print("Usage: rdh.sh doctor | serve --data DIR [server options] | test")
    return 0 if command in ("help", "--help", "-h") else 2


if __name__ == "__main__":
    sys.exit(cli())
