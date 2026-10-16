# Juniper Lambda Calculus (`juniper-lc`): Grammar & Syntax Specification

This document defines the formal LALR grammar rules implemented in `lc.py` for parsing Juniper Lambda Calculus source files (`.lc`).

---

## 1. Top-Level Program Structure (`start`)

A program consists of zero or more statements separated or preceded by newlines.

```ebnf
start: (_NEWLINE | statement)*

```

* **Comments**: Any text following `#` on a line is treated as a comment and ignored by the parser.


* **Line Continuations**: Backslashes immediately preceding a newline (`\`) are ignored, allowing multi-line statement wrapping.



---

## 2. Statement Rules

Statements drive variable bindings, module inclusion, proof assertions, and direct term evaluation.

```ebnf
statement: ident_list _ASSIGN expr          -> assign
         | ident_list _REDEFINE expr        -> redefine
         | _ASSERT expr                   -> assert_expr
         | _ASSERT_EQ expr _COMMA expr    -> assert_eq
         | _INCLUDE (STRING | IDENT) (_AS IDENT)? -> include_stmt
         | expr                            -> eval_expr

ident_list: IDENT (_COMMA IDENT)*

```

* **Assignment (`:=`)**: Binds one or more identifiers to a evaluated lambda term for the first time. Raises an error if the identifier is already defined.


* **Redefinition (`≡`)**: Explicitly overrides an existing symbol or asserts beta-equivalence.


* **Assertions (`ASSERT` / `ASSERT_EQ`)**: Validates that an expression evaluates to truth (`TRUE` / `⊤`) or that two expressions are equal.


* **Module Inclusion (`INCLUDE`)**: Imports definitions from another `.lc` file, optionally binding them under a colon namespace alias using `AS`.


* **Expression Evaluation (`eval_expr`)**: Evaluates a standalone term and prints its normalized form along with complexity metrics.



---

## 3. Abstraction Rules (`abstraction`)

Lambda abstractions support both named parameter lists and anonymous multi-abstraction chains.

```ebnf
?expr: abstraction
     | application

abstraction: LAMBDA params DOT expr -> named_abs
               | LAMBDA+ DOT expr       -> anon_abs_chain

params: IDENT+

```

* **Symbols**: Lambda abstractions may use either the ASCII backslash (`\`) or the Unicode lambda symbol (`λ`).


* **Named Abstraction**: `\x y. x y` or `λx y. x y` binds parameters sequentially from left to right.


* **Anonymous Abstraction Chain**: `\ . expr` or `λ . expr` creates anonymous nested abstractions.


* **Dot Separator**: Abstraction parameters are terminated by a dot (`.`).



---

## 4. Application & Atom Rules

Function applications are space-separated sequences of atoms.

```ebnf
?application: atom+

?atom: IDENT               -> var
     | INT                 -> int_lit
     | BRACKETED_INT       -> debruijn
     | STRING              -> string_lit
     | "(" expr ")"

```

* **Application**: Expressions like `f x y` associate left-to-right as `(f x) y`.


* **Variables (`IDENT`)**: References to bound variables, free variables, or built-in system primitives.


* **Integer Literals (`INT`)**: Standard integers (e.g., `3`) automatically desugar into their Church numeral representation (`\f x. f (f (f x))`).


* **De Bruijn Indices (`BRACKETED_INT`)**: Explicit De Bruijn index notation wrapped in brackets (e.g., `[0]`, `[1]`).


* **String Literals (`STRING`)**: Quoted strings (e.g., `"path/to/file"`), where numeric strings may also convert to Church numerals.


* **Parentheses**: Used to explicitly override application precedence: `(expr)`.



---

## 5. Lexical Tokens & Identifiers

```ebnf
    LAMBDA: "\\" | "λ"
    DOT: "."
    _ASSIGN: ":="
    _REDEFINE: "≡"
    _ASSERT: "ASSERT"
    _ASSERT_EQ: "ASSERT_EQ"
    _INCLUDE: "INCLUDE"
    _AS: "AS"
    _COMMA: ","
    BRACKETED_INT: /\[\d+\]/

    # Identifiers exclude reserved language operators and support colons/hyphens
    IDENT: /(?!(?::=|≡|\.|\(|\)))(?![\\λ])[-+*\/<>=!&|~%^:\w\u0080-\uFFFF]+/

```

* **Namespacing Colon Support**: The `IDENT` regex permits colons (`:`) internally, enabling namespaced symbol lookups (e.g., `s:term`) while correctly distinguishing assignment operators (`:=`).


* **Operator Symbols**: Common arithmetic and logic symbols (`+`, `-`, `*`, `/`, `<`, `>`, `=`, `!`, `&`, `|`, `~`, `%`, `^`) are valid constituents of identifiers unless tied to core grammar keywords.
