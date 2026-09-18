#!/usr/bin/env python3

import sys
import io
from typing import Dict, List, Tuple, Optional, Set
from lark import Lark, Transformer, v_args

# =====================================================================
# 1. Grammar Definition with Native De Bruijn Support
# =====================================================================

LC_GRAMMAR = r"""
    start: (_NEWLINE | statement)*

    statement: ident_list ASSIGN expr   -> assign
             | "ASSERT" expr            -> assert_expr
             | "ASSERT_EQ" expr "," expr -> assert_eq
             | expr                     -> eval_expr

    ident_list: IDENT ("," IDENT)*

    ?expr: abstraction
         | application

    abstraction: LAMBDA params DOT expr -> named_abs
               | LAMBDA DOT expr        -> anon_abs

    params: IDENT+

    ?application: atom+

    ?atom: IDENT                 -> var
         | INT                   -> int_lit
         | BRACKETED_INT         -> debruijn
         | STRING                -> string_lit
         | "(" expr ")"

    LAMBDA: "\\" | "λ"
    DOT: "."
    ASSIGN: ":="
    BRACKETED_INT: /\[\d+\]/

    IDENT: /(?!(?::=|\.|\(|\))\b)(?![\\λ])[+\-*\/<>=!&|~%^\w\u0080-\uFFFF]+/
    CONTINUATION: /\\\r?\n/

    %import common.INT
    %import common.ESCAPED_STRING -> STRING
    %import common.WS_INLINE
    %import common.NEWLINE -> _NEWLINE
    %ignore WS_INLINE
    %ignore CONTINUATION
    %ignore /#.*/
"""

# =====================================================================
# 2. De Bruijn Core AST
# =====================================================================

class DBTerm: pass

class DBVar(DBTerm):
    def __init__(self, index: int):
        self.index = index
    def __repr__(self):
        return f"[{self.index}]"

class DBAbs(DBTerm):
    def __init__(self, body: DBTerm):
        self.body = body
    def __repr__(self):
        return f"(λ.{self.body})"

class DBApp(DBTerm):
    def __init__(self, fun: DBTerm, arg: DBTerm):
        self.fun = fun
        self.arg = arg
    def __repr__(self):
        return f"({self.fun} {self.arg})"


class SurfaceAST: pass
class SVar(SurfaceAST):
    def __init__(self, name: str): self.name = name
class SDBVar(SurfaceAST):
    def __init__(self, index: int): self.index = index
class SAbs(SurfaceAST):
    def __init__(self, param: Optional[str], body: SurfaceAST):
        self.param = param
        self.body = body
class SApp(SurfaceAST):
    def __init__(self, fun: SurfaceAST, arg: SurfaceAST):
        self.fun = fun
        self.arg = arg

# =====================================================================
# 3. Surface Transformer & Conversion to De Bruijn
# =====================================================================

@v_args(inline=True)
class LCTransformer(Transformer):
    def start(self, *items): return [i for i in items if i is not None]
    def ident_list(self, *idents): return [str(i) for i in idents]
    def params(self, *idents): return [str(i) for i in idents]

    @v_args(meta=True, inline=True)
    def assign(self, meta, names, assign_op, expr):
        return (meta.line, "ASSIGN", names, expr)

    @v_args(meta=True, inline=True)
    def assert_expr(self, meta, expr):
        return (meta.line, "ASSERT", expr)

    @v_args(meta=True, inline=True)
    def assert_eq(self, meta, left, right):
        return (meta.line, "ASSERT_EQ", left, right)

    @v_args(meta=True, inline=True)
    def eval_expr(self, meta, expr):
        return (meta.line, "EVAL", expr)

    def named_abs(self, lambda_tok, param_list, dot_tok, body):
        res = body
        for p in reversed(param_list):
            res = SAbs(p, res)
        return res

    def anon_abs(self, lambda_tok, dot_tok, body):
        return SAbs(None, body)

    def application(self, *atoms):
        res = atoms[0]
        for arg in atoms[1:]:
            res = SApp(res, arg)
        return res

    def var(self, name): return SVar(str(name))
    def debruijn(self, val): return SDBVar(int(str(val)[1:-1]))

    def int_lit(self, val):
        n = int(val)
        body = SVar("x")
        for _ in range(n):
            body = SApp(SVar("f"), body)
        return SAbs("f", SAbs("x", body))

    def string_lit(self, val):
        s = str(val)[1:-1]
        if s.isdigit():
            n = int(s)
            body = SVar("x")
            for _ in range(n):
                body = SApp(SVar("f"), body)
            return SAbs("f", SAbs("x", body))
        return SVar(s)


FREE_VAR_MAP: Dict[str, int] = {}
REV_FREE_VAR_MAP: Dict[int, str] = {}

def get_free_var_index(name: str) -> int:
    """Assigns a persistent, deterministic De Bruijn index and reverse mapping for free vars."""
    if name not in FREE_VAR_MAP:
        idx = len(FREE_VAR_MAP) + 1000
        FREE_VAR_MAP[name] = idx
        REV_FREE_VAR_MAP[idx] = name
    return FREE_VAR_MAP[name]

def surface_to_debruijn(node: SurfaceAST, env: Dict[str, DBTerm], scope: List[str] = None) -> DBTerm:
    if scope is None: scope = []

    if isinstance(node, SVar):
        if node.name in scope:
            idx = scope[::-1].index(node.name)
            return DBVar(idx)
        elif node.name in env:
            return shift(env[node.name], len(scope), 0)
        else:
            return DBVar(len(scope) + get_free_var_index(node.name))

    elif isinstance(node, SDBVar):
        return DBVar(node.index)

    elif isinstance(node, SAbs):
        param_name = node.param if node.param is not None else f"_anon_{len(scope)}"
        return DBAbs(surface_to_debruijn(node.body, env, scope + [param_name]))

    elif isinstance(node, SApp):
        return DBApp(surface_to_debruijn(node.fun, env, scope), surface_to_debruijn(node.arg, env, scope))

    raise ValueError(f"Unknown Surface AST node: {node}")

# =====================================================================
# 4. De Bruijn Arithmetic (Shifting & Beta Reduction)
# =====================================================================

def shift(term: DBTerm, d: int, cutoff: int = 0) -> DBTerm:
    if isinstance(term, DBVar):
        if term.index >= cutoff:
            return DBVar(term.index + d)
        return term
    elif isinstance(term, DBAbs):
        return DBAbs(shift(term.body, d, cutoff + 1))
    elif isinstance(term, DBApp):
        return DBApp(shift(term.fun, d, cutoff), shift(term.arg, d, cutoff))
    return term

def db_substitute(term: DBTerm, value: DBTerm, index: int = 0) -> DBTerm:
    if isinstance(term, DBVar):
        if term.index == index:
            return shift(value, index, 0)
        elif term.index > index:
            return DBVar(term.index - 1)
        return term
    elif isinstance(term, DBAbs):
        return DBAbs(db_substitute(term.body, value, index + 1))
    elif isinstance(term, DBApp):
        return DBApp(db_substitute(term.fun, value, index), db_substitute(term.arg, value, index))
    return term

def beta_reduce_step(term: DBTerm) -> Tuple[DBTerm, bool]:
    if isinstance(term, DBApp):
        if isinstance(term.fun, DBAbs):
            reduced = db_substitute(term.fun.body, term.arg, 0)
            return reduced, True
        else:
            new_fun, reduced = beta_reduce_step(term.fun)
            if reduced:
                return DBApp(new_fun, term.arg), True
    return term, False

def normalize(term: DBTerm, max_steps: int = 10000) -> DBTerm:
    curr = term
    for _ in range(max_steps):
        curr, reduced = beta_reduce_step(curr)
        if not reduced:
            if isinstance(curr, DBAbs):
                body_norm = normalize(curr.body, max_steps=100)
                return DBAbs(body_norm)
            elif isinstance(curr, DBApp):
                fun_norm = normalize(curr.fun, max_steps=100)
                arg_norm = normalize(curr.arg, max_steps=100)
                return DBApp(fun_norm, arg_norm)
            break
    return curr

# =====================================================================
# 5. Structural Equivalence & Resugaring
# =====================================================================

def db_equal(t1: DBTerm, t2: DBTerm) -> bool:
    if type(t1) != type(t2): return False
    if isinstance(t1, DBVar): return t1.index == t2.index
    if isinstance(t1, DBAbs): return db_equal(t1.body, t2.body)
    if isinstance(t1, DBApp): return db_equal(t1.fun, t2.fun) and db_equal(t1.arg, t2.arg)
    return False

def try_decode_church(term: DBTerm) -> Optional[int]:
    if not isinstance(term, DBAbs): return None
    if not isinstance(term.body, DBAbs): return None

    curr = term.body.body
    count = 0
    while isinstance(curr, DBApp):
        if isinstance(curr.fun, DBVar) and curr.fun.index == 1:
            count += 1
            curr = curr.arg
        else:
            return None

    if isinstance(curr, DBVar) and curr.index == 0:
        return count
    return None

def debruijn_to_str(
    term: DBTerm,
    declared: Dict[str, DBTerm],
    names: List[str] = None,
    parent_type=None,
    exclude: Optional[Set[str]] = None
) -> str:
    if names is None: names = []
    if exclude is None: exclude = set()

    # 1. Resugar via declared dictionary lookup (excluding target names currently being defined)
    for name, decl in declared.items():
        if name not in exclude and db_equal(term, decl):
            return name

    # 2. Resugar Church Integers if not explicitly excluded
    num = try_decode_church(term)
    if num is not None and str(num) not in exclude:
        return str(num)

    # 3. De Bruijn Variables (and mapped free variables)
    if isinstance(term, DBVar):
        if term.index < len(names):
            return names[-(term.index + 1)]
        free_idx = term.index - len(names)
        if free_idx in REV_FREE_VAR_MAP:
            return REV_FREE_VAR_MAP[free_idx]
        return f"_{term.index}"

    # 4. Abstractions
    elif isinstance(term, DBAbs):
        var_name = chr(97 + (len(names) % 26))
        if names.count(var_name) > 0:
            var_name = f"{var_name}{len(names)}"

        body_str = debruijn_to_str(term.body, declared, names + [var_name], None, exclude)
        res = f"\\{var_name}.{body_str}"
        return f"({res})" if parent_type in (DBApp, "fun") else res

    # 5. Applications
    elif isinstance(term, DBApp):
        fun_str = debruijn_to_str(term.fun, declared, names, "fun", exclude)
        arg_str = debruijn_to_str(term.arg, declared, names, DBApp, exclude)
        res = f"{fun_str} {arg_str}"
        return f"({res})" if parent_type == DBApp else res

    return str(term)

# =====================================================================
# 6. Idempotency Assertion Verification Engine
# =====================================================================

def assert_unit_idempotency(
    db_term: DBTerm,
    pretty_str: str,
    env: Dict[str, DBTerm],
    declared_terms: Dict[str, DBTerm],
    exclude: Optional[Set[str]] = None
):
    """Unit-level check: Re-parses pretty_str to ensure semantic equality and syntactic idempotency."""
    parser = Lark(LC_GRAMMAR, parser="lalr", propagate_positions=True)
    try:
        tree = parser.parse(pretty_str)
        ast_list = LCTransformer().transform(tree)
        if not ast_list or ast_list[0][1] != "EVAL":
            raise ValueError("Resugared string failed to parse as an evaluation expression.")
        reparsed_ast = ast_list[0][2]
    except Exception as e:
        raise AssertionError(f"Unit Idempotency Error: Failed to parse resugared expression '{pretty_str}': {e}")

    reparsed_db = surface_to_debruijn(reparsed_ast, env)

    if not db_equal(db_term, reparsed_db):
        raise AssertionError(
            f"Unit Idempotency Error: Semantics changed after resugaring!\n"
            f"  Original DB: {db_term}\n"
            f"  Pretty Str:  '{pretty_str}'\n"
            f"  Reparsed DB: {reparsed_db}"
        )

    pretty_str_pass2 = debruijn_to_str(reparsed_db, declared_terms, exclude=exclude)
    if pretty_str != pretty_str_pass2:
        raise AssertionError(
            f"Unit Idempotency Error: Syntactic resugaring is not idempotent!\n"
            f"  Pass 1: '{pretty_str}'\n"
            f"  Pass 2: '{pretty_str_pass2}'"
        )

# =====================================================================
# 7. Execution Driver
# =====================================================================

def execute_program(
    filename: str,
    code: str,
    env: Dict[str, DBTerm],
    declared_terms: Dict[str, DBTerm],
    out_stream=sys.stdout
) -> str:
    parser = Lark(LC_GRAMMAR, parser="lalr", propagate_positions=True)

    try:
        tree = parser.parse(code)
        statements = LCTransformer().transform(tree)
    except Exception as e:
        sys.stderr.write(f"\n❌ PARSE ERROR in {filename}:\n{e}\n")
        sys.exit(1)

    sys.stderr.write(f"=== Evaluating: {filename} ===\n")

    for stmt in statements:
        line_no, action = stmt[0], stmt[1]

        try:
            if action == "ASSERT":
                expr = stmt[2]
                db_term = surface_to_debruijn(expr, env)
                evaluated = normalize(db_term)

                true_term = env.get("TRUE", env.get("⊤"))
                if not true_term or not db_equal(evaluated, true_term):
                    sys.stderr.write(f"\n❌ ASSERTION FAILED at {filename}:{line_no}\n")
                    sys.stderr.write(f"   Got: {debruijn_to_str(evaluated, declared_terms)}\n")
                    sys.exit(1)

                sys.stderr.write(f"✓ ASSERTION PASSED (Line {line_no})\n")
                pretty_expr = debruijn_to_str(db_term, declared_terms)
                assert_unit_idempotency(db_term, pretty_expr, env, declared_terms)
                out_stream.write(f"ASSERT {pretty_expr}\n")

            elif action == "ASSERT_EQ":
                left_ast, right_ast = stmt[2], stmt[3]
                db_left = surface_to_debruijn(left_ast, env)
                db_right = surface_to_debruijn(right_ast, env)
                red_left = normalize(db_left)
                red_right = normalize(db_right)

                if not db_equal(red_left, red_right):
                    sys.stderr.write(f"\n❌ ASSERT_EQ FAILED at {filename}:{line_no}\n")
                    sys.stderr.write(f"   Left:  {debruijn_to_str(red_left, declared_terms)}\n")
                    sys.stderr.write(f"   Right: {debruijn_to_str(red_right, declared_terms)}\n")
                    sys.exit(1)

                sys.stderr.write(f"✓ ASSERT_EQ PASSED (Line {line_no})\n")
                pretty_left = debruijn_to_str(db_left, declared_terms)
                pretty_right = debruijn_to_str(db_right, declared_terms)
                assert_unit_idempotency(db_left, pretty_left, env, declared_terms)
                assert_unit_idempotency(db_right, pretty_right, env, declared_terms)
                out_stream.write(f"ASSERT_EQ {pretty_left}, {pretty_right}\n")

            elif action == "ASSIGN":
                target, expr = stmt[2], stmt[3]
                db_term = surface_to_debruijn(expr, env)

                names_str = ", ".join(target)
                exclude_set = set(target)
                pretty = debruijn_to_str(db_term, declared_terms, exclude=exclude_set)

                assert_unit_idempotency(db_term, pretty, env, declared_terms, exclude=exclude_set)

                out_stream.write(f"{names_str} := {pretty}\n")

                for name in target:
                    env[name] = db_term
                    declared_terms[name] = db_term

            elif action == "EVAL":
                expr = stmt[2]
                db_term = surface_to_debruijn(expr, env)
                pretty = debruijn_to_str(db_term, declared_terms)
                assert_unit_idempotency(db_term, pretty, env, declared_terms)
                out_stream.write(f"{pretty}\n")

        except RecursionError:
            sys.stderr.write(f"\n💥 CRASH: Maximum Recursion Depth Exceeded at {filename}:{line_no}\n")
            sys.exit(1)
        except Exception as e:
            sys.stderr.write(f"\n💥 CRASH: Unexpected Error at {filename}:{line_no}: {e}\n")
            sys.exit(1)


def assert_integration_idempotency(filename: str, code: str):
    """Integration-level check: Executes twice in sequence and verifies output stability."""
    buf1 = io.StringIO()
    env1, declared1 = {}, {}
    execute_program(filename, code, env1, declared1, out_stream=buf1)
    pass1_output = buf1.getvalue()

    buf2 = io.StringIO()
    env2, declared2 = {}, {}
    execute_program(f"{filename}.pass2", pass1_output, env2, declared2, out_stream=buf2)
    pass2_output = buf2.getvalue()

    if pass1_output != pass2_output:
        lines1, lines2 = pass1_output.splitlines(), pass2_output.splitlines()
        for i, (l1, l2) in enumerate(zip(lines1, lines2)):
            if l1 != l2:
                raise AssertionError(
                    f"Integration Idempotency Divergence at line {i+1}:\n"
                    f"  Pass 1: {l1}\n"
                    f"  Pass 2: {l2}"
                )
        raise AssertionError("Integration Idempotency Divergence: Output length mismatch.")

    for k, v in declared1.items():
        if k not in declared2 or not db_equal(v, declared2[k]):
            raise AssertionError(f"Integration Environment Divergence for symbol '{k}'.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        global_env: Dict[str, DBTerm] = {}
        global_declared: Dict[str, DBTerm] = {}

        for path in sys.argv[1:]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                assert_integration_idempotency(path, content)
                execute_program(path, content, global_env, global_declared, out_stream=sys.stdout)
