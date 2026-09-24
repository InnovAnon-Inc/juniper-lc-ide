#!/usr/bin/env python3
import sys
import os
import subprocess
import math
from typing import Dict, List, Tuple, Optional, Set, Any
from lark import Lark, Transformer, v_args

# =====================================================================
# 1. Grammar Definition with Chained Lambda, Native De Bruijn & INCLUDE Support
# =====================================================================

LC_GRAMMAR = r"""
    start: (_NEWLINE | statement)*

    statement: ident_list ASSIGN expr           -> assign
             | "ASSERT" expr                    -> assert_expr
             | "ASSERT_EQ" expr "," expr        -> assert_eq
             | "INCLUDE" (STRING | IDENT)       -> include_stmt
             | expr                             -> eval_expr

    ident_list: IDENT ("," IDENT)*

    ?expr: abstraction
         | application

    abstraction: LAMBDA params DOT expr -> named_abs
               | LAMBDA+ DOT expr        -> anon_abs_chain

    params: IDENT+

    ?application: atom+

    ?atom: IDENT                 -> var
         | INT                   -> int_lit
         | BRACKETED_INT         -> debruijn
         | STRING                -> string_lit
         | "(" expr ")"

    LAMBDA: "\\" | "λ"
    DOT: "."
    ASSIGN: ":=" | "≡"
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

class DBBuiltin(DBTerm):
    def __init__(self, name: str, arity: int, args: List[DBTerm] = None):
        self.name = name
        self.arity = arity
        self.args = args if args is not None else []

    def __repr__(self):
        if not self.args:
            return f"<{self.name}>"
        return f"<{self.name} {' '.join(str(a) for a in self.args)}>"


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

BUILTIN_TABLE: Dict[str, int] = { # TODO need to handle sockets, too
    "PRINT": 1, # TODO can't just use fd_write ?
    "READ_LINE": 1, # TODO can't just use fd_read ?
    "EXEC_CMD": 1, # FIXME need shell-like power to redirect file descriptors between subprocesses ==> need direct access to low level operations like dup2, open, close, etc
    "FD_READ": 2,
    "FD_WRITE": 2,
    #"NEW_PAPER": 1,
    "PAGE": 1,
    #"DRAW_LINE": 2,
    "LINE": 2,
    #"DRAW_ARC": 2,
    "ARC": 2,
    "INTERSECT": 2,
    "SEND_AUDIO": 1, # TODO and recieve audio, too (mic)
}

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
    def include_stmt(self, meta, path_tok):
        p = str(path_tok)
        if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
            p = p[1:-1]
        return (meta.line, "INCLUDE", p)

    @v_args(meta=True, inline=True)
    def eval_expr(self, meta, expr):
        return (meta.line, "EVAL", expr)

    def named_abs(self, lambda_tok, param_list, dot_tok, body):
        res = body
        for p in reversed(param_list):
            res = SAbs(p, res)
        return res

    def anon_abs_chain(self, *args):
        body = args[-1]
        num_lambdas = len(args) - 2
        for _ in range(num_lambdas):
            body = SAbs(None, body)
        return body

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
        if node.name in BUILTIN_TABLE:
            return DBBuiltin(node.name, BUILTIN_TABLE[node.name])
        elif node.name in scope:
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
# 4. De Bruijn Arithmetic & Primitive Effect Execution Engine
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
    elif isinstance(term, DBBuiltin):
        return DBBuiltin(term.name, term.arity, [shift(a, d, cutoff) for a in term.args])
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
    elif isinstance(term, DBBuiltin):
        return DBBuiltin(term.name, term.arity, [db_substitute(a, value, index) for a in term.args])
    return term

# --- System & Hardware Primitive Handlers ---

GRAPHICS_STATE: Dict[str, Any] = {"papers": {}}

def execute_builtin_effect(name: str, args: List[DBTerm]) -> DBTerm:
    """Executes hardware, stdio, subprocess, audio, and relational geometry effects."""
    if name == "PRINT":
        val = args[0]
        print(f"[STDIO PRINT] {val}")
        return val

    elif name == "READ_LINE":
        prompt_val = args[0]
        line = input(f"{prompt_val}> ")
        return DBVar(get_free_var_index(line))

    elif name == "EXEC_CMD":
        cmd_term = args[0]
        cmd_str = str(cmd_term)
        try:
            res = subprocess.run(cmd_str, shell=True, capture_output=True, text=True)
            out = res.stdout.strip()
            print(f"[SHELL EXEC] {cmd_str} -> {out}")
            return DBVar(get_free_var_index(out if out else "0"))
        except Exception as e:
            print(f"[SHELL ERROR] {e}", file=sys.stderr)
            return DBVar(0)

    elif name == "FD_READ":
        fd_num, num_bytes = args[0], args[1]
        try:
            data = os.read(int(str(fd_num)), 1024)
            return DBVar(get_free_var_index(data.decode("utf-8", errors="ignore")))
        except Exception:
            return DBVar(0)

    elif name == "FD_WRITE":
        fd_num, data_term = args[0], args[1]
        try:
            os.write(int(str(fd_num)), str(data_term).encode("utf-8"))
            return data_term
        except Exception:
            return data_term

    #elif name == "NEW_PAPER":
    elif name == "PAGE":
        paper_id = str(args[0])
        GRAPHICS_STATE["papers"][paper_id] = []
        print(f"[GEOMETRY] Initialized paper context: '{paper_id}'")
        return args[0]

    #elif name == "DRAW_LINE":
    elif name == "LINE":
        p1, p2 = str(args[0]), str(args[1])
        print(f"[GEOMETRY DRAW LINE] Straightedge line passing through ({p1}) and ({p2})")
        return DBApp(args[0], args[1])

    #elif name == "DRAW_ARC":
    elif name == "ARC":
        center, radius = str(args[0]), str(args[1])
        print(f"[GEOMETRY DRAW ARC] Compass arc centered at ({center}) with radius ({radius})")
        return DBApp(args[0], args[1])

    elif name == "INTERSECT":
        g1, g2 = str(args[0]), str(args[1])
        print(f"[GEOMETRY INTERSECT] Relational intersection between ({g1}) and ({g2})")
        return DBApp(args[0], args[1])

    elif name == "SEND_AUDIO":
        audio_spec = str(args[0])
        print(f"[AUDIO EMIT] Generating signal / buffer frame: {audio_spec}")
        return args[0]

    return args[-1] if args else DBVar(0)

#def beta_reduce_step(term: DBTerm) -> Tuple[DBTerm, bool]:
#    if isinstance(term, DBApp):
#        if isinstance(term.fun, DBAbs):
#            reduced = db_substitute(term.fun.body, term.arg, 0)
#            return reduced, True
#        elif isinstance(term.fun, DBBuiltin):
#            builtin = term.fun
#            new_args = builtin.args + [term.arg]
#            if len(new_args) == builtin.arity:
#                result = execute_builtin_effect(builtin.name, new_args)
#                return result, True
#            else:
#                return DBBuiltin(builtin.name, builtin.arity, new_args), True
#        else:
#            new_fun, reduced = beta_reduce_step(term.fun)
#            if reduced:
#                return DBApp(new_fun, term.arg), True
#    return term, False
def beta_reduce_step(term: DBTerm) -> Tuple[DBTerm, bool]:
    if isinstance(term, DBApp):
        if isinstance(term.fun, DBAbs):
            # Reduce argument slightly or substitute directly
            reduced = db_substitute(term.fun.body, term.arg, 0)
            return reduced, True
        elif isinstance(term.fun, DBBuiltin):
            builtin = term.fun
            new_args = builtin.args + [term.arg]
            if len(new_args) == builtin.arity:
                result = execute_builtin_effect(builtin.name, new_args)
                return result, True
            else:
                return DBBuiltin(builtin.name, builtin.arity, new_args), True
        else:
            new_fun, reduced = beta_reduce_step(term.fun)
            if reduced:
                return DBApp(new_fun, term.arg), True
            # Fallback: reduce argument if function is already in normal form
            new_arg, arg_reduced = beta_reduce_step(term.arg)
            if arg_reduced:
                return DBApp(term.fun, new_arg), True
    return term, False

#def normalize(term: DBTerm, max_steps: int = 10000) -> DBTerm:
#def normalize(term: DBTerm, max_steps: int = 100000) -> DBTerm:
def normalize(term: DBTerm, max_steps: int = 1000000) -> DBTerm:
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
# 5. Structural Equivalence & Resugaring
# =====================================================================

def db_equal(t1: DBTerm, t2: DBTerm) -> bool:
    if type(t1) != type(t2): return False
    if isinstance(t1, DBVar): return t1.index == t2.index
    if isinstance(t1, DBAbs): return db_equal(t1.body, t2.body)
    if isinstance(t1, DBApp): return db_equal(t1.fun, t2.fun) and db_equal(t1.arg, t2.arg)
    if isinstance(t1, DBBuiltin): return t1.name == t2.name and len(t1.args) == len(t2.args)
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

    elif isinstance(term, DBBuiltin):
        return repr(term)

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
# 6. Execution Engine with Recursive Inclusion
# =====================================================================

def execute_program(
    filename: str,
    code: str,
    env: Dict[str, DBTerm],
    declared_terms: Dict[str, DBTerm],
    quiet: bool = False,
    visited_files: Optional[Set[str]] = None
) -> Tuple[List[str], Dict[str, DBTerm], Dict[str, DBTerm]]:
    if visited_files is None:
        visited_files = set()

    if filename and filename != "<stdin>" and os.path.exists(filename):
        visited_files.add(os.path.realpath(filename))

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
            if action == "INCLUDE":
                inc_path = stmt[2]
                if filename and filename != "<stdin>" and os.path.exists(filename):
                    base_dir = os.path.dirname(os.path.abspath(filename))
                else:
                    base_dir = os.getcwd()

                resolved_path = inc_path if os.path.isabs(inc_path) else os.path.join(base_dir, inc_path)
                canonical_path = os.path.realpath(resolved_path)

                if canonical_path in visited_files:
                    if not quiet:
                        print(f"# [INCLUDE] Skipping already included file: {inc_path}", file=sys.stderr)
                elif not os.path.exists(canonical_path):
                    print(f"\n❌ INCLUDE ERROR at {filename}:{line_no}: File not found '{inc_path}' ({canonical_path})", file=sys.stderr)
                    sys.exit(1)
                else:
                    visited_files.add(canonical_path)
                    with open(canonical_path, "r", encoding="utf-8") as f:
                        included_code = f.read()

                    inc_lines, env, declared_terms = execute_program(
                        canonical_path,
                        included_code,
                        env,
                        declared_terms,
                        quiet=quiet,
                        visited_files=visited_files
                    )
                    output_lines.extend(inc_lines)

            elif action == "ASSERT":
                expr = stmt[2]
                db_term = surface_to_debruijn(expr, env)
                evaluated = normalize(db_term)

                true_term = env.get("TRUE", env.get("⊤"))
                if not true_term or not db_equal(evaluated, true_term):
                    print(f"\n❌ ASSERTION FAILED at {filename}:{line_no}", file=sys.stderr)
                    print(f"   Got: {debruijn_to_str(evaluated, declared_terms, all_defined_symbols=all_defined_symbols)}", file=sys.stderr)
                    sys.exit(1)

                pretty_expr = debruijn_to_str(db_term, declared_terms, all_defined_symbols=all_defined_symbols)
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
                    print(f"   Left:  {debruijn_to_str(red_left, declared_terms)}", file=sys.stderr)
                    print(f"   Right: {debruijn_to_str(red_right, declared_terms)}", file=sys.stderr)
                    sys.exit(1)

                pretty_left = debruijn_to_str(db_left, declared_terms, all_defined_symbols=all_defined_symbols)
                pretty_right = debruijn_to_str(db_right, declared_terms, all_defined_symbols=all_defined_symbols)

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
