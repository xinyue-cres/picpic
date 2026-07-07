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
        report = analyze_all(
            conn,
            library,
            run_clip=not args.no_clip,
            force_clip=args.force_clip,
            clip_only=args.clip_only,
        )
    finally:
        conn.close()
    clip_line = ""
    if report.clip is not None:
        c = report.clip
        clip_line = (
            f" clip=processed:{c.processed}/failed:{c.failed}/skipped:{c.skipped}"
        )
    print(
        f"analyze: exif={report.exif} hashes={report.hashes} "
        f"similar={report.similar} blur={report.blur}{clip_line}"
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


def _cmd_categories(args) -> int:
    from .categories import (
        CATEGORIES_FILENAME,
        CategoriesError,
        check_categories,
        load_categories,
        write_default,
        yaml_available,
    )
    if not yaml_available():
        print(
            "error: PyYAML not installed. Install with: pip install '.[clip]'",
            file=sys.stderr,
        )
        return 2
    library = pathlib.Path(args.library).resolve()
    if (err := _require_library(library)) is not None:
        return err
    if args.init:
        try:
            path = write_default(library)
        except FileExistsError:
            print(
                f"error: {CATEGORIES_FILENAME} already exists in {library}",
                file=sys.stderr,
            )
            return 1
        except CategoriesError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {path}")
        return 0
    if args.check:
        problems = check_categories(library)
        if not problems:
            print("ok")
            return 0
        for msg in problems:
            print(f"problem: {msg}", file=sys.stderr)
        return 1
    if args.list:
        try:
            cfg = load_categories(library)
        except FileNotFoundError:
            print(
                f"error: {CATEGORIES_FILENAME} not found in {library}. "
                f"Run: picpic categories {library} --init",
                file=sys.stderr,
            )
            return 1
        except CategoriesError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            f"version={cfg.version} model={cfg.model} "
            f"pretrained={cfg.pretrained} top_k={cfg.top_k}"
        )
        for c in cfg.categories:
            print(f"  - {c.name}: {c.prompt}")
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

    p = sub.add_parser("scan")
    p.add_argument("library")
    p.set_defaults(fn=_cmd_scan)

    p = sub.add_parser("analyze")
    p.add_argument("library")
    p.add_argument("--no-clip", action="store_true", help="skip CLIP pass")
    p.add_argument("--clip-only", action="store_true", help="run only CLIP")
    p.add_argument("--force-clip", action="store_true",
                   help="rerun CLIP on all photos, not just unlabeled")
    p.set_defaults(fn=_cmd_analyze)

    p = sub.add_parser("rules")
    p.add_argument("library")
    p.set_defaults(fn=_cmd_rules)

    p = sub.add_parser("all")
    p.add_argument("library")
    p.add_argument("--no-clip", action="store_true")
    p.add_argument("--clip-only", action="store_true")
    p.add_argument("--force-clip", action="store_true")
    p.set_defaults(fn=_cmd_all)

    p = sub.add_parser("serve")
    p.add_argument("library")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(fn=_cmd_serve)

    p = sub.add_parser("categories")
    p.add_argument("library")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--list", action="store_true")
    grp.add_argument("--check", action="store_true")
    grp.add_argument("--init", action="store_true")
    p.set_defaults(fn=_cmd_categories)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
