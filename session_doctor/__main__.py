"""__main__.py – CLI entry point for session_doctor."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .loader import build_index, collect_files, detect_fastapi_version, _version_gte_118
from .graph import OwnershipGraph
from .rules import RuleEngine
from .report import build_json_report, format_json, format_text, should_fail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="session_doctor",
        description="Static analyzer for FastAPI + SQLAlchemy session hygiene.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="Scan a directory for session violations.")
    scan_parser.add_argument("path", type=Path, help="Root directory to scan.")
    scan_parser.add_argument(
        "--format", choices=["json", "text"], default="text",
        dest="fmt", help="Output format (default: text).",
    )
    scan_parser.add_argument(
        "--out", type=Path, default=None, metavar="FILE",
        help="Write output to FILE instead of stdout.",
    )
    scan_parser.add_argument(
        "--fail-on", choices=["high", "medium", "never"], default="high",
        dest="fail_on",
        help="Exit with code 1 if any finding is at or above this severity (default: high).",
    )

    args = parser.parse_args(argv)

    if args.command == "scan":
        return _run_scan(args)

    parser.print_help()
    return 2


def _run_scan(args: argparse.Namespace) -> int:
    root = args.path.resolve()
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"error: path is not a directory: {root}", file=sys.stderr)
        return 2

    # Detect FastAPI version
    fastapi_version, fastapi_version_assumed = detect_fastapi_version(root)
    fastapi_gte_118 = _version_gte_118(fastapi_version)

    # Build index
    index, parse_errors = build_index(root)

    # Build ownership graph
    graph = OwnershipGraph(index)

    # Run rules
    engine = RuleEngine(index, graph, fastapi_gte_118)
    findings = engine.run()

    # Count files
    files_scanned = len(index.file_module)

    # Build report
    scanned_root_str = root.as_posix()
    report = build_json_report(
        findings=findings,
        scanned_root=scanned_root_str,
        files_scanned=files_scanned,
        fastapi_version=fastapi_version,
        fastapi_version_assumed=fastapi_version_assumed,
        parse_errors=parse_errors,
    )

    # Format output
    if args.fmt == "json":
        output = format_json(report)
    else:
        output = format_text(report)

    # Write or print
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output)

    return 1 if should_fail(findings, args.fail_on) else 0


if __name__ == "__main__":
    sys.exit(main())
