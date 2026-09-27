"""report.py – JSON and text output formatting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .rules import Finding

_RULE_NAMES = {
    "SD001": "commit-after-yield",
    "SD002": "helper-commits",
    "SD003": "read-after-commit",
    "SD004": "lazy-relationship",
    "SD005": "begin-after-autobegin",
    "SD006": "shared-session-concurrency",
    "SD007": "unsafe-background-work",
    "SD008": "session-outlives-request",
}


def build_json_report(
    findings: list[Finding],
    scanned_root: str,
    files_scanned: int,
    fastapi_version: str | None,
    fastapi_version_assumed: bool,
    parse_errors: list[tuple[str, str, int]],
) -> dict[str, Any]:
    high = sum(1 for f in findings if f.severity == "high")
    medium = sum(1 for f in findings if f.severity == "medium")
    needs_review = sum(1 for f in findings if f.confidence == "needs_review")

    result: dict[str, Any] = {
        "tool": "session_doctor",
        "version": "0.1.0",
        "scanned_root": scanned_root,
        "files_scanned": files_scanned,
        "fastapi_version": fastapi_version or "unknown",
        "fastapi_version_assumed": fastapi_version_assumed,
        "summary": {
            "high": high,
            "medium": medium,
            "needs_review": needs_review,
        },
        "findings": [_finding_to_dict(f) for f in findings],
    }
    if parse_errors:
        result["parse_errors"] = [
            {"file": e[0], "message": e[1], "line": e[2]} for e in parse_errors
        ]
    return result


def _finding_to_dict(f: Finding) -> dict[str, Any]:
    return {
        "rule": f.rule,
        "name": f.name,
        "severity": f.severity,
        "confidence": f.confidence,
        "file": f.file,
        "line": f.line,
        "function": f.function,
        "message": f.message,
        "fix_hint": f.fix_hint,
    }


def format_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=False)


def format_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"  session_doctor v{report['version']}  --  {report['scanned_root']}")
    lines.append("=" * 70)
    lines.append(
        f"  Files scanned : {report['files_scanned']}"
    )
    fv = report.get("fastapi_version", "unknown")
    assumed = " (assumed)" if report.get("fastapi_version_assumed") else ""
    lines.append(f"  FastAPI       : {fv}{assumed}")
    s = report["summary"]
    lines.append(
        f"  Findings      : {s['high']} high  |  {s['medium']} medium  |  "
        f"{s['needs_review']} needs-review"
    )
    lines.append("")

    if not report["findings"]:
        lines.append("  No findings.")
    else:
        for f in report["findings"]:
            sev_tag = f"[{f['severity'].upper():6}]"
            conf_tag = "" if f["confidence"] == "high" else " (needs_review)"
            lines.append(
                f"  {f['rule']} {sev_tag}  {f['file']}:{f['line']}{conf_tag}"
            )
            lines.append(f"    {f['name']}  in  {f['function']}")
            lines.append(f"    {f['message']}")
            lines.append(f"    Fix: {f['fix_hint']}")
            lines.append("")

    if report.get("parse_errors"):
        lines.append("  PARSE ERRORS:")
        for e in report["parse_errors"]:
            lines.append(f"    {e['file']}:{e['line']}  {e['message']}")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def should_fail(findings: list[Finding], fail_on: str) -> bool:
    if fail_on == "never":
        return False
    if fail_on == "medium":
        return any(f.severity in ("high", "medium") for f in findings)
    # Default: high
    return any(f.severity == "high" for f in findings)
