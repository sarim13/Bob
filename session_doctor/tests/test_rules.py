"""test_rules.py – integration tests for session_doctor rules.

Each test scans a single synthetic case file and asserts:
  - the BAD case triggers the expected rule
  - the GOOD case triggers no findings for that rule
"""

from __future__ import annotations

import ast

import pytest
from pathlib import Path

from session_doctor import loader as _loader
from session_doctor.graph import OwnershipGraph
from session_doctor.rules import RuleEngine, Finding

CASES = Path(__file__).parent / "cases"


def _scan(filename: str, fastapi_gte_118: bool = True) -> list[Finding]:
    """Build the index for a single case file and run all rules."""
    path = CASES / filename
    assert path.exists(), f"Case file not found: {path}"

    single_index = _loader.Index()
    module = _loader.path_to_module(path, path.parent)
    single_index.file_module[path.name] = module

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    ic = _loader._ImportCollector(module)
    ic.visit(tree)
    imports = ic.imports

    for local, qualified in imports.items():
        single_index.imports[(path.name, local)] = qualified

    _loader._collect_module_factories(tree, imports, module, path.name, single_index)

    collector = _loader._FunctionCollector(module, path.name, imports, single_index)
    collector.visit(tree)

    assigns = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                n = _loader._name_of(target)
                if n:
                    assigns.append((n, stmt.lineno, ast.unparse(stmt.value)))
        elif isinstance(stmt, ast.AnnAssign) and stmt.value:
            n = _loader._name_of(stmt.target)
            if n:
                assigns.append((n, stmt.lineno, ast.unparse(stmt.value)))
    single_index.module_assignments[module] = assigns

    graph = OwnershipGraph(single_index)
    engine = RuleEngine(single_index, graph, fastapi_gte_118)
    return engine.run()


def _rules(findings: list[Finding]) -> list[str]:
    return sorted({f.rule for f in findings})


# ---------------------------------------------------------------------------
# SD001
# ---------------------------------------------------------------------------


class TestSD001:
    def test_bad_triggers(self):
        findings = _scan("sd001_bad.py")
        assert "SD001" in _rules(findings), f"Expected SD001, got: {_rules(findings)}"

    def test_good_clean(self):
        findings = _scan("sd001_good.py")
        sd001 = [f for f in findings if f.rule == "SD001"]
        assert not sd001, f"Unexpected SD001: {sd001}"


# ---------------------------------------------------------------------------
# SD002
# ---------------------------------------------------------------------------


class TestSD002:
    def test_bad_triggers(self):
        findings = _scan("sd002_bad.py")
        assert "SD002" in _rules(findings), f"Expected SD002, got: {_rules(findings)}"

    def test_good_clean(self):
        findings = _scan("sd002_good.py")
        sd002 = [f for f in findings if f.rule == "SD002"]
        assert not sd002, f"Unexpected SD002: {sd002}"


# ---------------------------------------------------------------------------
# SD003
# ---------------------------------------------------------------------------


class TestSD003:
    def test_bad_triggers(self):
        findings = _scan("sd003_bad.py")
        assert "SD003" in _rules(findings), f"Expected SD003, got: {_rules(findings)}"

    def test_good_clean(self):
        findings = _scan("sd003_good.py")
        sd003 = [f for f in findings if f.rule == "SD003"]
        assert not sd003, f"Unexpected SD003: {sd003}"


# ---------------------------------------------------------------------------
# SD004
# ---------------------------------------------------------------------------


class TestSD004:
    def test_bad_triggers(self):
        findings = _scan("sd004_bad.py")
        assert "SD004" in _rules(findings), f"Expected SD004, got: {_rules(findings)}"

    def test_good_clean(self):
        findings = _scan("sd004_good.py")
        sd004 = [f for f in findings if f.rule == "SD004"]
        assert not sd004, f"Unexpected SD004: {sd004}"


# ---------------------------------------------------------------------------
# SD005
# ---------------------------------------------------------------------------


class TestSD005:
    def test_bad_triggers(self):
        findings = _scan("sd005_bad.py")
        assert "SD005" in _rules(findings), f"Expected SD005, got: {_rules(findings)}"

    def test_good_clean(self):
        findings = _scan("sd005_good.py")
        sd005 = [f for f in findings if f.rule == "SD005"]
        assert not sd005, f"Unexpected SD005: {sd005}"


# ---------------------------------------------------------------------------
# SD006
# ---------------------------------------------------------------------------


class TestSD006:
    def test_bad_triggers(self):
        findings = _scan("sd006_bad.py")
        assert "SD006" in _rules(findings), f"Expected SD006, got: {_rules(findings)}"

    def test_good_clean(self):
        findings = _scan("sd006_good.py")
        sd006 = [f for f in findings if f.rule == "SD006"]
        assert not sd006, f"Unexpected SD006: {sd006}"


# ---------------------------------------------------------------------------
# SD007
# ---------------------------------------------------------------------------


class TestSD007:
    def test_bad_triggers(self):
        findings = _scan("sd007_bad.py")
        assert "SD007" in _rules(findings), f"Expected SD007, got: {_rules(findings)}"

    def test_good_clean(self):
        findings = _scan("sd007_good.py")
        sd007 = [f for f in findings if f.rule == "SD007"]
        assert not sd007, f"Unexpected SD007: {sd007}"


# ---------------------------------------------------------------------------
# SD008
# ---------------------------------------------------------------------------


class TestSD008:
    def test_bad_triggers(self):
        findings = _scan("sd008_bad.py")
        assert "SD008" in _rules(findings), f"Expected SD008, got: {_rules(findings)}"

    def test_good_clean(self):
        findings = _scan("sd008_good.py")
        sd008 = [f for f in findings if f.rule == "SD008"]
        assert not sd008, f"Unexpected SD008: {sd008}"


# ---------------------------------------------------------------------------
# Determinism: same input → same output
# ---------------------------------------------------------------------------


class TestDeterminism:
    @pytest.mark.parametrize("filename", [
        "sd001_bad.py", "sd002_bad.py", "sd003_bad.py",
        "sd005_bad.py", "sd007_bad.py", "sd008_bad.py",
    ])
    def test_deterministic(self, filename):
        r1 = [(f.rule, f.file, f.line) for f in _scan(filename)]
        r2 = [(f.rule, f.file, f.line) for f in _scan(filename)]
        assert r1 == r2, f"Non-deterministic output for {filename}"


# ---------------------------------------------------------------------------
# Severity / confidence spot-checks
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_sd001_high_severity(self):
        findings = [f for f in _scan("sd001_bad.py") if f.rule == "SD001"]
        assert findings
        assert findings[0].severity == "high"
        assert findings[0].confidence == "high"

    def test_sd002_high_severity(self):
        findings = [f for f in _scan("sd002_bad.py") if f.rule == "SD002"]
        assert findings
        assert findings[0].severity == "high"

    def test_sd008_module_level_high(self):
        findings = [f for f in _scan("sd008_bad.py") if f.rule == "SD008"]
        assert findings
        high = [f for f in findings if f.severity == "high"]
        assert high

    def test_findings_sorted(self):
        findings = _scan("sd002_bad.py")
        keys = [f.sort_key() for f in findings]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# SD004 extended: scalar / execute load patterns
# ---------------------------------------------------------------------------


class TestSD004Extended:
    def test_scalar_bad_triggers(self):
        findings = _scan("sd004_scalar_bad.py")
        assert "SD004" in _rules(findings), f"Expected SD004, got: {_rules(findings)}"

    def test_execute_bad_triggers(self):
        findings = _scan("sd004_execute_bad.py")
        assert "SD004" in _rules(findings), f"Expected SD004, got: {_rules(findings)}"

    def test_get_options_kwarg_no_false_positive(self):
        findings = _scan("sd004_get_options_good.py")
        sd004 = [f for f in findings if f.rule == "SD004"]
        assert not sd004, f"Unexpected SD004 with options= kwarg: {sd004}"

    def test_select_options_chain_no_false_positive(self):
        findings = _scan("sd004_select_options_good.py")
        sd004 = [f for f in findings if f.rule == "SD004"]
        assert not sd004, f"Unexpected SD004 with .options() chain: {sd004}"

    def test_partial_options_flags_unloaded_relationship(self):
        findings = _scan("sd004_partial_options_bad.py")
        sd004 = [f for f in findings if f.rule == "SD004"]
        assert len(sd004) == 1, f"Expected one SD004 (customer), got: {sd004}"
        assert "customer" in sd004[0].message


# ---------------------------------------------------------------------------
# SD005 severity is now high
# ---------------------------------------------------------------------------


class TestSD005Severity:
    def test_severity_is_high(self):
        findings = [f for f in _scan("sd005_bad.py") if f.rule == "SD005"]
        assert findings, "No SD005 finding"
        assert findings[0].severity == "high", (
            f"Expected high, got {findings[0].severity}"
        )


# ---------------------------------------------------------------------------
# SD008 nested factory call at module level
# ---------------------------------------------------------------------------


class TestSD008Nested:
    def test_nested_factory_bad_triggers(self):
        findings = _scan("sd008_nested_bad.py")
        sd008 = [f for f in findings if f.rule == "SD008"]
        assert sd008, f"Expected SD008 for nested factory call, got: {_rules(findings)}"
        assert sd008[0].severity == "high"
