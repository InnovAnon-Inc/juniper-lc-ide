#!/usr/bin/env python3

# TODO handle beta-equivalence, especially for resugaring and asymptotic complexity analysis
# TODO resugaring output should contain structured comments with kolmogorov complexity, time and space complexity ?
# TODO write a compiler in lc, and have it compile itself
# TODO (builtin) need graphics primitives, such as creating a drawing space (new piece of paper), drawing lines (straightedge) and arcs (compass); must be able to work in the browser and also in a physical notebook
# TODO (builtin) need systems primitives, such as for stdio
# TODO need to define common structures, such as loops

# INCLUDE

# for IPC/stdio and use as a shell:
# IN/OUT
# File Descriptors

# geometry: relational instead of coordinate-based
# NEW_PAPER
# DRAW_LINE
# DRAW_ARC
# INTERSECT

# SEND_AUDIO

## =====================================================================
## 8. Universal Primitives & Effect Handlers (Browser / CLI / UEFI)
## =====================================================================
#
#def evaluate_builtin_primitive(name: str, arg: DBTerm) -> Optional[DBTerm]:
#    """
#    Handles hardware/system effects for graphics, audio, and stdio 
#    when running in CLI, browser, or UEFI environments.
#    """
#    if name == "BUILTIN_PRINT":
#        # Stdio primitive for printing evaluated structures
#        print(f"[STDIN/STDOUT] {arg}")
#        return arg
#    elif name == "BUILTIN_DRAW_LINE":
#        # Straightedge graphics primitive 
#        return arg
#    elif name == "BUILTIN_AUDIO_EMIT":
#        # Audio device primitive (e.g. 432 Hz wave generation)
#        return arg
#    return None

import sys
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

    def var(self, name):
        return SVar(str(name))

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
INV_FREE_VAR_MAP: Dict[int, str] = {}

def get_free_var_index(name: str) -> int:
    if name not in FREE_VAR_MAP:
        idx = len(FREE_VAR_MAP) + 1000
        FREE_VAR_MAP[name] = idx
        INV_FREE_VAR_MAP[idx] = name
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
                body_norm = normalize(curr.body, max_steps)
                if not db_equal(curr.body, body_norm):
                    curr = DBAbs(body_norm)
                    continue
            elif isinstance(curr, DBApp):
                fun_norm = normalize(curr.fun, max_steps)
                arg_norm = normalize(curr.arg, max_steps)
                if not (db_equal(curr.fun, fun_norm) and db_equal(curr.arg, arg_norm)):
                    curr = DBApp(fun_norm, arg_norm)
                    continue
            break
    return curr

# =====================================================================
# 5. Structural Equivalence & Scoped Resugaring
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
    exclude_names: Optional[Set[str]] = None,
    all_defined_symbols: Optional[Set[str]] = None
) -> str:
    if names is None: names = []
    if exclude_names is None: exclude_names = set()

    for name, decl in declared.items():
        if name in exclude_names:
            continue
        if db_equal(term, decl):
            return name

    num = try_decode_church(term)
    if num is not None:
        s_num = str(num)
        if s_num not in exclude_names:
            if all_defined_symbols is not None and s_num in all_defined_symbols and s_num not in declared:
                pass
            else:
                return s_num

    if isinstance(term, DBVar):
        if term.index < len(names):
            return names[-(term.index + 1)]
        free_idx = term.index - len(names)
        if free_idx in INV_FREE_VAR_MAP:
            return INV_FREE_VAR_MAP[free_idx]
        return f"_{term.index}"

    elif isinstance(term, DBAbs):
        params = []
        curr = term
        while isinstance(curr, DBAbs):
            var_name = chr(97 + ((len(names) + len(params)) % 26))
            if (names + params).count(var_name) > 0:
                var_name = f"{var_name}{len(names) + len(params)}"
            params.append(var_name)
            curr = curr.body

        body_str = debruijn_to_str(
            curr, declared, names + params,
            parent_type=None, exclude_names=exclude_names,
            all_defined_symbols=all_defined_symbols
        )
        param_str = " ".join(params)
        res = f"\\{param_str}.{body_str}"
        return f"({res})" if parent_type in (DBApp, "fun") else res

    elif isinstance(term, DBApp):
        fun_str = debruijn_to_str(
            term.fun, declared, names,
            parent_type="fun", exclude_names=exclude_names,
            all_defined_symbols=all_defined_symbols
        )
        arg_str = debruijn_to_str(
            term.arg, declared, names,
            parent_type=DBApp, exclude_names=exclude_names,
            all_defined_symbols=all_defined_symbols
        )
        res = f"{fun_str} {arg_str}"
        return f"({res})" if parent_type == DBApp else res

    return str(term)

# =====================================================================
# 6. Static Time and Space Complexity Analysis
# =====================================================================

def db_node_count(term: DBTerm) -> int:
    if isinstance(term, DBVar): return 1
    if isinstance(term, DBAbs): return 1 + db_node_count(term.body)
    if isinstance(term, DBApp): return 1 + db_node_count(term.fun) + db_node_count(term.arg)
    return 1

def db_depth(term: DBTerm) -> int:
    if isinstance(term, DBVar): return 1
    if isinstance(term, DBAbs): return 1 + db_depth(term.body)
    if isinstance(term, DBApp): return 1 + max(db_depth(term.fun), db_depth(term.arg))
    return 1

def analyze_static_complexity(term: DBTerm, declared: Dict[str, DBTerm]) -> Tuple[str, str]:
    """
    Statically predicts time and space complexity bounds for predictable terms.
    Returns a tuple of strings: (Time Complexity, Space Complexity).
    """
    # Check if it's a Church numeral
    num = try_decode_church(term)
    if num is not None:
        return "O(1)", "O(1)"

    # Check for binary arithmetic patterns if term is an application tree
    # e.g., PLUS m n, MULT m n, POW b n
    nodes = db_node_count(term)
    depth = db_depth(term)

    # Heuristic pattern matching for common combinator structures
    if isinstance(term, DBApp):
        # Look for named functions in declared environment if possible
        pass

    # General structural fallback
    if nodes < 15:
        return "O(1)", "O(1)"
    elif depth > 50:
        return "O(2^n) [Deep Recursion / Potential Divergence]", f"O({depth})"
    
    return f"O(n) [Structural nodes: {nodes}]", f"O({depth})"

# =====================================================================
# 7. Self-Checking Assertions & Execution Engine
# =====================================================================

def verify_unit_idempotency(
    term: DBTerm,
    resugared_str: str,
    env: Dict[str, DBTerm],
    declared_terms: Dict[str, DBTerm],
    parser: Lark,
    line_no: int,
    filename: str,
    target_names: Optional[List[str]] = None,
    all_defined_symbols: Optional[Set[str]] = None
):
    try:
        dummy_code = f"_dummy := {resugared_str}"
        tree = parser.parse(dummy_code)
        stmts = LCTransformer().transform(tree)
        expr_ast = stmts[0][3]
        parsed_db = surface_to_debruijn(expr_ast, env)

        if not db_equal(term, parsed_db) and debruijn_to_str(term, declared_terms, all_defined_symbols=all_defined_symbols) != debruijn_to_str(parsed_db, declared_terms, all_defined_symbols=all_defined_symbols):
            print(
                f"\n❌ UNIT IDEMPOTENCY FAILED at {filename}:{line_no}\n"
                f"   Target: {target_names}\n"
                f"   Resugared: {resugared_str}\n"
                f"   Original: {debruijn_to_str(term, declared_terms, all_defined_symbols=all_defined_symbols)}\n"
                f"   Parsed:   {debruijn_to_str(parsed_db, declared_terms, all_defined_symbols=all_defined_symbols)}",
                file=sys.stderr
            )
            sys.exit(1)
    except Exception as e:
        print(
            f"\n❌ UNIT IDEMPOTENCY PARSE ERROR at {filename}:{line_no}\n"
            f"   Resugared String: '{resugared_str}'\n"
            f"   Error: {e}",
            file=sys.stderr
        )
        sys.exit(1)

def execute_program(
    filename: str,
    code: str,
    env: Dict[str, DBTerm],
    declared_terms: Dict[str, DBTerm],
    enable_idempotency_check: bool = True,
    quiet: bool = False
) -> Tuple[List[str], Dict[str, DBTerm], Dict[str, DBTerm]]:
    parser = Lark(LC_GRAMMAR, parser="lalr", propagate_positions=True)

    try:
        tree = parser.parse(code)
        statements = LCTransformer().transform(tree)
    except Exception as e:
        print(f"\n❌ PARSE ERROR in {filename}:\n{e}", file=sys.stderr)
        sys.exit(1)

    all_defined_symbols = set()
    for stmt in statements:
        if stmt[1] == "ASSIGN":
            all_defined_symbols.update(stmt[2])

    if not quiet:
        print(f"=== Evaluating: {filename} ===", file=sys.stderr)

    output_lines: List[str] = []

    for stmt in statements:
        line_no, action = stmt[0], stmt[1]

        try:
            if action == "ASSERT":
                expr = stmt[2]
                db_term = surface_to_debruijn(expr, env)
                evaluated = normalize(db_term)

                true_term = env.get("TRUE", env.get("⊤"))
                if not true_term or not db_equal(evaluated, true_term):
                    print(f"\n❌ ASSERTION FAILED at {filename}:{line_no}", file=sys.stderr)
                    print(f"   Got: {debruijn_to_str(evaluated, declared_terms, all_defined_symbols=all_defined_symbols)}", file=sys.stderr)
                    sys.exit(1)

                pretty_expr = debruijn_to_str(db_term, declared_terms, all_defined_symbols=all_defined_symbols)
                
                # Output Kolmogorov and Static Complexity stats to stderr
                time_c, space_c = analyze_static_complexity(db_term, declared_terms)
                print(f"# [STATIC COMPLEXITY] Line {line_no} | Time: {time_c} | Space: {space_c}", file=sys.stderr)
                print(f"# [KOLMOGOROV K(x) APPROX] Line {line_no} | Length: {len(pretty_expr)} chars", file=sys.stderr)

                if enable_idempotency_check:
                    verify_unit_idempotency(db_term, pretty_expr, env, declared_terms, parser, line_no, filename, all_defined_symbols=all_defined_symbols)

                line_out = f"ASSERT {pretty_expr}"
                output_lines.append(line_out)
                if not quiet:
                    print(line_out)
                    print(f"✓ ASSERTION PASSED (Line {line_no})", file=sys.stderr)

            elif action == "ASSERT_EQ":
                left_ast, right_ast = stmt[2], stmt[3]
                db_left = surface_to_debruijn(left_ast, env)
                db_right = surface_to_debruijn(right_ast, env)

                red_left = normalize(db_left)
                red_right = normalize(db_right)

                if not db_equal(red_left, red_right):
                    print(f"\n❌ ASSERT_EQ FAILED at {filename}:{line_no}", file=sys.stderr)
                    sys.exit(1)

                pretty_left = debruijn_to_str(db_left, declared_terms, all_defined_symbols=all_defined_symbols)
                pretty_right = debruijn_to_str(db_right, declared_terms, all_defined_symbols=all_defined_symbols)

                time_c, space_c = analyze_static_complexity(db_left, declared_terms)
                print(f"# [STATIC COMPLEXITY] Line {line_no} (Left) | Time: {time_c} | Space: {space_c}", file=sys.stderr)
                print(f"# [KOLMOGOROV K(x) APPROX] Line {line_no} (Left) | Length: {len(pretty_left)} chars", file=sys.stderr)

                if enable_idempotency_check:
                    verify_unit_idempotency(db_left, pretty_left, env, declared_terms, parser, line_no, filename, all_defined_symbols=all_defined_symbols)
                    verify_unit_idempotency(db_right, pretty_right, env, declared_terms, parser, line_no, filename, all_defined_symbols=all_defined_symbols)

                line_out = f"ASSERT_EQ {pretty_left}, {pretty_right}"
                output_lines.append(line_out)
                if not quiet:
                    print(line_out)
                    print(f"✓ ASSERT_EQ PASSED (Line {line_no})", file=sys.stderr)

            elif action == "ASSIGN":
                target, expr = stmt[2], stmt[3]
                db_term = surface_to_debruijn(expr, env)

                exclude_set = set(target)
                pretty = debruijn_to_str(db_term, declared_terms, exclude_names=exclude_set, all_defined_symbols=all_defined_symbols)

                # Output Kolmogorov and Static Complexity stats to stderr
                time_c, space_c = analyze_static_complexity(db_term, declared_terms)
                print(f"# [STATIC COMPLEXITY] Assign '{', '.join(target)}' (Line {line_no}) | Time: {time_c} | Space: {space_c}", file=sys.stderr)
                print(f"# [KOLMOGOROV K(x) APPROX] Assign '{', '.join(target)}' (Line {line_no}) | Length: {len(pretty)} chars", file=sys.stderr)

                if enable_idempotency_check:
                    verify_unit_idempotency(db_term, pretty, env, declared_terms, parser, line_no, filename, target_names=target, all_defined_symbols=all_defined_symbols)

                names_str = ", ".join(target)
                line_out = f"{names_str} := {pretty}"
                output_lines.append(line_out)
                if not quiet:
                    print(line_out)

                for name in target:
                    env[name] = db_term
                    declared_terms[name] = db_term

            elif action == "EVAL":
                expr = stmt[2]
                db_term = surface_to_debruijn(expr, env)
                evaluated = normalize(db_term)

                pretty_in = debruijn_to_str(db_term, declared_terms, all_defined_symbols=all_defined_symbols)
                pretty_res = debruijn_to_str(evaluated, declared_terms, all_defined_symbols=all_defined_symbols)

                time_c, space_c = analyze_static_complexity(db_term, declared_terms)
                print(f"# [STATIC COMPLEXITY] Eval (Line {line_no}) | Time: {time_c} | Space: {space_c}", file=sys.stderr)
                print(f"# [KOLMOGOROV K(x) APPROX] Eval (Line {line_no}) | Length: {len(pretty_in)} chars", file=sys.stderr)

                if enable_idempotency_check:
                    verify_unit_idempotency(db_term, pretty_in, env, declared_terms, parser, line_no, filename, all_defined_symbols=all_defined_symbols)

                line_out = pretty_in
                output_lines.append(line_out)
                if not quiet:
                    print(f"# Eval ({filename}:{line_no}): {pretty_in}", file=sys.stderr)
                    print(f"# Result → {pretty_res}", file=sys.stderr)
                    print(line_out)

        except RecursionError:
            print(f"\n💥 CRASH: Maximum Recursion Depth Exceeded (Divergent Term?)", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"\n💥 CRASH: Unexpected Error: {e}", file=sys.stderr)
            sys.exit(1)

    return output_lines, env, declared_terms


if __name__ == "__main__":
    if len(sys.argv) > 1:
        global_env: Dict[str, DBTerm] = {}
        global_declared: Dict[str, DBTerm] = {}

        for path in sys.argv[1:]:
            with open(path, "r", encoding="utf-8") as f:
                execute_program(path, f.read(), global_env, global_declared)
