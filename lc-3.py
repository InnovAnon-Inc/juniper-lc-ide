#!/usr/bin/env python3

# TODO idempotent resugaring
# TODO visual evaluation -- seed of life-like
# TODO support f**n (superscript) repeated applications
# TODO graphics primitives / geometric proofs, e.g., circle/arc/compass and straightedge
# TODO system primitives, e.g., stdio/print

import sys
from typing import Dict, List, Tuple, Optional, Union
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


# Dynamic AST for Named Parsing Phase
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

    # Inject meta parameter to capture line numbers for all top-level statements
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

#@v_args(inline=True)
#class LCTransformer(Transformer):
#    def start(self, *items): return [i for i in items if i is not None]
#    def ident_list(self, *idents): return [str(i) for i in idents]
#    def assign(self, names, assign_op, expr): return (names, expr)
#    def assert_expr(self, expr): return ("ASSERT", expr)
#    def assert_eq(self, left, right): return ("ASSERT_EQ", (left, right))
#    def eval_expr(self, expr): return ("_", expr)
#    def params(self, *idents): return [str(i) for i in idents]

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
    #def debruijn(self, val): return SDBVar(int(str(val)[1:-1]))
    def debruijn(self, val): 
        # Parse [0], [1] directly into DBVar indices
        return SDBVar(int(str(val)[1:-1]))

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

def get_free_var_index(name: str) -> int:
    """Assigns a persistent, deterministic De Bruijn index to free variables."""
    if name not in FREE_VAR_MAP:
        FREE_VAR_MAP[name] = len(FREE_VAR_MAP) + 1000
    return FREE_VAR_MAP[name]

def surface_to_debruijn(node: SurfaceAST, env: Dict[str, DBTerm], scope: List[str] = None) -> DBTerm:
    if scope is None: scope = []

    if isinstance(node, SVar):
        if node.name in scope:
            # Distance from closest binder
            #idx = len(scope) - 1 - scope[::-1].index(node.name)
            idx = scope[::-1].index(node.name)
            return DBVar(idx)
        elif node.name in env:
            # Substitute stored global definition
            return shift(env[node.name], len(scope), 0)
        else:
            # Deterministic index for unbound global free variables
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
    """Shifts free variables in a term by d above cutoff."""
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
    """Substitutes value for variable at De Bruijn index in term."""
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
    """Performs one step of Weak Head Normal Form (WHNF) reduction."""
    if isinstance(term, DBApp):
        if isinstance(term.fun, DBAbs):
            # Beta reduction: (λ. M) N ==> M [0 := N]
            reduced = db_substitute(term.fun.body, term.arg, 0)
            return reduced, True
        else:
            new_fun, reduced = beta_reduce_step(term.fun)
            if reduced:
                return DBApp(new_fun, term.arg), True
    return term, False

def normalize(term: DBTerm, max_steps: int = 10000) -> DBTerm:
    """Fully reduces a term into Normal Form (NF)."""
    curr = term
    for _ in range(max_steps):
        # First reduce to WHNF
        curr, reduced = beta_reduce_step(curr)
        if not reduced:
            # Congruence step: reduce inside abstractions and applications
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
    """De Bruijn terms offer structural equivalence directly (Alpha Equivalence)."""
    if type(t1) != type(t2): return False
    if isinstance(t1, DBVar): return t1.index == t2.index
    if isinstance(t1, DBAbs): return db_equal(t1.body, t2.body)
    if isinstance(t1, DBApp): return db_equal(t1.fun, t2.fun) and db_equal(t1.arg, t2.arg)
    return False

def try_decode_church(term: DBTerm) -> Optional[int]:
    """Detects Church numerals: λf. λx. f^n x -> (λ. λ. [1]^n [0])"""
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

def debruijn_to_str(term: DBTerm, declared: Dict[str, DBTerm], names: List[str] = None, parent_type=None) -> str:
    """Pretty prints De Bruijn terms back into named lambda form without shadowing."""
    if names is None: names = []

    # Resugar via declared dictionary lookup
    for name, decl in declared.items():
        if db_equal(term, decl):
            return name

    # Resugar Church Integers
    num = try_decode_church(term)
    if num is not None:
        return str(num)

    if isinstance(term, DBVar):
        if term.index < len(names):
            return names[-(term.index + 1)]
        return f"_{term.index}"

    elif isinstance(term, DBAbs):
        # Generate fresh variable name to guarantee non-shadowing
        var_name = chr(97 + (len(names) % 26))
        if names.count(var_name) > 0:
            var_name = f"{var_name}{len(names)}"

        body_str = debruijn_to_str(term.body, declared, names + [var_name])
        res = f"\\{var_name}.{body_str}"
        return f"({res})" if parent_type in (DBApp, "fun") else res

    elif isinstance(term, DBApp):
        fun_str = debruijn_to_str(term.fun, declared, names, "fun")
        arg_str = debruijn_to_str(term.arg, declared, names, DBApp)
        res = f"{fun_str} {arg_str}"
        return f"({res})" if parent_type == DBApp else res

    return str(term)

# =====================================================================
# 6. Execution Driver
# =====================================================================

#def execute_program(code: str): # TODO crashes should attempt to record line number and other useful info
#    parser = Lark(LC_GRAMMAR, parser="lalr", transformer=LCTransformer())
#    statements = parser.parse(code)
#
#    env: Dict[str, DBTerm] = {}
#    declared_terms: Dict[str, DBTerm] = {}
#
#    print("=== De Bruijn Lambda Reduction Engine ===")
#    for target, ast in statements:
#        if target == "ASSERT":
#            db_term = surface_to_debruijn(ast, env)
#            evaluated = normalize(db_term)
#
#            true_term = env.get("TRUE", env.get("⊤"))
#            if not true_term or not db_equal(evaluated, true_term):
#                print(f"\n❌ ASSERTION FAILED: Got {debruijn_to_str(evaluated, declared_terms)}")
#                sys.exit(1)
#            print("✓ ASSERTION PASSED") # TODO display info about what passed
#
#        elif target == "ASSERT_EQ":
#            left_ast, right_ast = ast
#            red_left = normalize(surface_to_debruijn(left_ast, env))
#            red_right = normalize(surface_to_debruijn(right_ast, env))
#
#            if not db_equal(red_left, red_right):
#                print(f"\n❌ ASSERT_EQ FAILED:\n  Left:  {debruijn_to_str(red_left, declared_terms)}\n  Right: {debruijn_to_str(red_right, declared_terms)}")
#                sys.exit(1)
#            print("✓ ASSERT_EQ PASSED") # TODO display info about what passed
#
#        elif target != "_":
#            db_term = surface_to_debruijn(ast, env)
#            
#            names_str = ", ".join(target)
#            pretty = debruijn_to_str(db_term, declared_terms)
#            print(f"{names_str} := {pretty}")
#
#            for name in target:
#                env[name] = db_term
#                declared_terms[name] = db_term
#
#        else:
#            db_term = surface_to_debruijn(ast, env)
#            print(f"\nEval: {debruijn_to_str(db_term, declared_terms)}")
#            evaluated = normalize(db_term)
#            print(f"Result → {debruijn_to_str(evaluated, declared_terms)}\n")

def execute_program(filename: str, code: str, env: Dict[str, DBTerm], declared_terms: Dict[str, DBTerm]):
    # Remove transformer=LCTransformer() from the parser initialization
    parser = Lark(LC_GRAMMAR, parser="lalr", propagate_positions=True)

    try:
        # Parse into a tree first, then transform it
        tree = parser.parse(code)
        statements = LCTransformer().transform(tree)
    except Exception as e:
        print(f"\n❌ PARSE ERROR in {filename}:\n{e}")
        sys.exit(1)

    print(f"=== Evaluating: {filename} ===")

    for stmt in statements:
        line_no, action = stmt[0], stmt[1]

        # ... [Rest of the evaluation loop remains identical] ...
#def execute_program(filename: str, code: str, env: Dict[str, DBTerm], declared_terms: Dict[str, DBTerm]):
#    # propagate_positions=True is required for meta.line to populate
#    parser = Lark(LC_GRAMMAR, parser="lalr", transformer=LCTransformer(), propagate_positions=True)
#
#    try:
#        statements = parser.parse(code)
#    except Exception as e:
#        print(f"\n❌ PARSE ERROR in {filename}:\n{e}")
#        sys.exit(1)
#
#    print(f"=== Evaluating: {filename} ===")
#
#    for stmt in statements:
#        line_no, action = stmt[0], stmt[1]

        try:
            if action == "ASSERT":
                expr = stmt[2]
                db_term = surface_to_debruijn(expr, env)
                evaluated = normalize(db_term)

                true_term = env.get("TRUE", env.get("⊤"))
                if not true_term or not db_equal(evaluated, true_term):
                    print(f"\n❌ ASSERTION FAILED at {filename}:{line_no}")
                    print(f"   Got: {debruijn_to_str(evaluated, declared_terms)}")
                    sys.exit(1)
                print(f"✓ ASSERTION PASSED (Line {line_no})")

            elif action == "ASSERT_EQ":
                left_ast, right_ast = stmt[2], stmt[3]
                red_left = normalize(surface_to_debruijn(left_ast, env))
                red_right = normalize(surface_to_debruijn(right_ast, env))

                if not db_equal(red_left, red_right):
                    print(f"\n❌ ASSERT_EQ FAILED at {filename}:{line_no}")
                    print(f"   Left:  {debruijn_to_str(red_left, declared_terms)}")
                    print(f"   Right: {debruijn_to_str(red_right, declared_terms)}")
                    sys.exit(1)
                print(f"✓ ASSERT_EQ PASSED (Line {line_no})")

            elif action == "ASSIGN":
                target, expr = stmt[2], stmt[3]
                db_term = surface_to_debruijn(expr, env)

                names_str = ", ".join(target)
                pretty = debruijn_to_str(db_term, declared_terms)
                print(f"{names_str} := {pretty}")

                for name in target:
                    env[name] = db_term
                    declared_terms[name] = db_term

            elif action == "EVAL":
                expr = stmt[2]
                db_term = surface_to_debruijn(expr, env)
                print(f"\nEval ({filename}:{line_no}): {debruijn_to_str(db_term, declared_terms)}")
                evaluated = normalize(db_term)
                print(f"Result → {debruijn_to_str(evaluated, declared_terms)}\n")

        except RecursionError:
            print(f"\n💥 CRASH: Maximum Recursion Depth Exceeded (Divergent Term?)")
            print(f" ➔ File: {filename}:{line_no}")
            print(f" ➔ Operation: {action}")
            sys.exit(1)
        except Exception as e:
            print(f"\n💥 CRASH: Unexpected Error: {e}")
            print(f" ➔ File: {filename}:{line_no}")
            print(f" ➔ Operation: {action}")
            sys.exit(1)

#if __name__ == "__main__":
#    if len(sys.argv) > 1:
#        combined_code = "" # FIXME erasing file info makes debugging difficult
#        for path in sys.argv[1:]:
#            with open(path, "r", encoding="utf-8") as f:
#                combined_code += f.read() + "\n"
#        execute_program(combined_code)
if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Maintain execution context across disparate files
        global_env: Dict[str, DBTerm] = {}
        global_declared: Dict[str, DBTerm] = {}

        for path in sys.argv[1:]:
            with open(path, "r", encoding="utf-8") as f:
                execute_program(path, f.read(), global_env, global_declared)
