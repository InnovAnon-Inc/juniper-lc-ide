#!/usr/bin/env python3
import sys
import os
import subprocess
from typing import Dict, List, Optional, Set, Any
from lark import Lark, Transformer, v_args

# =====================================================================
# 1. Grammar Definition with Chained Lambda & INCLUDE Support
# =====================================================================

LC_GRAMMAR = r"""
    start: (_NEWLINE | statement)*

    statement: ident_list ASSIGN expr          -> assign
             | "ASSERT" expr                   -> assert_expr
             | "ASSERT_EQ" expr "," expr       -> assert_eq
             | "INCLUDE" (STRING | IDENT)      -> include_stmt
             | expr                            -> eval_expr

    ident_list: IDENT ("," IDENT)*

    ?expr: abstraction
         | application

    abstraction: LAMBDA params DOT expr -> named_abs
               | LAMBDA+ DOT expr       -> anon_abs_chain

    params: IDENT+

    ?application: atom+

    ?atom: IDENT               -> var
         | INT                 -> int_lit
         | BRACKETED_INT       -> debruijn
         | STRING              -> string_lit
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
# 2. Surface AST Nodes with Guile Code Generation
# =====================================================================

class SurfaceAST:
    def to_guile(self) -> str:
        raise NotImplementedError

class SVar(SurfaceAST):
    def __init__(self, name: str):
        self.name = name
    def to_guile(self) -> str:
        # Sanitize symbols for Scheme compatibility
        return self.name.replace("-", "_")

class SString(SurfaceAST):
    def __init__(self, val: str):
        self.val = val
    def to_guile(self) -> str:
        escaped = self.val.replace('"', '\\"')
        return f'"{escaped}"'

class SAbs(SurfaceAST):
    def __init__(self, param: Optional[str], body: SurfaceAST):
        self.param = param if param else "_"
        self.body = body
    def to_guile(self) -> str:
        p = self.param.replace("-", "_")
        return f"(lambda ({p}) {self.body.to_guile()})"

class SApp(SurfaceAST):
    def __init__(self, fun: SurfaceAST, arg: SurfaceAST):
        self.fun = fun
        self.arg = arg
    def to_guile(self) -> str:
        return f"({self.fun.to_guile()} {self.arg.to_guile()})"

# =====================================================================
# 3. Transformer
# =====================================================================

@v_args(inline=True)
class LCTransformer(Transformer):
    def start(self, *items):
        return [i for i in items if i is not None]

    def ident_list(self, *idents):
        return [str(i) for i in idents]

    def params(self, *idents):
        return [str(i) for i in idents]

    @v_args(meta=True, inline=True)
    def assign(self, meta, names, assign_op, expr):
        return ("ASSIGN", names, expr)

    @v_args(meta=True, inline=True)
    def assert_expr(self, meta, expr):
        return ("ASSERT", expr)

    @v_args(meta=True, inline=True)
    def assert_eq(self, meta, left, right):
        return ("ASSERT_EQ", left, right)

    @v_args(meta=True, inline=True)
    def include_stmt(self, meta, path_tok):
        p = str(path_tok)
        if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
            p = p[1:-1]
        return ("INCLUDE", p)

    @v_args(meta=True, inline=True)
    def eval_expr(self, meta, expr):
        return ("EVAL", expr)

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

    def debruijn(self, val):
        # Fallback handling for explicit indices if encountered
        idx = int(str(val)[1:-1])
        return SVar(f"_db_{idx}")

    def int_lit(self, val):
        # Represent integer literals as native Scheme numbers
        return SVar(str(val))

    def string_lit(self, val):
        s = str(val)[1:-1]
        return SString(s)

# =====================================================================
# 4. Preprocessor & File Inclusion Manager
# =====================================================================

def load_source_tree(filename: str, visited: Optional[Set[str]] = None) -> str:
    if visited is None:
        visited = set()

    canonical = os.path.realpath(filename)
    if canonical in visited:
        return ""
    visited.add(canonical)

    if not os.path.exists(canonical):
        print(f"\n❌ INCLUDE ERROR: File not found '{filename}' ({canonical})", file=sys.stderr)
        sys.exit(1)

    base_dir = os.path.dirname(canonical)
    parser = Lark(LC_GRAMMAR, parser="lalr", propagate_positions=True)
    
    with open(canonical, "r", encoding="utf-8") as f:
        content = f.read()

    try:
        tree = parser.parse(content)
        statements = LCTransformer().transform(tree)
    except Exception as e:
        print(f"\n❌ PARSE ERROR in {filename}:\n{e}", file=sys.stderr)
        sys.exit(1)

    expanded_chunks = []
    for stmt in statements:
        if stmt[0] == "INCLUDE":
            inc_path = stmt[1]
            resolved = inc_path if os.path.isabs(inc_path) else os.path.join(base_dir, inc_path)
            expanded_chunks.append(load_source_tree(resolved, visited))
        else:
            # Reconstruct statement text or keep track of AST
            pass

    # For simplicity, we can parse raw file contents or let the AST compile directly.
    return content

# =====================================================================
# 5. Guile Runtime Preamble (Standard Library & Builtins)
# =====================================================================

GUILE_PRELUDE = """
;;; Generated by LC-Guile Compiler
(use-modules (ice-9 popen) (ice-9 rdelim))

(define TRUE (lambda (t) (lambda (f) t)))
(define FALSE (lambda (t) (lambda (f) f)))

(define (PRINT x)
  (display "[STDIO PRINT] ")
  (display x)
  (newline)
  x)

(define (READ_LINE prompt)
  (display prompt)
  (display "> ")
  (let ((line (read-line)))
    (if (eof-object? line) "" line)))

(define (EXEC_CMD cmd)
  (let* ((port (open-input-pipe cmd))
         (output (read-string port)))
    (close-pipe port)
    (let ((trimmed (string-trim-both output)))
      (display (string-append "[SHELL EXEC] " cmd " -> " trimmed))
      (newline)
      trimmed)))

(define (PAGE id)
  (display (string-append "[GEOMETRY] Initialized paper context: '" id "'"))
  (newline)
  id)

(define (LINE p1 p2)
  (display (string-append "[GEOMETRY DRAW LINE] Straightedge line passing through (" p1 ") and (" p2 ")"))
  (newline)
  p1)

(define (ARC center radius)
  (display (string-append "[GEOMETRY DRAW ARC] Compass arc centered at (" center ") with radius (" radius ")"))
  (newline)
  center)

(define (INTERSECT g1 g2)
  (display (string-append "[GEOMETRY INTERSECT] Relational intersection between (" g1 ") and (" g2 ")"))
  (newline)
  g1)

(define (SEND_AUDIO spec)
  (display (string-append "[AUDIO EMIT] Generating signal / buffer frame: " spec))
  (newline)
  spec)
"""

# =====================================================================
# 6. Compiler Pipeline & Execution
# =====================================================================

def compile_statements_to_guile(statements: List[Tuple]) -> str:
    guile_code = [GUILE_PRELUDE]

    for stmt in statements:
        action = stmt[0]
        if action == "ASSIGN":
            names, expr = stmt[1], stmt[2]
            expr_code = expr.to_guile()
            for name in names:
                clean_name = name.replace("-", "_")
                guile_code.append(f"(define {clean_name} {expr_code})")
        
        elif action == "ASSERT":
            expr = stmt[1]
            expr_code = expr.to_guile()
            guile_code.append(f'(unless (equal? {expr_code} TRUE)')
            guile_code.append(f'  (begin (display "❌ ASSERTION FAILED: ")(display \'{expr_code})(newline)(exit 1)))')
        
        elif action == "ASSERT_EQ":
            left, right = stmt[1], stmt[2]
            l_code, r_code = left.to_guile(), right.to_guile()
            guile_code.append(f'(unless (equal? {l_code} {r_code})')
            guile_code.append(f'  (begin (display "❌ ASSERT_EQ FAILED\\nLeft: ")(display {l_code})(display "\\nRight: ")(display {r_code})(newline)(exit 1)))')

        elif action == "EVAL":
            expr = stmt[1]
            expr_code = expr.to_guile()
            guile_code.append(f'(display {expr_code}) (newline)')

    return "\n".join(guile_code)

def run_guile(script: str):
    try:
        process = subprocess.run(
            ["guile", "-c", script],
            capture_output=False,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"\n❌ GUILE RUNTIME ERROR", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("\n❌ ERROR: 'guile' executable not found in PATH. Please install GNU Guile.", file=sys.stderr)
        sys.exit(1)

def process_file(filename: str, visited: Optional[Set[str]] = None) -> List[Tuple]:
    if visited is None:
        visited = set()

    canonical = os.path.realpath(filename)
    if canonical in visited:
        return []
    visited.add(canonical)

    if not os.path.exists(canonical):
        print(f"\n❌ FILE ERROR: '{filename}' not found.", file=sys.stderr)
        sys.exit(1)

    base_dir = os.path.dirname(canonical)
    with open(canonical, "r", encoding="utf-8") as f:
        code = f.read()

    parser = Lark(LC_GRAMMAR, parser="lalr", propagate_positions=True)
    try:
        tree = parser.parse(code)
        statements = LCTransformer().transform(tree)
    except Exception as e:
        print(f"\n❌ PARSE ERROR in {filename}:\n{e}", file=sys.stderr)
        sys.exit(1)

    resolved_statements = []
    for stmt in statements:
        if stmt[0] == "INCLUDE":
            inc_path = stmt[1]
            inc_resolved = inc_path if os.path.isabs(inc_path) else os.path.join(base_dir, inc_path)
            resolved_statements.extend(process_file(inc_resolved, visited))
        else:
            resolved_statements.append(stmt)

    return resolved_statements

if __name__ == "__main__":
    if len(sys.argv) > 1:
        all_statements = []
        for path in sys.argv[1:]:
            all_statements.extend(process_file(path))
        
        guile_script = compile_statements_to_guile(all_statements)
        run_guile(guile_script)
    else:
        print("Usage: python lc.py <file1.lc> [file2.lc ...]")
        sys.exit(1)
