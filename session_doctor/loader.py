"""loader.py – file discovery, parsing, and cross-file index building."""

from __future__ import annotations

import ast
import re
try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # pyproject parsing skipped on 3.10
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SKIP_DIRS = {"tests", ".venv", "venv", "site-packages", "__pycache__", "migrations", "examples"}

_SESSION_TYPES = {"Session", "AsyncSession"}

_SESSION_FACTORY_CALLS = {"sessionmaker", "async_sessionmaker"}

_LAZY_SAFE = {"selectin", "joined", "immediate"}

_LOAD_OPTIONS = {
    "selectinload", "joinedload", "subqueryload", "immediateload",
    "contains_eager", "raiseload",  # raiseload isn't safe but we track it
}

_SAFE_LOAD_OPTIONS = {"selectinload", "joinedload", "subqueryload", "immediateload"}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class FunctionInfo:
    """Metadata collected for a single function/method."""

    __slots__ = (
        "qualname", "node", "file", "module",
        "params", "session_params", "depends_params",
        "decorators", "is_async",
        "session_ops",       # list of SessionOp
        "calls",             # list of (lineno, callee_qualname_or_local, args_kw)
        "yields",            # list of lineno where yield occurs
        "is_route",          # bool
        "route_method",
        "route_path",
        "is_session_dep",    # yields a session from a factory
        "local_session_vars",  # vars bound via `with Factory() as s` or direct factory call
    )

    def __init__(self, qualname: str, node: ast.FunctionDef | ast.AsyncFunctionDef,
                 file: str, module: str) -> None:
        self.qualname = qualname
        self.node = node
        self.file = file
        self.module = module
        self.params: list[str] = []
        self.session_params: list[str] = []       # params annotated Session/AsyncSession
        self.depends_params: dict[str, str] = {}  # param_name → dep_qualname
        self.decorators: list[str] = []
        self.is_async = isinstance(node, ast.AsyncFunctionDef)
        self.session_ops: list[SessionOp] = []
        self.calls: list[CallSite] = []
        self.yields: list[int] = []
        self.is_route = False
        self.route_method: str | None = None
        self.route_path: str | None = None
        self.is_session_dep = False
        self.local_session_vars: list[str] = []   # locally-owned sessions


class SessionOp:
    """A single session operation (commit, flush, query, etc.) in a function."""

    __slots__ = ("kind", "lineno", "session_var", "is_await", "is_async_with")

    def __init__(self, kind: str, lineno: int, session_var: str,
                 is_await: bool = False, is_async_with: bool = False) -> None:
        self.kind = kind          # commit|flush|rollback|add|add_all|delete|query|begin|begin_nested|close
        self.lineno = lineno
        self.session_var = session_var
        self.is_await = is_await
        self.is_async_with = is_async_with

    def __repr__(self) -> str:
        return f"SessionOp({self.kind!r}, line={self.lineno}, var={self.session_var!r})"


class CallSite:
    """A call within a function body."""

    __slots__ = ("lineno", "callee", "pos_args", "kw_args", "result_var")

    def __init__(self, lineno: int, callee: str,
                 pos_args: list[str], kw_args: dict[str, str],
                 result_var: str | None = None) -> None:
        self.lineno = lineno
        self.callee = callee       # resolved or local name
        self.pos_args = pos_args   # variable names for positional args
        self.kw_args = kw_args     # keyword → variable name
        self.result_var = result_var  # variable the return value is assigned to


class ModelInfo:
    """Information about an ORM model class."""

    __slots__ = ("qualname", "file", "relationships")

    def __init__(self, qualname: str, file: str) -> None:
        self.qualname = qualname
        self.file = file
        self.relationships: dict[str, str | None] = {}  # attr_name → lazy value or None


class SessionFactoryInfo:
    __slots__ = ("qualname", "module_var", "expire_on_commit", "is_async")

    def __init__(self, qualname: str, module_var: str,
                 expire_on_commit: bool, is_async: bool) -> None:
        self.qualname = qualname
        self.module_var = module_var
        self.expire_on_commit = expire_on_commit
        self.is_async = is_async


class Index:
    """Cross-file index built during pass 1."""

    def __init__(self) -> None:
        # qualname → FunctionInfo
        self.functions: dict[str, FunctionInfo] = {}
        # (file, local_name) → qualname  (import resolution)
        self.imports: dict[tuple[str, str], str] = {}
        # qualname → ModelInfo
        self.models: dict[str, ModelInfo] = {}
        # var_name → SessionFactoryInfo  (module-level)
        self.session_factories: dict[str, SessionFactoryInfo] = {}
        # module name → list of module-level assignments  (name → lineno, value_snippet)
        self.module_assignments: dict[str, list[tuple[str, int, str]]] = {}
        # file → module name
        self.file_module: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _name_of(node: ast.expr | None) -> str | None:
    """Return a dotted name string for Name/Attribute chains, else None."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name_of(node.value)
        if base:
            return f"{base}.{node.attr}"
    return None


def _call_func_name(node: ast.Call) -> str | None:
    return _name_of(node.func)


def _bool_constant(node: ast.expr) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def _str_constant(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_arg_var(node: ast.expr) -> str | None:
    """Return the variable name if the expression is a simple Name."""
    if isinstance(node, ast.Name):
        return node.id
    return None


# ---------------------------------------------------------------------------
# FastAPI version detection
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(
    r"fastapi\s*[=><~!^]{1,3}\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE
)


def detect_fastapi_version(root: Path) -> tuple[str | None, bool]:
    """Return (version_str_or_None, assumed_bool).

    If lower bound >= 0.118 or undetermined → assumed True.
    """
    candidates = list(root.glob("requirements*.txt")) + list(root.glob("pyproject.toml"))
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if candidate.suffix == ".toml":
            if tomllib is None:
                continue
            try:
                data = tomllib.loads(text)
            except Exception:
                continue
            # Check project.dependencies and tool.poetry.dependencies
            deps: list[str] = []
            deps += data.get("project", {}).get("dependencies", [])
            poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
            for k, v in poetry_deps.items():
                if "fastapi" in k.lower():
                    deps.append(f"fastapi{v}" if isinstance(v, str) else "fastapi")
            for dep in deps:
                m = _VERSION_RE.search(dep)
                if m:
                    return m.group(1), False
        else:
            m = _VERSION_RE.search(text)
            if m:
                return m.group(1), False
    return None, True


def _version_gte_118(version_str: str | None) -> bool:
    if version_str is None:
        return True
    parts = version_str.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch) >= (0, 118, 0)
    except (ValueError, IndexError):
        return True


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def collect_files(root: Path) -> list[Path]:
    """Return sorted list of .py files under root, skipping skip dirs."""
    result: list[Path] = []
    for p in sorted(root.rglob("*.py")):
        # Check none of the parts is a skip dir
        rel = p.relative_to(root)
        parts = set(rel.parts[:-1])  # directory parts only
        if parts & _SKIP_DIRS:
            continue
        if rel.parts[0] in _SKIP_DIRS:
            continue
        result.append(p)
    return result


def path_to_module(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # strip .py
    return ".".join(parts)


# ---------------------------------------------------------------------------
# AST walkers
# ---------------------------------------------------------------------------


class _FunctionCollector(ast.NodeVisitor):
    """Walk a module, building FunctionInfo for every function/method."""

    def __init__(self, module: str, file: str, imports: dict[str, str],
                 index: Index) -> None:
        self._module = module
        self._file = file
        self._imports = imports   # local_name → qualified
        self._index = index
        self._scope: list[str] = []

    # ------------------------------------------------------------------
    def _qualname(self, name: str) -> str:
        if self._scope:
            return f"{self._module}.{'.'.join(self._scope)}.{name}"
        return f"{self._module}.{name}"

    def _resolve(self, name: str) -> str:
        """Resolve a dotted name via imports or return as-is."""
        root = name.split(".")[0]
        if root in self._imports:
            rest = name[len(root):]
            return self._imports[root] + rest
        return name

    # ------------------------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Compute qualname before pushing scope
        class_qualname = self._qualname(node.name)
        self._scope.append(node.name)
        # Check if this is an ORM model
        self._check_model(node, class_qualname)
        self.generic_visit(node)
        self._scope.pop()

    def _check_model(self, node: ast.ClassDef, class_qualname: str) -> None:
        """Detect SQLAlchemy ORM model classes and their relationships."""
        # Heuristic: has a base or decorator that smells like a declarative model
        model_info = ModelInfo(class_qualname, self._file)
        found_rel = False
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    attr_name = _name_of(target)
                    if attr_name and isinstance(stmt.value, ast.Call):
                        fname = _call_func_name(stmt.value)
                        if fname and fname.split(".")[-1] == "relationship":
                            lazy_val = None
                            for kw in stmt.value.keywords:
                                if kw.arg == "lazy":
                                    lazy_val = _str_constant(kw.value)
                            model_info.relationships[attr_name] = lazy_val
                            found_rel = True
            elif isinstance(stmt, ast.AnnAssign):
                attr_name = _name_of(stmt.target)
                if attr_name and stmt.value and isinstance(stmt.value, ast.Call):
                    fname = _call_func_name(stmt.value)
                    if fname and fname.split(".")[-1] == "relationship":
                        lazy_val = None
                        for kw in stmt.value.keywords:
                            if kw.arg == "lazy":
                                lazy_val = _str_constant(kw.value)
                        model_info.relationships[attr_name] = lazy_val
                        found_rel = True
        if found_rel:
            self._index.models[class_qualname] = model_info

    # ------------------------------------------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualname = self._qualname(node.name)
        info = FunctionInfo(qualname, node, self._file, self._module)
        self._index.functions[qualname] = info

        # Parameters
        all_args = (
            node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        )
        for arg in all_args:
            info.params.append(arg.arg)
            ann = arg.annotation
            if ann is not None:
                ann_name = _name_of(ann)
                if ann_name and ann_name.split(".")[-1] in _SESSION_TYPES:
                    info.session_params.append(arg.arg)

        # Map defaults (positional: align from right)
        defaults = node.args.defaults
        positional_args = node.args.posonlyargs + node.args.args
        offset = len(positional_args) - len(defaults)
        for i, default in enumerate(defaults):
            param = positional_args[offset + i]
            self._check_depends(info, param.arg, default)

        # kwonly defaults
        for param, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None:
                self._check_depends(info, param.arg, default)

        # Decorators
        for dec in node.decorator_list:
            dec_name = _name_of(dec)
            if dec_name:
                info.decorators.append(dec_name)
            elif isinstance(dec, ast.Call):
                dec_name = _call_func_name(dec)
                if dec_name:
                    info.decorators.append(dec_name)
            self._check_route_decorator(info, dec)

        # Walk body
        self._scope.append(node.name)
        _BodyWalker(info, self._imports, self._index, self._module).walk(node)
        self._scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _check_depends(self, info: FunctionInfo, param: str, default: ast.expr) -> None:
        if not isinstance(default, ast.Call):
            return
        fname = _call_func_name(default)
        if fname is None:
            return
        base = fname.split(".")[-1]
        if base == "Depends" and default.args:
            dep_arg = _name_of(default.args[0])
            if dep_arg:
                resolved = self._resolve(dep_arg)
                info.depends_params[param] = resolved
                # Also treat as session param (we'll verify later)
                info.session_params.append(param)

    def _check_route_decorator(self, info: FunctionInfo, dec: ast.expr) -> None:
        http_methods = {"get", "post", "put", "patch", "delete", "api_route", "websocket"}
        if isinstance(dec, ast.Call):
            fname = _call_func_name(dec)
            if fname:
                parts = fname.split(".")
                if len(parts) >= 2 and parts[-1] in http_methods:
                    info.is_route = True
                    info.route_method = parts[-1]
                    if dec.args:
                        s = _str_constant(dec.args[0])
                        if s:
                            info.route_path = s
        elif isinstance(dec, ast.Attribute):
            if dec.attr in http_methods:
                info.is_route = True
                info.route_method = dec.attr


class _BodyWalker(ast.NodeVisitor):
    """Walk a function body, recording session ops, calls, yields."""

    _QUERY_METHODS = {
        "execute", "scalar", "scalars", "get", "refresh", "stream",
        "stream_scalars", "run_sync", "all",
    }
    _WRITE_METHODS = {"add", "add_all", "delete", "merge"}
    _CTRL_METHODS = {
        "flush", "commit", "rollback", "close",
        "begin", "begin_nested",
    }

    def __init__(self, info: FunctionInfo, imports: dict[str, str],
                 index: Index, module: str) -> None:
        self._info = info
        self._imports = imports
        self._index = index
        self._module = module
        # local var → "session" marker
        self._session_vars: set[str] = set(info.session_params)
        # track assignments: name → value expr
        self._assignments: dict[str, ast.expr] = {}

    def walk(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for stmt in ast.walk(node):
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                self._record_assignment(stmt)
        # Second pass: proper ordered walk
        for child in ast.iter_child_nodes(node):
            self.visit(child)

    def _record_assignment(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                name = _name_of(target)
                if name and isinstance(target, ast.Name):
                    self._assignments[name] = stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            name = _name_of(stmt.target)
            if name and stmt.value:
                self._assignments[name] = stmt.value

    def _detect_session_var(self, name: str) -> bool:
        if name in self._session_vars:
            return True
        val = self._assignments.get(name)
        if val is None:
            return False
        return self._is_session_expr(val)

    def _is_session_expr(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Call):
            fname = _call_func_name(node)
            if fname:
                base = fname.split(".")[-1]
                if base in _SESSION_FACTORY_CALLS or base in _SESSION_TYPES:
                    return True
                # Check if it's a known factory
                if fname in self._index.session_factories:
                    return True
                root = fname.split(".")[0]
                resolved = self._imports.get(root, root)
                if resolved in self._index.session_factories:
                    return True
        if isinstance(node, ast.Name):
            n = node.id
            if n in self._session_vars:
                return True
        return False

    # ------------------------------------------------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        # Check if RHS is a session factory call
        rhs = node.value
        if self._is_session_expr(rhs):
            for target in node.targets:
                name = _name_of(target)
                if name and isinstance(target, ast.Name):
                    self._session_vars.add(name)
                    # Direct factory call → locally owned session
                    if isinstance(rhs, ast.Call):
                        if name not in self._info.local_session_vars:
                            self._info.local_session_vars.append(name)
        # Also handle: x = some_func(session, ...)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value and self._is_session_expr(node.value):
            name = _name_of(node.target)
            if name:
                self._session_vars.add(name)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with_common(node)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self._visit_with_common(node)
        self.generic_visit(node)

    def _visit_with_common(self, node: ast.With | ast.AsyncWith) -> None:
        is_async = isinstance(node, ast.AsyncWith)
        for item in node.items:
            ctx = item.context_expr
            var = item.optional_vars
            if isinstance(ctx, ast.Call):
                fname = _call_func_name(ctx)
                if fname:
                    # session.begin() or session.begin_nested()
                    parts = fname.split(".")
                    if len(parts) >= 2 and parts[-1] in ("begin", "begin_nested"):
                        session_var = ".".join(parts[:-1])
                        if self._detect_session_var(session_var):
                            kind = parts[-1]
                            self._info.session_ops.append(
                                SessionOp(kind, ctx.lineno, session_var,
                                          is_await=False, is_async_with=is_async)
                            )
                    # Factory() as session
                    base = fname.split(".")[-1]
                    is_factory = (
                        base in _SESSION_FACTORY_CALLS
                        or fname in self._index.session_factories
                        or self._imports.get(fname.split(".")[0], "") in _SESSION_FACTORY_CALLS
                    )
                    if is_factory and var:
                        vname = _name_of(var)
                        if vname:
                            self._session_vars.add(vname)
                            if vname not in self._info.local_session_vars:
                                self._info.local_session_vars.append(vname)

    def visit_Expr(self, node: ast.Expr) -> None:
        self._check_call_expr(node.value, node.lineno)
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        if isinstance(node.value, ast.Call):
            self._check_call_expr(node.value, node.lineno, is_await=True)
        self.generic_visit(node)

    def _check_call_expr(self, node: ast.expr, lineno: int, is_await: bool = False) -> None:
        if not isinstance(node, ast.Call):
            return
        fname = _call_func_name(node)
        if fname is None:
            return
        parts = fname.split(".")
        if len(parts) >= 2:
            obj = ".".join(parts[:-1])
            method = parts[-1]
            if self._detect_session_var(obj):
                if method in self._CTRL_METHODS:
                    self._info.session_ops.append(
                        SessionOp(method, lineno, obj, is_await=is_await)
                    )
                elif method in self._QUERY_METHODS:
                    self._info.session_ops.append(
                        SessionOp("query", lineno, obj, is_await=is_await)
                    )
                elif method in self._WRITE_METHODS:
                    self._info.session_ops.append(
                        SessionOp("add", lineno, obj, is_await=is_await)
                    )
        # Record call site for propagation
        self._record_callsite(node, lineno)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value:
            self._check_call_expr(node.value, node.lineno)
        self.generic_visit(node)

    def _record_callsite(self, node: ast.Call, lineno: int) -> None:
        fname = _call_func_name(node)
        if fname is None:
            return
        pos_args = []
        for arg in node.args:
            pos_args.append(_name_of(arg) or "?")
        kw_args = {}
        for kw in node.keywords:
            if kw.arg:
                kw_args[kw.arg] = _name_of(kw.value) or "?"
        self._info.calls.append(CallSite(lineno, fname, pos_args, kw_args))

    def visit_Yield(self, node: ast.Yield) -> None:
        self._info.yields.append(node.lineno)
        # If yield (value) is a session var, mark function as session dep
        if node.value:
            val_name = _name_of(node.value)
            if val_name and self._detect_session_var(val_name):
                self._info.is_session_dep = True
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self._info.yields.append(node.lineno)
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Import collector
# ---------------------------------------------------------------------------


class _ImportCollector(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self._module = module
        self.imports: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.imports[local] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        if node.level:
            # Relative import: resolve against self._module
            parts = self._module.split(".")
            parts = parts[: len(parts) - node.level]
            if base:
                base = ".".join(parts) + "." + base
            else:
                base = ".".join(parts)
        for alias in node.names:
            local = alias.asname or alias.name
            self.imports[local] = f"{base}.{alias.name}" if base else alias.name


# ---------------------------------------------------------------------------
# Module-level session factory detector
# ---------------------------------------------------------------------------


def _collect_module_factories(tree: ast.Module, imports: dict[str, str],
                               module: str, file: str, index: Index) -> None:
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            if not isinstance(stmt.value, ast.Call):
                continue
            fname = _call_func_name(stmt.value)
            if fname is None:
                continue
            base = fname.split(".")[-1]
            is_factory = base in _SESSION_FACTORY_CALLS
            if not is_factory:
                # Check imports
                root = fname.split(".")[0]
                resolved = imports.get(root, "")
                is_factory = resolved.split(".")[-1] in _SESSION_FACTORY_CALLS

            if is_factory:
                is_async = "async" in (fname.split(".")[-1]).lower()
                expire = True  # default is True
                for kw in stmt.value.keywords:
                    if kw.arg == "expire_on_commit":
                        v = _bool_constant(kw.value)
                        if v is not None:
                            expire = v
                for target in stmt.targets:
                    name = _name_of(target)
                    if name:
                        qn = f"{module}.{name}"
                        info = SessionFactoryInfo(qn, name, expire, is_async)
                        index.session_factories[name] = info
                        index.session_factories[qn] = info


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------


def build_index(root: Path) -> tuple[Index, list[tuple[str, str, int]]]:
    """Parse all files and return (Index, parse_errors).

    parse_errors: list of (file, message, lineno)
    """
    index = Index()
    errors: list[tuple[str, str, int]] = []
    files = collect_files(root)

    for path in files:
        rel = path.relative_to(root)
        file_key = rel.as_posix()
        module = path_to_module(path, root)
        index.file_module[file_key] = module

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError) as e:
            errors.append((file_key, str(e), 0))
            continue

        # Collect imports
        ic = _ImportCollector(module)
        ic.visit(tree)
        imports = ic.imports

        # Store file→module
        for local, qualified in imports.items():
            index.imports[(file_key, local)] = qualified

        # Collect factories at module level
        _collect_module_factories(tree, imports, module, file_key, index)

        # Collect functions
        collector = _FunctionCollector(module, file_key, imports, index)
        collector.visit(tree)

        # Collect module-level assignments
        assigns = []
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    name = _name_of(target)
                    if name:
                        assigns.append((name, stmt.lineno, ast.unparse(stmt.value)))
            elif isinstance(stmt, ast.AnnAssign) and stmt.value:
                name = _name_of(stmt.target)
                if name:
                    assigns.append((name, stmt.lineno, ast.unparse(stmt.value)))
        index.module_assignments[module] = assigns

    return index, errors
