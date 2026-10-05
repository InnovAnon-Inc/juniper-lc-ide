Provides the top-level vision, runtime execution instructions, and language syntax conventions.

# Juniper Lambda Calculus (Juniper-LC)

A pure, self-hosting De Bruijn lambda calculus language, interpreter, and mathematical framework designed for ubiquitous execution—from terminal shells to web apps, kernel space, UEFI/BIOS environments, and physical Turing books.

## Execution & Runtime Setup

The interpreter environment routes `.lc` files via shebang to `/usr/local/bin/lc`, executing inside a dedicated Python virtual environment (`$HOME/venv`):

```bash
# Execute standard library assertions & proofs
./stdlib.lc

# Execute top-level entry point
./juniper.lc

```

## Language Syntax Conventions

* **Lambda Abstractions**: Uses `\` or `λ` (e.g., `λs elem. s elem`).

* **Symbol Binding**: Uses `:=` for original definitions and `≡` for redefinitions / beta-equivalence assertions.

* **Namespacing**: Supports colon-namespaced symbol imports (e.g., `INCLUDE "server.lc" AS s` creates `s:term`).

* **System & Hardware Primitives**: Represented in ALL_CAPS (`PRINT`, `SOCKET`, `EXECVE`, `PIPE`, `PAGE`, `LINE`, `SEND_AUDIO`).

* **Set Theory & Logic Symbols**: Native Unicode symbols (`∈`, `∪`, `∩`, `∖`, `∧`, `∨`, `¬`, `⊤`).



## System Architecture

1. **`lc.py`**: Reference interpreter in Python featuring Lark LALR parsing, native De Bruijn index manipulation (`[0]`, `[1]`), beta reduction, complexity calculation ($K(x)$, time/space), and resugaring.

2. **`stdlib.lc`**: Core standard library covering standard terms, first-order logic (FOL), Church encodings, pair structures, map-reduce, higher-order logic (HOL), AST definitions, and evaluation routines.

3. **`juniper.lc`**: Main executable wrapper importing `stdlib.lc` and server bindings.

4. **`lc.lc` (Target)**: Pure lambda calculus self-hosting compiler meant to replace `lc.py`.

