"""rules.py – SD001 through SD008 rule implementations."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Iterator

from .loader import (
    Index, FunctionInfo, SessionOp, _name_of, _call_func_name,
    _SAFE_LOAD_OPTIONS, _LAZY_SAFE,
)
from .graph import OwnershipGraph

# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    rule: str
    name: str
    severity: str       # high | medium
    confidence: str     # high | needs_review
    file: str
    line: int
    function: str
    message: str
    fix_hint: str

    def sort_key(self) -> tuple[str, int, str]:
        return (self.file, self.line, self.rule)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fi_commits(fi: FunctionInfo, var: str | None = None) -> list[SessionOp]:
    if var:
        return [op for op in fi.session_ops if op.kind == "commit" and op.session_var == var]
    return [op for op in fi.session_ops if op.kind == "commit"]


def _fi_ops_of_kind(fi: FunctionInfo, kind: str, var: str | None = None) -> list[SessionOp]:
    if var:
        return [op for op in fi.session_ops if op.kind == kind and op.session_var == var]
    return [op for op in fi.session_ops if op.kind == kind]


def _fi_queries(fi: FunctionInfo, var: str | None = None) -> list[SessionOp]:
    return _fi_ops_of_kind(fi, "query", var)


def _first_lineno(ops: list[SessionOp]) -> int:
    if not ops:
        return 0
    return min(op.lineno for op in ops)


# Check if function is a background task receiver
_BACKGROUND_CALL_NAMES = {
    "asyncio.gather", "asyncio.create_task", "asyncio.ensure_future",
    "loop.create_task", "BackgroundTasks.add_task",
    "background_tasks.add_task",
}

_GATHER_NAMES = {"gather", "asyncio.gather"}
_CREATE_TASK_NAMES = {
    "create_task", "asyncio.create_task",
    "ensure_future", "asyncio.ensure_future",
    "loop.create_task",
}
_BACKGROUND_TASK_ADD = {"add_task"}


# ---------------------------------------------------------------------------
# Rule runner
# ---------------------------------------------------------------------------


class RuleEngine:
    def __init__(self, index: Index, graph: OwnershipGraph, fastapi_gte_118: bool) -> None:
        self.index = index
        self.graph = graph
        self.fastapi_gte_118 = fastapi_gte_118
        self.findings: list[Finding] = []

    def run(self) -> list[Finding]:
        for qn, fi in self.index.functions.items():
            self._sd001(fi)
            self._sd002(fi)
            self._sd003(fi)
            self._sd004(fi)
            self._sd005(fi)
            self._sd006(fi)
            self._sd007(fi)
            self._sd008(fi)
        # Module-level SD008
        self._sd008_module_level()
        self.findings.sort(key=lambda f: f.sort_key())
        return self.findings

    def _add(self, rule: str, name: str, severity: str, confidence: str,
             fi: FunctionInfo, line: int, message: str, fix_hint: str) -> None:
        self.findings.append(Finding(
            rule=rule, name=name, severity=severity, confidence=confidence,
            file=fi.file, line=line, function=fi.qualname,
            message=message, fix_hint=fix_hint,
        ))

    # -----------------------------------------------------------------------
    # SD001 – commit-after-yield
    # -----------------------------------------------------------------------
    def _sd001(self, fi: FunctionInfo) -> None:
        if not fi.yields:
            return
        svars = self.graph.session_vars_for(fi.qualname)
        # Include locally-owned sessions (with Factory() as s) not in graph svars
        all_vars: dict[str, str] = dict(svars)
        for var in fi.local_session_vars:
            all_vars.setdefault(var, "local")
        ops = fi.session_ops
        for var in all_vars:
            for yield_line in fi.yields:
                # Check for commit AFTER yield
                post_commits = [
                    op for op in ops
                    if op.kind == "commit" and op.session_var == var and op.lineno > yield_line
                ]
                # Check for `async with session.begin()` wrapping the yield
                begin_wraps = [
                    op for op in ops
                    if op.kind == "begin" and op.session_var == var
                    and op.is_async_with
                ]
                if post_commits or begin_wraps:
                    severity = "high" if self.fastapi_gte_118 else "medium"
                    line = post_commits[0].lineno if post_commits else begin_wraps[0].lineno
                    self._add(
                        "SD001", "commit-after-yield", severity, "high", fi, line,
                        f"Session '{var}' is committed after yield in dependency "
                        f"'{fi.qualname}'. On FastAPI >= 0.118 this runs after the response is sent.",
                        "Commit explicitly in the route before returning, "
                        "or use Depends(dep, scope='function').",
                    )
                    break  # one finding per var, break yield loop

    # -----------------------------------------------------------------------
    # SD002 – helper-commits
    # -----------------------------------------------------------------------
    def _sd002(self, fi: FunctionInfo) -> None:
        svars = self.graph.session_vars_for(fi.qualname)
        for var, source in svars.items():
            if source == "depends" and fi.is_route:
                # Route committing its own Depends session is allowed
                continue
            if source == "local":
                # Function owns this session; committing is fine
                continue
            if source == "annotated" and not self._is_called_with_session(fi, var):
                # Annotated param but no known caller passes a session → treat as owner
                continue
            if source in ("annotated", "propagated"):
                # This function received a session from a caller – it's a helper
                commits = _fi_commits(fi, var)
                if commits:
                    self._add(
                        "SD002", "helper-commits", "high", "high", fi,
                        commits[0].lineno,
                        f"Helper '{fi.qualname}' calls commit() on session '{var}' "
                        f"which it received as a parameter.",
                        "Use flush() in the helper; commit once in the owner.",
                    )

    def _is_called_with_session(self, fi: FunctionInfo, var: str) -> bool:
        """Return True if any function in the index calls fi passing a session for var."""
        # Check graph edges first (propagated cases)
        callers = self.graph.called_by.get(fi.qualname, set())
        for caller_qn in callers:
            edges = self.graph.edges.get(caller_qn, [])
            for edge in edges:
                if edge.callee_qualname == fi.qualname and edge.param_in_callee == var:
                    return True
        # Also scan all functions' call sites directly (handles annotated→annotated passing)
        param_index = fi.params.index(var) if var in fi.params else -1
        for caller_fi in self.index.functions.values():
            if caller_fi.qualname == fi.qualname:
                continue
            caller_svars = self.graph.session_vars_for(caller_fi.qualname)
            for call in caller_fi.calls:
                resolved = self.graph._resolve_callee(call.callee, caller_fi)
                if resolved != fi.qualname:
                    continue
                # Check if the session var is passed positionally at param_index
                if param_index >= 0 and param_index < len(call.pos_args):
                    if call.pos_args[param_index] in caller_svars:
                        return True
                # Or by keyword
                if var in call.kw_args and call.kw_args[var] in caller_svars:
                    return True
        return False

    # -----------------------------------------------------------------------
    # SD003 – read-after-commit
    # -----------------------------------------------------------------------
    def _sd003(self, fi: FunctionInfo) -> None:
        svars = self.graph.session_vars_for(fi.qualname)
        for var, source in svars.items():
            # Check if factory lacks expire_on_commit=False
            factory = self._find_factory_for_var(fi, var)
            if factory is not None and factory.expire_on_commit:
                # expire_on_commit=True (default): attributes expire after commit
                # Look for commit followed by attribute access on an ORM variable
                ops = sorted(fi.session_ops, key=lambda op: op.lineno)
                commit_lines = [op.lineno for op in ops if op.kind == "commit" and op.session_var == var]
                if not commit_lines:
                    continue
                last_commit = max(commit_lines)
                # Walk the AST for attribute reads after last commit
                node = fi.node
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute):
                        if hasattr(child, "lineno") and child.lineno > last_commit:
                            obj_name = _name_of(child.value)
                            if obj_name and obj_name != var:
                                # Attribute read on some object after commit
                                # We can't fully track which objects are ORM instances,
                                # so emit needs_review
                                self._add(
                                    "SD003", "read-after-commit", "medium", "needs_review",
                                    fi, child.lineno,
                                    f"Attribute '{child.attr}' read after commit() on session '{var}'. "
                                    f"Factory uses expire_on_commit=True (default); "
                                    f"this will trigger a lazy load or raise DetachedInstanceError.",
                                    "Set expire_on_commit=False on the session factory, "
                                    "or avoid reading ORM attributes after commit.",
                                )
                                break  # one finding per function

    def _find_factory_for_var(self, fi: FunctionInfo, var: str):
        """Try to find the SessionFactoryInfo for the session variable."""
        # Check assignments in function
        node = fi.node
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    n = _name_of(target)
                    if n == var and isinstance(stmt.value, ast.Call):
                        fname = _call_func_name(stmt.value)
                        if fname:
                            # Direct factory call
                            if fname in self.index.session_factories:
                                return self.index.session_factories[fname]
            if isinstance(stmt, ast.AnnAssign):
                n = _name_of(stmt.target)
                if n == var and stmt.value and isinstance(stmt.value, ast.Call):
                    fname = _call_func_name(stmt.value)
                    if fname and fname in self.index.session_factories:
                        return self.index.session_factories[fname]
        # Try module-level factories
        for fname, finfo in self.index.session_factories.items():
            return finfo  # Return first one as heuristic if only one exists
        return None

    # -----------------------------------------------------------------------
    # SD004 – lazy-relationship (async sessions only)
    # -----------------------------------------------------------------------
    def _sd004(self, fi: FunctionInfo) -> None:
        if not fi.is_async:
            return
        svars = self.graph.session_vars_for(fi.qualname)
        # Map var_name -> (model_qualname | None, has_options)
        loaded_vars: dict[str, tuple[str | None, bool]] = {}

        for stmt in ast.walk(fi.node):
            if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                continue
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
                value = stmt.value
            else:
                targets = [stmt.target]
                value = stmt.value
            if value is None:
                continue

            # Unwrap a single await
            rhs = value
            if isinstance(rhs, ast.Await):
                rhs = rhs.value

            if not isinstance(rhs, ast.Call):
                continue

            # ----------------------------------------------------------------
            # Pattern A: obj = await session.get(Model, id, options=[...])
            # ----------------------------------------------------------------
            fname = _call_func_name(rhs)
            if fname:
                parts = fname.split(".")
                if len(parts) >= 2:
                    sess_obj = ".".join(parts[:-1])
                    method = parts[-1]
                    if sess_obj in svars and method == "get":
                        model_qn = self._infer_model(rhs, fi)
                        has_opts = (
                            self._has_load_options(rhs)
                            or self._has_get_options_kwarg(rhs)
                        )
                        for t in targets:
                            vname = _name_of(t)
                            if vname:
                                loaded_vars[vname] = (model_qn, has_opts)
                        continue

            # ----------------------------------------------------------------
            # Pattern B: obj = await session.scalar(select(Model)...)
            #            obj = (await session.execute(select(Model)...)).scalar_one()
            #            obj = (await session.execute(...)).scalars().first()  etc.
            # ----------------------------------------------------------------
            # Walk the entire RHS call chain looking for a session.scalar /
            # session.execute call, and collect chained post-execute extractors.
            session_call, model_qn, has_opts = self._extract_session_select_call(
                rhs, svars, fi
            )
            if session_call is not None:
                for t in targets:
                    vname = _name_of(t)
                    if vname:
                        loaded_vars[vname] = (model_qn, has_opts)
                continue

            # ----------------------------------------------------------------
            # Pattern C: result = await session.execute(...)
            #            followed by obj = result.scalar_one() etc. (handled
            #            below as a separate assignment pass)
            # ----------------------------------------------------------------
            if fname:
                parts = fname.split(".")
                if len(parts) >= 2:
                    sess_obj = ".".join(parts[:-1])
                    method = parts[-1]
                    if sess_obj in svars and method == "execute":
                        model_qn2 = self._infer_model_from_select_arg(rhs, fi)
                        has_opts2 = self._has_load_options(rhs)
                        for t in targets:
                            vname = _name_of(t)
                            if vname:
                                # Mark as a "result object" keyed specially
                                loaded_vars[f"__result__{vname}"] = (model_qn2, has_opts2)

        # Second pass: resolve result.scalar_one() etc.
        _RESULT_EXTRACTORS = {
            "scalar_one", "scalar_one_or_none", "first", "one",
        }
        for stmt in ast.walk(fi.node):
            if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                continue
            if isinstance(stmt, ast.Assign):
                targets2 = stmt.targets
                value2 = stmt.value
            else:
                targets2 = [stmt.target]
                value2 = stmt.value
            if value2 is None:
                continue
            rhs2 = value2
            fname2 = _call_func_name(rhs2) if isinstance(rhs2, ast.Call) else None
            if fname2 is None:
                continue
            parts2 = fname2.split(".")
            if len(parts2) < 2:
                continue
            base_obj = ".".join(parts2[:-1])
            method2 = parts2[-1]
            # result.scalar_one() / result.scalar_one_or_none()
            if method2 in _RESULT_EXTRACTORS and f"__result__{base_obj}" in loaded_vars:
                for t in targets2:
                    vname = _name_of(t)
                    if vname:
                        loaded_vars[vname] = loaded_vars[f"__result__{base_obj}"]
                continue
            # result.scalars().first() / result.scalars().one()
            if method2 in _RESULT_EXTRACTORS:
                # check if base is result.scalars()
                if isinstance(rhs2, ast.Call) and isinstance(rhs2.func, ast.Attribute):
                    inner = rhs2.func.value
                    inner_fname = _call_func_name(inner) if isinstance(inner, ast.Call) else None
                    if inner_fname:
                        iparts = inner_fname.split(".")
                        if iparts[-1] == "scalars" and f"__result__{'.'.join(iparts[:-1])}" in loaded_vars:
                            for t in targets2:
                                vname = _name_of(t)
                                if vname:
                                    loaded_vars[vname] = loaded_vars[
                                        f"__result__{'.'.join(iparts[:-1])}"
                                    ]

        if not loaded_vars:
            return

        # Which relationships are actually eager-loaded in this function?
        # e.g. selectinload(Order.items) covers 'items' but not 'customer'.
        eager_attrs, eager_wildcard = self._eager_loaded_attrs(fi.node)

        # Now find attribute reads on loaded_vars
        for stmt in ast.walk(fi.node):
            if isinstance(stmt, ast.Attribute):
                obj = _name_of(stmt.value)
                if obj and obj in loaded_vars:
                    model_qn, has_options = loaded_vars[obj]  # type: ignore
                    attr = stmt.attr
                    # Check if this attr is a relationship
                    rel_lazy = None
                    confidence = "needs_review"
                    if model_qn and model_qn in self.index.models:
                        model = self.index.models[model_qn]
                        if attr in model.relationships:
                            confidence = "high"
                            rel_lazy = model.relationships[attr]
                            # Skip safe lazy modes
                            if rel_lazy in _LAZY_SAFE:
                                continue
                        else:
                            continue  # not a known relationship
                    else:
                        continue  # can't resolve model → skip (or use needs_review)
                    covered = has_options and (eager_wildcard or attr in eager_attrs)
                    if not covered:
                        self._add(
                            "SD004", "lazy-relationship", "high", confidence,
                            fi, stmt.lineno,  # type: ignore
                            f"Async session loads '{obj}' (model {model_qn or '?'}) and reads "
                            f"relationship '{attr}' without eager-load option. "
                            f"lazy={rel_lazy!r}.",
                            "Add .options(selectinload(Model.rel)) to the query.",
                        )

    @staticmethod
    def _eager_loaded_attrs(node: ast.AST) -> tuple[set[str], bool]:
        """Collect relationship names passed to eager loaders in `node`.

        Returns (attr_names, wildcard). wildcard is True when a loader argument
        can't be resolved to `Model.attr` (e.g. a string or variable), so we
        stay conservative and treat every relationship as covered.
        """
        attrs: set[str] = set()
        wildcard = False
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            if isinstance(sub.func, ast.Attribute):
                loader = sub.func.attr
            elif isinstance(sub.func, ast.Name):
                loader = sub.func.id
            else:
                continue
            if loader not in _SAFE_LOAD_OPTIONS:
                continue
            for arg in sub.args:
                if isinstance(arg, ast.Attribute):
                    attrs.add(arg.attr)
                else:
                    wildcard = True
        return attrs, wildcard

    def _resolve_name(self, name: str, fi: FunctionInfo) -> str:
        """Resolve a simple name through imports."""
        root = name.split(".")[0]
        resolved = self.index.imports.get((fi.file, root))
        if resolved:
            rest = name[len(root):]
            return resolved + rest
        return f"{fi.module}.{name}"

    def _infer_model(self, call: ast.Call, fi: FunctionInfo) -> str | None:
        """Try to infer the model class from a session.get(Model, id) call."""
        if call.args:
            first_arg = _name_of(call.args[0])
            if first_arg:
                return self._resolve_name(first_arg, fi)
        return None

    def _infer_model_from_select_arg(self, call: ast.Call, fi: FunctionInfo) -> str | None:
        """Infer model from select(Model) buried anywhere in a call chain."""
        for node in ast.walk(call):
            if not isinstance(node, ast.Call):
                continue
            fname = _call_func_name(node)
            if fname and fname.split(".")[-1] == "select" and node.args:
                first_arg = _name_of(node.args[0])
                if first_arg:
                    return self._resolve_name(first_arg, fi)
        return None

    def _extract_session_select_call(
        self,
        rhs: ast.Call,
        svars: dict[str, str],
        fi: FunctionInfo,
    ) -> tuple[ast.Call | None, str | None, bool]:
        """Walk a chained-call RHS for session.scalar/execute(select(Model)...).

        Returns (call_node, model_qn, has_options) or (None, None, False).
        """
        _SCALAR_METHODS = {"scalar", "scalars"}
        _POST_EXECUTE = {"scalar_one", "scalar_one_or_none", "first", "one"}
        # Walk down the func chain collecting method names
        node: ast.expr = rhs
        chain: list[tuple[str, ast.Call]] = []  # (method, call_node) innermost-first
        while isinstance(node, ast.Call):
            fname = _call_func_name(node)
            if fname:
                method = fname.split(".")[-1]
                chain.append((method, node))
            if isinstance(node.func, ast.Attribute):
                node = node.func.value
            else:
                break

        # chain[0] = outermost call, chain[-1] = innermost
        # Find session.scalar / session.execute.
        # For "execute": only match when it is NOT the outermost call (i > 0),
        # meaning an extractor like .scalar_one() is chained on top of it.
        # A bare `result = await session.execute(...)` goes to Pattern C instead.
        for i, (method, call_node) in enumerate(chain):
            fname = _call_func_name(call_node)
            if not fname:
                continue
            parts = fname.split(".")
            if len(parts) < 2:
                continue
            sess_obj = ".".join(parts[:-1])
            if sess_obj not in svars:
                continue
            if method in _SCALAR_METHODS:
                pass  # always accept scalar/scalars
            elif method == "execute" and i > 0:
                pass  # accept execute only when an extractor is chained on top
            else:
                continue
            # Found the session call — infer model from select() inside it
            model_qn = self._infer_model_from_select_arg(call_node, fi)
            # Check options anywhere in the select chain (call args) and on the call itself
            has_opts = self._has_load_options_deep(call_node)
            return call_node, model_qn, has_opts

        return None, None, False

    def _has_get_options_kwarg(self, call: ast.Call) -> bool:
        """Return True if session.get(..., options=[selectinload(...), ...]) covers a safe loader."""
        for kw in call.keywords:
            if kw.arg == "options" and isinstance(kw.value, ast.List):
                for elt in kw.value.elts:
                    name = _call_func_name(elt) if isinstance(elt, ast.Call) else _name_of(elt)
                    if name and name.split(".")[0] in _SAFE_LOAD_OPTIONS:
                        return True
        return False

    def _has_load_options_deep(self, call: ast.Call) -> bool:
        """Check entire AST subtree of `call` for .options(safe_loader) anywhere.

        Uses func.attr directly so it works even when the receiver is a chained
        call (e.g. select(M).where(...).options(selectinload(...))).
        """
        for node in ast.walk(call):
            if not isinstance(node, ast.Call):
                continue
            # Check via _call_func_name first (simple dotted names)
            fname = _call_func_name(node)
            is_options = bool(fname and fname.split(".")[-1] == "options")
            # Also check func.attr directly for chained calls whose receiver is a Call
            if not is_options and isinstance(node.func, ast.Attribute):
                is_options = node.func.attr == "options"
            if is_options:
                for arg in node.args:
                    aname = _call_func_name(arg) if isinstance(arg, ast.Call) else _name_of(arg)
                    if aname and aname.split(".")[0] in _SAFE_LOAD_OPTIONS:
                        return True
        return False

    def _has_load_options(self, call: ast.Call) -> bool:
        """Check if the call or its chain has .options(selectinload/joinedload/...).

        Walks the method-call chain (e.g. session.scalar(...)) AND recursively
        searches call arguments (e.g. select(...).options(selectinload(...))).
        """
        # Walk the outer method chain (session.scalar → its func chain)
        node: ast.expr = call
        while True:
            if isinstance(node, ast.Call):
                fname = _call_func_name(node)
                if fname and fname.split(".")[-1] == "options":
                    for arg in node.args:
                        aname = _call_func_name(arg) if isinstance(arg, ast.Call) else _name_of(arg)
                        if aname and aname.split(".")[0] in _SAFE_LOAD_OPTIONS:
                            return True
                # Descend into func (for chained calls like a.b().c())
                if isinstance(node.func, ast.Attribute):
                    node = node.func.value
                else:
                    break
            else:
                break
        # Also search all arguments recursively (handles select(...).options(...) as arg)
        for arg in call.args:
            if self._has_load_options_deep(arg):
                return True
        return False

    # -----------------------------------------------------------------------
    # SD005 – begin-after-autobegin
    # -----------------------------------------------------------------------
    def _sd005(self, fi: FunctionInfo) -> None:
        svars = self.graph.session_vars_for(fi.qualname)
        for var in svars:
            ops = sorted(
                [op for op in fi.session_ops if op.session_var == var],
                key=lambda op: op.lineno,
            )
            first_non_begin = None
            for op in ops:
                if op.kind not in ("begin", "begin_nested"):
                    first_non_begin = op
                    break

            for op in ops:
                if op.kind == "begin" and not op.is_async_with:
                    # begin_nested is always fine
                    pass
                if op.kind == "begin":
                    # Find if there's any prior op (query/add/flush) OR if session came from param
                    prior_ops = [o for o in ops if o.lineno < op.lineno and
                                 o.kind not in ("begin", "begin_nested")]
                    source = svars[var]
                    is_param = source in ("annotated", "propagated", "depends")
                    if prior_ops or is_param:
                        self._add(
                            "SD005", "begin-after-autobegin", "high", "high",
                            fi, op.lineno,
                            f"session.begin() called on '{var}' which already has "
                            f"{'prior operations' if prior_ops else 'a parameter source'}. "
                            f"SQLAlchemy autobegin is already active.",
                            "Remove the explicit begin() - autobegin handles transaction start. "
                            "Use begin_nested() for savepoints.",
                        )
                        break

    # -----------------------------------------------------------------------
    # SD006 – shared-session-concurrency
    # -----------------------------------------------------------------------
    def _sd006(self, fi: FunctionInfo) -> None:
        svars = self.graph.session_vars_for(fi.qualname)
        session_var_names = set(svars.keys()) | set(fi.session_params)

        for call in fi.calls:
            gather_base = call.callee.split(".")[-1]
            if gather_base == "gather" and "asyncio" in call.callee or call.callee in ("gather", "asyncio.gather"):
                # Check if same session var appears in 2+ args
                session_args = [a for a in call.pos_args if a in session_var_names]
                # Also check if the callees passed the session
                seen: set[str] = set()
                for arg in call.pos_args:
                    if arg in session_var_names:
                        if arg in seen:
                            pass
                        seen.add(arg)
                if len(seen) >= 1:
                    # Check if multiple callees in gather receive it
                    # Simplified: if same var in pos_args more than once
                    if call.pos_args.count(list(seen)[0]) >= 2:
                        var = list(seen)[0]
                        self._add(
                            "SD006", "shared-session-concurrency", "high", "high",
                            fi, call.lineno,
                            f"Session '{var}' passed to multiple coroutines in asyncio.gather().",
                            "Give each concurrent task its own session.",
                        )
                        continue
                # Check: session var appears in two different coroutine call arguments
                # within gather() — i.e. gather(func1(session), func2(session))
                self._check_gather_node(fi, call, session_var_names)

            # TaskGroup
            if gather_base in ("create_task",) and "TaskGroup" in call.callee:
                self._check_taskgroup(fi, session_var_names)

    def _check_gather_node(self, fi: FunctionInfo, call: CallSite,
                            session_vars: set[str]) -> None:
        """Walk the actual AST node for asyncio.gather to find shared sessions."""
        for stmt in ast.walk(fi.node):
            if not isinstance(stmt, ast.Call):
                continue
            fname = _call_func_name(stmt)
            if fname is None:
                continue
            if fname.split(".")[-1] != "gather":
                continue
            if stmt.lineno != call.lineno:
                continue
            # Count how many args pass a session var
            vars_passed: dict[str, int] = {}
            for arg in stmt.args:
                # arg may be a Call like func(session)
                if isinstance(arg, ast.Call):
                    for sub_arg in arg.args:
                        vname = _name_of(sub_arg)
                        if vname and vname in session_vars:
                            vars_passed[vname] = vars_passed.get(vname, 0) + 1
                    for kw in arg.keywords:
                        vname = _name_of(kw.value)
                        if vname and vname in session_vars:
                            vars_passed[vname] = vars_passed.get(vname, 0) + 1
                elif isinstance(arg, ast.Name):
                    if arg.id in session_vars:
                        vars_passed[arg.id] = vars_passed.get(arg.id, 0) + 1
            for vname, count in vars_passed.items():
                if count >= 2:
                    self._add(
                        "SD006", "shared-session-concurrency", "high", "high",
                        fi, stmt.lineno,
                        f"Session '{vname}' passed to {count} coroutines in asyncio.gather().",
                        "Give each concurrent task its own session.",
                    )

    def _check_taskgroup(self, fi: FunctionInfo, session_vars: set[str]) -> None:
        """Find TaskGroup.create_task calls that share a session."""
        session_passed_count: dict[str, int] = {}
        first_lineno: dict[str, int] = {}
        for stmt in ast.walk(fi.node):
            if not isinstance(stmt, ast.Call):
                continue
            fname = _call_func_name(stmt)
            if fname is None:
                continue
            if fname.split(".")[-1] != "create_task":
                continue
            for arg in stmt.args:
                if isinstance(arg, ast.Call):
                    for sub in arg.args:
                        v = _name_of(sub)
                        if v and v in session_vars:
                            session_passed_count[v] = session_passed_count.get(v, 0) + 1
                            if v not in first_lineno:
                                first_lineno[v] = stmt.lineno
        for v, count in session_passed_count.items():
            if count >= 2:
                self._add(
                    "SD006", "shared-session-concurrency", "high", "high",
                    fi, first_lineno[v],
                    f"Session '{v}' passed to {count} tasks in the same TaskGroup.",
                    "Give each concurrent task its own session.",
                )

    # -----------------------------------------------------------------------
    # SD007 – unsafe-background-work
    # -----------------------------------------------------------------------
    def _sd007(self, fi: FunctionInfo) -> None:
        svars = self.graph.session_vars_for(fi.qualname)
        session_var_names = set(svars.keys()) | set(fi.session_params)

        for stmt in ast.walk(fi.node):
            if not isinstance(stmt, ast.Call):
                continue
            fname = _call_func_name(stmt)
            if fname is None:
                continue
            base = fname.split(".")[-1]

            is_create_task = base in ("create_task", "ensure_future")
            is_bg_task = base == "add_task" and any(
                "background" in p.lower() for p in [fname.split(".")[0]]
            )

            if not (is_create_task or is_bg_task):
                continue

            lineno = stmt.lineno

            # (a) request session passed as argument
            for arg in stmt.args:
                if isinstance(arg, ast.Call):
                    for sub in list(arg.args) + [kw.value for kw in arg.keywords]:
                        v = _name_of(sub)
                        if v and v in session_var_names:
                            source = svars.get(v, "")
                            if source in ("depends", "annotated"):
                                self._add(
                                    "SD007", "unsafe-background-work", "high", "high",
                                    fi, lineno,
                                    f"Request session '{v}' passed to background task '{fname}'. "
                                    f"The session will be closed when the request ends.",
                                    "Open a new session inside the background task.",
                                )
                elif isinstance(arg, ast.Name):
                    if arg.id in session_var_names:
                        source = svars.get(arg.id, "")
                        if source in ("depends", "annotated"):
                            self._add(
                                "SD007", "unsafe-background-work", "high", "high",
                                fi, lineno,
                                f"Request session '{arg.id}' passed to background task '{fname}'.",
                                "Open a new session inside the background task.",
                            )

            # (c) result not stored (for create_task / ensure_future)
            if is_create_task:
                is_stored = self._call_result_stored(fi, stmt)
                if not is_stored:
                    self._add(
                        "SD007", "unsafe-background-work", "medium", "high",
                        fi, lineno,
                        f"Result of '{fname}' (create_task/ensure_future) is not stored. "
                        f"The task may be garbage-collected before completing.",
                        "Store the task: `task = asyncio.create_task(...)`",
                    )

            # (b) target opens session, writes but never commits
            target_func = self._extract_task_target(stmt)
            if target_func:
                target_qn = self.graph._resolve_callee(target_func, fi)
                if target_qn in self.index.functions:
                    target_fi = self.index.functions[target_qn]
                    self._check_sd007b(fi, target_fi, lineno, fname)

    def _extract_task_target(self, call: ast.Call) -> str | None:
        """Get the function name passed as first arg to create_task/add_task."""
        if not call.args:
            return None
        first = call.args[0]
        if isinstance(first, ast.Name):
            return first.id
        if isinstance(first, ast.Attribute):
            return _name_of(first)
        if isinstance(first, ast.Call):
            return _call_func_name(first)
        return None

    def _call_result_stored(self, fi: FunctionInfo, call_node: ast.Call) -> bool:
        """Check if the call result is assigned anywhere in the function."""
        for stmt in ast.walk(fi.node):
            if isinstance(stmt, ast.Assign):
                if isinstance(stmt.value, ast.Await):
                    if stmt.value.value is call_node:
                        return True
                if stmt.value is call_node:
                    return True
            elif isinstance(stmt, ast.AnnAssign):
                if stmt.value is call_node:
                    return True
        return False

    def _check_sd007b(self, caller_fi: FunctionInfo, target_fi: FunctionInfo,
                       lineno: int, fname: str) -> None:
        """SD007(b): target opens own session, writes, but never commits."""
        target_svars = self.graph.session_vars_for(target_fi.qualname)
        for var, source in target_svars.items():
            if source != "local":
                continue
            has_write = any(
                op.kind in ("add", "add_all", "delete", "flush", "query")
                and op.session_var == var
                for op in target_fi.session_ops
            )
            if not has_write:
                continue
            # Check DML in execute calls
            has_dml_execute = self._has_dml_execute(target_fi, var)
            has_commit = any(
                op.kind == "commit" and op.session_var == var
                for op in target_fi.session_ops
            )
            has_begin_ctx = any(
                op.kind == "begin" and op.is_async_with and op.session_var == var
                for op in target_fi.session_ops
            )
            if (has_write or has_dml_execute) and not has_commit and not has_begin_ctx:
                self._add(
                    "SD007", "unsafe-background-work", "high", "high",
                    caller_fi, lineno,
                    f"Background task '{target_fi.qualname}' opens its own session, "
                    f"writes data, but never commits.",
                    "Add an explicit commit() or use `async with session.begin():` "
                    "in the background task.",
                )
                return

    def _has_dml_execute(self, fi: FunctionInfo, var: str) -> bool:
        """Check for session.execute(insert/update/delete(...))."""
        _DML = {"insert", "update", "delete"}
        for stmt in ast.walk(fi.node):
            if isinstance(stmt, ast.Call):
                fname = _call_func_name(stmt)
                if fname and fname.split(".")[-1] == "execute":
                    parts = fname.split(".")
                    if len(parts) >= 2 and ".".join(parts[:-1]) == var:
                        for arg in stmt.args:
                            argn = _call_func_name(arg) if isinstance(arg, ast.Call) else None
                            if argn and argn.split(".")[-1] in _DML:
                                return True
        return False

    # -----------------------------------------------------------------------
    # SD008 – session-outlives-request
    # -----------------------------------------------------------------------
    def _sd008(self, fi: FunctionInfo) -> None:
        """Detect self.x = session in __init__, or local factory with no close."""
        if fi.node.name == "__init__":
            for stmt in ast.walk(fi.node):
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        tname = _name_of(target)
                        if tname and tname.startswith("self."):
                            if isinstance(stmt.value, ast.Call):
                                fname = _call_func_name(stmt.value)
                                if fname and self._is_factory_call(fname, fi):
                                    self._add(
                                        "SD008", "session-outlives-request", "high", "high",
                                        fi, stmt.lineno,
                                        f"Session factory called at instance level: "
                                        f"'{tname}' = {fname}(). "
                                        f"Session stored on instance will outlive the request.",
                                        "Open a session per-request in a dependency or route, "
                                        "not in __init__.",
                                    )
                            # Also: self.x = session_param
                            elif isinstance(stmt.value, ast.Name):
                                vname = stmt.value.id
                                svars = self.graph.session_vars_for(fi.qualname)
                                if vname in svars:
                                    # Storing an injected session is fine for a
                                    # per-request wrapper; only the module-level
                                    # instantiation check below is high-confidence.
                                    self._add(
                                        "SD008", "session-outlives-request", "medium", "needs_review",
                                        fi, stmt.lineno,
                                        f"Session '{vname}' stored on instance as '{tname}'. "
                                        f"If this object is created at module level or cached, "
                                        f"the session outlives any single request.",
                                        "Do not store sessions on instance attributes.",
                                    )

        # Local factory call with no with/close/finally
        svars = self.graph.session_vars_for(fi.qualname)
        for var, source in svars.items():
            if source == "local":
                has_close = any(
                    op.kind == "close" and op.session_var == var
                    for op in fi.session_ops
                )
                has_with = self._var_used_in_with(fi, var)
                if not has_close and not has_with:
                    # Check it was created by a factory call (not a parameter)
                    if self._var_created_by_factory(fi, var):
                        self._add(
                            "SD008", "session-outlives-request", "medium", "high",
                            fi, self._factory_call_line(fi, var),
                            f"Session '{var}' created by factory call but never closed "
                            f"(no with/async with/close()/finally).",
                            "Use `async with Factory() as session:` or call session.close() "
                            "in a finally block.",
                        )

    def _sd008_module_level(self) -> None:
        """Detect module-level session USAGE (calling a known factory to open a session).

        Factory *definitions* (sessionmaker(...), async_sessionmaker(...)) at module
        level are fine — they just define a factory.  It is calling a *registered*
        factory (e.g. SessionLocal()) that produces a session that outlives a request.
        """
        for module, assigns in self.index.module_assignments.items():
            file = self._module_to_file(module)
            if file is None:
                continue
            for name, lineno, value_snippet in assigns:
                # Skip if this assignment IS a factory definition
                # (i.e. its RHS is sessionmaker/async_sessionmaker)
                try:
                    expr_tree = ast.parse(value_snippet, mode="eval")
                except SyntaxError:
                    continue
                if not isinstance(expr_tree.body, ast.Call):
                    continue
                fname = _call_func_name(expr_tree.body)
                if fname is None:
                    continue
                # If the callee itself is a factory constructor → skip (it's a definition)
                if self._is_factory_call_by_name(fname):
                    continue
                # Check if the callee is a known registered factory (e.g. SessionLocal())
                # Look up by local name then by module-qualified name
                is_session_open = (
                    fname in self.index.session_factories
                    or f"{module}.{fname}" in self.index.session_factories
                )
                if not is_session_open:
                    # Also check arguments: SomeClass(SessionLocal()) — factory nested in a call
                    is_session_open = self._args_contain_factory_call(
                        expr_tree.body, module
                    )
                if is_session_open:
                    self.findings.append(Finding(
                        rule="SD008",
                        name="session-outlives-request",
                        severity="high",
                        confidence="high",
                        file=file,
                        line=lineno,
                        function=f"{module}.<module>",
                        message=(
                            f"Session factory '{fname}' called at module level "
                            f"('{name}'). Module-level sessions outlive requests."
                        ),
                        fix_hint=(
                            "Move session creation into a per-request dependency or route."
                        ),
                    ))

    def _module_to_file(self, module: str) -> str | None:
        for file, mod in self.index.file_module.items():
            if mod == module:
                return file
        return None

    def _is_factory_call(self, fname: str, fi: FunctionInfo) -> bool:
        from .loader import _SESSION_FACTORY_CALLS
        base = fname.split(".")[-1]
        if base in _SESSION_FACTORY_CALLS:
            return True
        root = fname.split(".")[0]
        resolved = self.index.imports.get((fi.file, root), "")
        return resolved in _SESSION_FACTORY_CALLS

    def _is_factory_call_by_name(self, fname: str) -> bool:
        from .loader import _SESSION_FACTORY_CALLS
        base = fname.split(".")[-1]
        return base in _SESSION_FACTORY_CALLS

    def _args_contain_factory_call(self, call: ast.Call, module: str) -> bool:
        """Return True if any argument (recursively) is a known factory call."""
        for arg in call.args:
            if isinstance(arg, ast.Call):
                inner_fname = _call_func_name(arg)
                if inner_fname:
                    if self._is_factory_call_by_name(inner_fname):
                        return True
                    if (inner_fname in self.index.session_factories
                            or f"{module}.{inner_fname}" in self.index.session_factories):
                        return True
        for kw in call.keywords:
            if isinstance(kw.value, ast.Call):
                inner_fname = _call_func_name(kw.value)
                if inner_fname:
                    if self._is_factory_call_by_name(inner_fname):
                        return True
                    if (inner_fname in self.index.session_factories
                            or f"{module}.{inner_fname}" in self.index.session_factories):
                        return True
        return False

    def _var_used_in_with(self, fi: FunctionInfo, var: str) -> bool:
        for stmt in ast.walk(fi.node):
            if isinstance(stmt, (ast.With, ast.AsyncWith)):
                for item in stmt.items:
                    ctx = item.context_expr
                    fname = _call_func_name(ctx) if isinstance(ctx, ast.Call) else _name_of(ctx)
                    if fname == var:
                        return True
                    # async with Factory() as var
                    if item.optional_vars:
                        vname = _name_of(item.optional_vars)
                        if vname == var:
                            return True
        return False

    def _var_created_by_factory(self, fi: FunctionInfo, var: str) -> bool:
        for stmt in ast.walk(fi.node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if _name_of(target) == var and isinstance(stmt.value, ast.Call):
                        fname = _call_func_name(stmt.value)
                        if fname and self._is_factory_call(fname, fi):
                            return True
        return False

    def _factory_call_line(self, fi: FunctionInfo, var: str) -> int:
        for stmt in ast.walk(fi.node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if _name_of(target) == var and isinstance(stmt.value, ast.Call):
                        return stmt.lineno
        return fi.node.lineno
