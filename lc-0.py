#! /usr/bin/env python

import sys
from typing import Dict, List, Tuple
from lark import Lark, Transformer, v_args
from lambda_calculus import Variable, Abstraction, Application
from lambda_calculus.visitors.normalisation import BetaNormalisingVisitor

# =====================================================================
# Grammar Definition (Lark)
# =====================================================================

LC_GRAMMAR = r"""
    start: (_NEWLINE | statement)*

    statement: ident_list ASSIGN expr   -> assign
             | expr                     -> eval_expr

    ident_list: IDENT ("," IDENT)*

    ?expr: abstraction
         | application

    abstraction: LAMBDA IDENT+ DOT expr

    ?application: atom+

    ?atom: IDENT                 -> var
         | INT                   -> debruijn
         | STRING                -> string_lit
         | "(" expr ")"

    LAMBDA: "\\" | "λ"
    DOT: "."
    ASSIGN: ":="

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
    def __init__(self, param: str, body: AST):
        self.param = param
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
        
        for p in reversed(params):
            body = AbsAST(p, body)
        return body

    def application(self, *atoms):
        res = atoms[0]
        for arg in atoms[1:]:
            res = AppAST(res, arg)
        return res

    def var(self, name):
        return VarAST(str(name))

    def debruijn(self, val):
        return DeBruijnAST(int(val))

    def string_lit(self, val):
        return StringLitAST(str(val)[1:-1])


# =====================================================================
# Conversion & Evaluation
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
        param_name = node.param
        new_scope = scope + [param_name]
        body_lc = ast_to_lc(node.body, env, new_scope)
        return Abstraction(param_name, body_lc)

    elif isinstance(node, AppAST):
        fun_lc = ast_to_lc(node.fun, env, scope)
        arg_lc = ast_to_lc(node.arg, env, scope)
        return Application(fun_lc, arg_lc)


# =====================================================================
# Pretty Printing & Term Matching
# =====================================================================

def get_param_name(abs_term: Abstraction) -> str:
    if hasattr(abs_term, "parameter_name"):
        return abs_term.parameter_name
    elif hasattr(abs_term, "parameter"):
        return abs_term.parameter
    return str(getattr(abs_term, "name", "x"))

def get_abs_body(abs_term: Abstraction):
    if hasattr(abs_term, "body"):
        return abs_term.body
    elif hasattr(abs_term, "expression"):
        return abs_term.expression
    slots = getattr(type(abs_term), "__slots__", ())
    if len(slots) >= 2:
        return getattr(abs_term, slots[1])
    raise AttributeError("Cannot inspect Abstraction body.")

def get_app_terms(app_term: Application) -> Tuple[any, any]:
    if hasattr(app_term, "expression_1") and hasattr(app_term, "expression_2"):
        return app_term.expression_1, app_term.expression_2
    elif hasattr(app_term, "function") and hasattr(app_term, "argument"):
        return app_term.function, app_term.argument
    elif hasattr(app_term, "fun") and hasattr(app_term, "arg"):
        return app_term.fun, app_term.arg
        
    slots = getattr(type(app_term), "__slots__", ())
    if len(slots) >= 2:
        return getattr(app_term, slots[0]), getattr(app_term, slots[1])
        
    raise AttributeError("Cannot inspect Application subterms.")

def lc_to_str(term, parent_type=None) -> str:
    if isinstance(term, Variable):
        return getattr(term, "name", str(term))
        
    elif isinstance(term, Abstraction):
        params = [get_param_name(term)]
        body = get_abs_body(term)
        while isinstance(body, Abstraction):
            params.append(get_param_name(body))
            body = get_abs_body(body)
            
        param_str = " ".join(params)
        res = f"λ{param_str}.{lc_to_str(body)}"
        return f"({res})" if parent_type in (Application, "fun") else res
        
    elif isinstance(term, Application):
        fun, arg = get_app_terms(term)
        fun_str = lc_to_str(fun, "fun")
        arg_str = lc_to_str(arg, Application)
        res = f"{fun_str} {arg_str}"
        return f"({res})" if parent_type == Application else res
        
    return str(term)

def alpha_equal(t1, t2, env1=None, env2=None) -> bool:
    if env1 is None: env1 = {}
    if env2 is None: env2 = {}

    if type(t1) != type(t2):
        return False
        
    if isinstance(t1, Variable):
        name1 = getattr(t1, "name", str(t1))
        name2 = getattr(t2, "name", str(t2))
        v1 = env1.get(name1, name1)
        v2 = env2.get(name2, name2)
        return v1 == v2
        
    elif isinstance(t1, Abstraction):
        fresh_sym = object()
        p1 = get_param_name(t1)
        p2 = get_param_name(t2)
        new_env1 = {**env1, p1: fresh_sym}
        new_env2 = {**env2, p2: fresh_sym}
        return alpha_equal(get_abs_body(t1), get_abs_body(t2), new_env1, new_env2)
        
    elif isinstance(t1, Application):
        f1, a1 = get_app_terms(t1)
        f2, a2 = get_app_terms(t2)
        return alpha_equal(f1, f2, env1, env2) and alpha_equal(a1, a2, env1, env2)
                
    return False

def match_declared_aliases(term, declared_terms: Dict[str, any]) -> str:
    for name, decl_term in declared_terms.items():
        if alpha_equal(term, decl_term):
            return name
    return None


# =====================================================================
# Main Execution
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
    normalizer = BetaNormalisingVisitor()

    print("=== File Normalization & Output Execution ===")
#    for names_or_flag, ast in statements:
#        lc_term = ast_to_lc(ast, env)
#        evaluated_term = normalizer.skip_intermediate(lc_term)
#
#        if names_or_flag != "_":
#            for name in names_or_flag:
#                env[name] = lc_term
#                declared_terms[name] = evaluated_term
#            aliases_str = ", ".join(names_or_flag)
#            print(f"{aliases_str} := {lc_to_str(evaluated_term)}")
#        else:
#            alias = match_declared_aliases(evaluated_term, declared_terms)
#            formatted_str = lc_to_str(evaluated_term)
#            
#            if alias:
#                print(f"Eval: {formatted_str}  ==>  '{alias}'")
#            else:
#                print(f"Eval: {formatted_str}")
    for names_or_flag, ast in statements:
        lc_term = ast_to_lc(ast, env)
    
        if names_or_flag != "_":
            # Store un-normalized term in env; normalize only for display alias matching
            for name in names_or_flag:
                env[name] = lc_term
            
            # Optional: Print raw term or skip evaluation on infinite definitions
            aliases_str = ", ".join(names_or_flag)
            print(f"{aliases_str} := {lc_to_str(lc_term)}")
        else:
            # Only normalize during evaluation steps
            evaluated_term = normalizer.skip_intermediate(lc_term)
            alias = match_declared_aliases(evaluated_term, declared_terms)
            formatted_str = lc_to_str(evaluated_term)
            
            if alias:
                print(f"Eval: {formatted_str}  ==>  '{alias}'")
            else:
                print(f"Eval: {formatted_str}")
    
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python lc_interpreter.py <file1.lc> [file2.lc ...]")
        sys.exit(1)
    run_files(sys.argv[1:])
