"""graph.py – session ownership graph and propagation."""

from __future__ import annotations

from .loader import Index, FunctionInfo, SessionOp, CallSite

_MAX_DEPTH = 6


class SessionEdge:
    """Caller → callee propagation edge."""

    __slots__ = ("caller_qualname", "callee_qualname", "session_var_in_caller",
                 "param_in_callee", "lineno")

    def __init__(self, caller: str, callee: str,
                 session_var: str, param: str, lineno: int) -> None:
        self.caller_qualname = caller
        self.callee_qualname = callee
        self.session_var_in_caller = session_var
        self.param_in_callee = param
        self.lineno = lineno


class OwnershipGraph:
    """Maps function qualnames to the session variables they own/receive."""

    def __init__(self, index: Index) -> None:
        self.index = index
        # qualname → set of (session_var, source)
        # source: "depends" | "annotated" | "propagated" | "local"
        self.session_vars: dict[str, dict[str, str]] = {}
        # edges: caller_qualname → list[SessionEdge]
        self.edges: dict[str, list[SessionEdge]] = {}
        # callee → set of callers
        self.called_by: dict[str, set[str]] = {}
        self._build()

    def _build(self) -> None:
        # Seed with annotated / depends params and local session vars
        for qn, fi in self.index.functions.items():
            svars: dict[str, str] = {}
            for param in fi.session_params:
                if param in fi.depends_params:
                    svars[param] = "depends"
                else:
                    svars[param] = "annotated"
            # Locally-owned sessions (from with Factory() as s or s = Factory())
            for var in fi.local_session_vars:
                svars[var] = "local"
            self.session_vars[qn] = svars

        # Propagate through call sites (BFS up to depth 6)
        changed = True
        depth = 0
        while changed and depth < _MAX_DEPTH:
            changed = False
            depth += 1
            for qn, fi in self.index.functions.items():
                for call in fi.calls:
                    callee_qn = self._resolve_callee(call.callee, fi)
                    if callee_qn not in self.index.functions:
                        continue
                    callee_fi = self.index.functions[callee_qn]
                    # Check positional args
                    session_vars_here = self.session_vars.get(qn, {})
                    for i, arg_name in enumerate(call.pos_args):
                        if arg_name in session_vars_here or arg_name in fi.session_params:
                            # Map to callee param
                            if i < len(callee_fi.params):
                                cparam = callee_fi.params[i]
                                callee_svars = self.session_vars.setdefault(callee_qn, {})
                                if cparam not in callee_svars:
                                    callee_svars[cparam] = "propagated"
                                    callee_fi.session_params.append(cparam)
                                    changed = True
                                    edge = SessionEdge(qn, callee_qn, arg_name, cparam, call.lineno)
                                    self.edges.setdefault(qn, []).append(edge)
                                    self.called_by.setdefault(callee_qn, set()).add(qn)
                    # Check keyword args
                    for kw, arg_name in call.kw_args.items():
                        if arg_name in session_vars_here or arg_name in fi.session_params:
                            callee_svars = self.session_vars.setdefault(callee_qn, {})
                            if kw not in callee_svars and kw in callee_fi.params:
                                callee_svars[kw] = "propagated"
                                if kw not in callee_fi.session_params:
                                    callee_fi.session_params.append(kw)
                                changed = True
                                edge = SessionEdge(qn, callee_qn, arg_name, kw, call.lineno)
                                self.edges.setdefault(qn, []).append(edge)
                                self.called_by.setdefault(callee_qn, set()).add(qn)

    def _resolve_callee(self, name: str, fi: FunctionInfo) -> str:
        """Try to resolve a callee name to a qualified function name."""
        # Try direct lookup
        if name in self.index.functions:
            return name
        # Try module-qualified
        module_qn = f"{fi.module}.{name}"
        if module_qn in self.index.functions:
            return module_qn
        # Try via imports stored in index
        root = name.split(".")[0]
        resolved = self.index.imports.get((fi.file, root))
        if resolved:
            rest = name[len(root):]
            full = resolved + rest
            if full in self.index.functions:
                return full
        return name

    def session_vars_for(self, qualname: str) -> dict[str, str]:
        return self.session_vars.get(qualname, {})

    def ops_for_var(self, fi: FunctionInfo, var: str) -> list[SessionOp]:
        """Return session ops on a specific variable in a function."""
        return [op for op in fi.session_ops if op.session_var == var]

    def has_commit(self, fi: FunctionInfo, var: str) -> bool:
        return any(op.kind == "commit" for op in self.ops_for_var(fi, var))

    def has_flush(self, fi: FunctionInfo, var: str) -> bool:
        return any(op.kind == "flush" for op in self.ops_for_var(fi, var))

    def first_op_kind(self, fi: FunctionInfo, var: str) -> str | None:
        ops = self.ops_for_var(fi, var)
        return ops[0].kind if ops else None
