#! /usr/bin/env python

import sys
from typing import Dict, List, Tuple, Optional
from lark import Lark, Transformer, v_args
from lambda_calculus import Variable, Abstraction, Application

# =====================================================================
# Grammar Definition (Supports Bracketed De Bruijn: [0], [1])
# =====================================================================

LC_GRAMMAR = r"""
    start: (_NEWLINE | statement)*

    statement: ident_list ASSIGN expr   -> assign
             | expr                     -> eval_expr

    ident_list: IDENT ("," IDENT)*

    ?expr: abstraction
         | application

    abstraction: LAMBDA IDENT* DOT expr

    ?application: atom+

    ?atom: IDENT                 -> var
         | BRACKETED_INT         -> debruijn
         | STRING                -> string_lit
         | "(" expr ")"

    LAMBDA: "\\" | "λ"
    DOT: "."
    ASSIGN: ":="
    BRACKETED_INT: "\[" INT "\]"

    IDENT: /(?!(?::=|\.|\(|\))\b)(?![\\λ])[+\-*\/<>=!&|~%^\w\u0080-\u00FF\u2190-\u21FF\u2200-\u22FF\u27C0-\u27EF\u2980-\u29FF\u2A00-\u2AFF]+/
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
# AST Nodes
# =====================================================================

class AST: pass

class VarAST(AST):
    def __init__(self, name: str):
        self.name = name

class DeBruijnAST(AST):
    def __init__(self, index: int):
        self.index = index

class AbsAST(AST):
    def __init__(self, params: List[str], body: AST):
        self.params = params
        self.body = body

class AppAST(AST):
    def __init__(self, fun: AST, arg: AST):
        self.fun = fun
        self.arg = arg

class StringLitAST(AST):
    def __init__(self, val: str):
        self.val = val


# =====================================================================
# Lark AST Transformer
# =====================================================================

@v_args(inline=True)
class LCTransformer(Transformer):
    def start(self, *items):
        return [item for item in items if item is not None]

    def ident_list(self, *idents):
        return [str(i) for i in idents]

    def assign(self, names, assign_op, expr):
        return (names, expr)

    def eval_expr(self, expr):
        return ("_", expr)

    def abstraction(self, lambda_tok, *args):
        params = [str(p) for p in args[:-1]]
        body = args[-1]
        return AbsAST(params, body)

    def application(self, *atoms):
        res = atoms[0]
        for arg in atoms[1:]:
            res = AppAST(res, arg)
        return res

    def var(self, name):
        return VarAST(str(name))

    def debruijn(self, val):
        # Strip outer '[' and ']'
        idx = int(str(val)[1:-1])
        return DeBruijnAST(idx)

    def string_lit(self, val):
        return StringLitAST(str(val)[1:-1])


# =====================================================================
# AST Conversion
# =====================================================================

def make_church_numeral(n: int):
    body = Variable("x")
    for _ in range(n):
        body = Application(Variable("f"), body)
    return Abstraction("f", Abstraction("x", body))

def ast_to_lc(node: AST, env: Dict[str, any], scope: List[str] = None):
    if scope is None:
        scope = []

    if isinstance(node, VarAST):
        for var_name in reversed(scope):
            if node.name == var_name:
                return Variable(node.name)
        if node.name in env:
            return env[node.name]
        return Variable(node.name)

    elif isinstance(node, DeBruijnAST):
        if node.index < len(scope):
            var_name = scope[len(scope) - 1 - node.index]
            return Variable(var_name)
        else:
            return Variable(f"_{node.index}")

    elif isinstance(node, StringLitAST):
        if node.val.isdigit():
            return make_church_numeral(int(node.val))
        return Variable(node.val)

    elif isinstance(node, AbsAST):
        if not node.params:
            param_name = f"_{len(scope)}"
            new_scope = scope + [param_name]
            body_lc = ast_to_lc(node.body, env, new_scope)
            return Abstraction(param_name, body_lc)
        else:
            p = node.params[0]
            new_scope = scope + [p]
            if len(node.params) > 1:
                body_lc = ast_to_lc(AbsAST(node.params[1:], node.body), env, new_scope)
            else:
                body_lc = ast_to_lc(node.body, env, new_scope)
            return Abstraction(p, body_lc)

    elif isinstance(node, AppAST):
        fun_lc = ast_to_lc(node.fun, env, scope)
        arg_lc = ast_to_lc(node.arg, env, scope)
        return Application(fun_lc, arg_lc)


# =====================================================================
# Graph Reduction Engine (Call-by-Need / Wadsworth-style)
# =====================================================================

class Node:
    """Graph Heap Node to support shared evaluation (call-by-need)."""
    def __init__(self, term):
        self.term = term

def substitute_graph(term, var_name: str, shared_node: Node):
    """Replaces occurrences of var_name with a shared pointer node."""
    if isinstance(term, Variable):
        return shared_node if getattr(term, "name", str(term)) == var_name else term
    elif isinstance(term, Node):
        return term
    elif isinstance(term, Abstraction):
        param = get_param_name(term)
        if param == var_name:
            return term
        return Abstraction(param, substitute_graph(get_abs_body(term), var_name, shared_node))
    elif isinstance(term, Application):
        f, a = get_app_terms(term)
        return Application(
            substitute_graph(f, var_name, shared_node),
            substitute_graph(a, var_name, shared_node)
        )
    return term

def reduce_graph(node: Node, depth=0, max_depth=2000) -> any:
    """Evaluates graph nodes using outer reduction with argument sharing."""
    if depth > max_depth:
        raise RecursionError("Max evaluation depth reached.")

    term = node.term

    while isinstance(term, Node):
        node = term
        term = node.term

    if isinstance(term, (Variable, Abstraction)):
        return term

    elif isinstance(term, Application):
        fun, arg = get_app_terms(term)

        # 1. Outer reduction on function position
        fun_val = reduce_graph(Node(fun), depth + 1, max_depth)

        if isinstance(fun_val, Abstraction):
            param = get_param_name(fun_val)
            body = get_abs_body(fun_val)

            # 2. Wrap argument in single shared node (Lazy memoization pointer)
            arg_node = arg if isinstance(arg, Node) else Node(arg)
            substituted = substitute_graph(body, param, arg_node)

            # Update heap node and reduce recursively
            node.term = substituted
            return reduce_graph(node, depth + 1, max_depth)

        node.term = Application(fun_val, arg)
        return node.term

    return term

# Helper to unwrap Node graph back to pure Lambda Calculus terms
def unwrap_graph(term):
    if isinstance(term, Node):
        return unwrap_graph(term.term)
    elif isinstance(term, Abstraction):
        return Abstraction(get_param_name(term), unwrap_graph(get_abs_body(term)))
    elif isinstance(term, Application):
        f, a = get_app_terms(term)
        return Application(unwrap_graph(f), unwrap_graph(a))
    return term


# =====================================================================
# Alpha Equivalence & Inspection
# =====================================================================

def get_param_name(abs_term: Abstraction) -> str:
    if hasattr(abs_term, "parameter_name"): return abs_term.parameter_name
    if hasattr(abs_term, "parameter"): return abs_term.parameter
    return str(getattr(abs_term, "name", "x"))

def get_abs_body(abs_term: Abstraction):
    if hasattr(abs_term, "body"): return abs_term.body
    if hasattr(abs_term, "expression"): return abs_term.expression
    slots = getattr(type(abs_term), "__slots__", ())
    return getattr(abs_term, slots[1]) if len(slots) >= 2 else None

def get_app_terms(app_term: Application) -> Tuple[any, any]:
    if hasattr(app_term, "expression_1"): return app_term.expression_1, app_term.expression_2
    if hasattr(app_term, "function"): return app_term.function, app_term.argument
    if hasattr(app_term, "fun"): return app_term.fun, app_term.arg
    slots = getattr(type(app_term), "__slots__", ())
    return getattr(app_term, slots[0]), getattr(app_term, slots[1])

def alpha_equal(t1, t2, env1=None, env2=None) -> bool:
    t1 = unwrap_graph(t1)
    t2 = unwrap_graph(t2)
    if env1 is None: env1 = {}
    if env2 is None: env2 = {}
    if type(t1) != type(t2): return False

    if isinstance(t1, Variable):
        v1 = env1.get(getattr(t1, "name", str(t1)), getattr(t1, "name", str(t1)))
        v2 = env2.get(getattr(t2, "name", str(t2)), getattr(t2, "name", str(t2)))
        return v1 == v2
    elif isinstance(t1, Abstraction):
        fresh = object()
        p1, p2 = get_param_name(t1), get_param_name(t2)
        return alpha_equal(get_abs_body(t1), get_abs_body(t2), {**env1, p1: fresh}, {**env2, p2: fresh})
    elif isinstance(t1, Application):
        f1, a1 = get_app_terms(t1)
        f2, a2 = get_app_terms(t2)
        return alpha_equal(f1, f2, env1, env2) and alpha_equal(a1, a2, env1, env2)

    return False


# =====================================================================
# Pretty Formatting Engine
# =====================================================================

def match_alias(term, declared_terms: Dict[str, any]) -> Optional[str]:
    for name, decl_term in declared_terms.items():
        if alpha_equal(term, decl_term):
            return name
    return None

def lc_to_str_sugared(term, declared_terms: Dict[str, any], parent_type=None) -> str:
    term = unwrap_graph(term)
    alias = match_alias(term, declared_terms)
    if alias:
        return alias

    if isinstance(term, Variable):
        return getattr(term, "name", str(term))

    elif isinstance(term, Abstraction):
        params = [get_param_name(term)]
        body = get_abs_body(term)

        while isinstance(body, Abstraction) and not match_alias(body, declared_terms):
            params.append(get_param_name(body))
            body = get_abs_body(body)

        param_str = " ".join(params)
        body_str = lc_to_str_sugared(body, declared_terms)
        res = f"λ{param_str}.{body_str}"
        return f"({res})" if parent_type in (Application, "fun") else res

    elif isinstance(term, Application):
        fun, arg = get_app_terms(term)
        fun_str = lc_to_str_sugared(fun, declared_terms, "fun")
        arg_str = lc_to_str_sugared(arg, declared_terms, Application)
        res = f"{fun_str} {arg_str}"
        return f"({res})" if parent_type == Application else res

    return str(term)


# =====================================================================
# Main Interpreter Loop
# =====================================================================

def run_files(file_paths: List[str]):
    combined_code = ""
    for path in file_paths:
        with open(path, "r", encoding="utf-8") as f:
            combined_code += f.read() + "\n"

    parser = Lark(LC_GRAMMAR, parser="lalr", transformer=LCTransformer())
    statements = parser.parse(combined_code)

    env = {}
    declared_terms = {}

    print("=== Pure Graph Reduction Engine ===")
    for names_or_flag, ast in statements:
        lc_term = ast_to_lc(ast, env)

        if names_or_flag != "_":
            norm_term = unwrap_graph(reduce_graph(Node(lc_term)))
            for name in names_or_flag:
                env[name] = lc_term
                declared_terms[name] = norm_term

            aliases_str = ", ".join(names_or_flag)
            pretty_raw = lc_to_str_sugared(lc_term, {})
            print(f"{aliases_str} := {pretty_raw}")
        else:
            evaluated_term = unwrap_graph(reduce_graph(Node(lc_term)))
            formatted_str = lc_to_str_sugared(evaluated_term, declared_terms)
            print(f"Eval: {formatted_str}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python lc_interpreter.py <file1.lc> [file2.lc ...]")
        sys.exit(1)
    run_files(sys.argv[1:])
