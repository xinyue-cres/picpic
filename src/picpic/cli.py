from __future__ import annotations

import argparse
import pathlib
import sys

from .db import open_db


def _db_path(library: pathlib.Path) -> pathlib.Path:
    return library / "picpic.db"


def _require_library(library: pathlib.Path) -> int | None:
    """Return error code 2 if library is invalid, else None."""
    if not library.exists() or not library.is_dir():
        print(
            f"error: library not found or not a directory: {library}",
            file=sys.stderr,
        )
        return 2
    return None


def _cmd_scan(args) -> int:
    from .scan import scan_library
    library = pathlib.Path(args.library).resolve()
    if (err := _require_library(library)) is not None:
        return err
    conn = open_db(_db_path(library))
    try:
        report = scan_library(library, conn)
    finally:
        conn.close()
    print(
        f"scan: added={report.added} "
        f"already_present={report.already_present} skipped={report.skipped}"
    )
    return 0


def _cmd_analyze(args) -> int:
    from .analyze.runner import analyze_all
    library = pathlib.Path(args.library).resolve()
    if (err := _require_library(library)) is not None:
        return err
    conn = open_db(_db_path(library))
    try:
        report = analyze_all(conn)
    finally:
        conn.close()
    print(
        f"analyze: exif={report.exif} hashes={report.hashes} "
        f"similar={report.similar} blur={report.blur}"
    )
    return 0


def _cmd_rules(args) -> int:
    from .rules import apply_rules
    library = pathlib.Path(args.library).resolve()
    if (err := _require_library(library)) is not None:
        return err
    conn = open_db(_db_path(library))
    try:
        report = apply_rules(conn)
    finally:
        conn.close()
    print(
        f"rules: kept={report.kept} candidates={report.candidates} "
        f"unanalyzed={report.unanalyzed} reasons={report.by_reason}"
    )
    return 0


def _cmd_all(args) -> int:
    library = pathlib.Path(args.library).resolve()
    if (err := _require_library(library)) is not None:
        return err
    for step in (_cmd_scan, _cmd_analyze, _cmd_rules):
        code = step(args)
        if code != 0:
            return code
    return 0


def _cmd_serve(args) -> int:
    from .web.app import serve
    library = pathlib.Path(args.library).resolve()
    if (err := _require_library(library)) is not None:
        return err
    serve(library, host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="picpic")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, fn in (
        ("scan", _cmd_scan),
        ("analyze", _cmd_analyze),
        ("rules", _cmd_rules),
        ("all", _cmd_all),
    ):
        p = sub.add_parser(name)
        p.add_argument("library")
        p.set_defaults(fn=fn)

    p = sub.add_parser("serve")
    p.add_argument("library")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(fn=_cmd_serve)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
