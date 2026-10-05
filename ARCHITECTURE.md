# Repository Architecture & File Mapping

## Entry Points & Interpreter Pipeline

- **`lc`**: Shell wrapper installed to `/usr/local/bin/lc` that initializes `$HOME/venv` and executes `lc.py`.
- **`lc.py`**:
  - `LC_GRAMMAR`: Grammar definition supporting chained lambdas, De Bruijn terms (`[n]`), and colon namespaces.
  - `surface_to_debruijn()` & `db_substitute()`: AST transformation and index shifting engine.
  - `beta_reduce_step()` & `normalize()`: Evaluation loop with primitive effect execution.
  - `debruijn_to_str()`: Idempotent resugarer and term printer.
  - `analyze_complexity()`: Calculates node count, tree depth, Kolmogorov complexity approximation $K(x)$, and asymptotic runtime bounds.

## Standard Library Hierarchy (`stdlib.lc`)


```

stdlib.lc
├── 01_standard_terms.lc
├── 02_fol.lc (First-Order Logic)
├── 03_pair.lc
├── 04_church.lc (Church Numerals & Encodings)
├── 05_map_reduce.lc
├── 06_hol.lc (Higher-Order Logic)
├── 11_standard_terms.lc ... 16_hol.lc (Namespaced equivalents)
├── 21_ast.lc (Lambda AST in LC)
├── 22_eval.lc (Evaluator in LC)
├── 23_resugar.lc
├── 24_kolmogorov.lc
└── 25_bootstrap.lc

```

## System Primitives (`BUILTIN_TABLE`)

- **Filesystem & Stdio**: `PRINT`, `READ_LINE`, `OPEN`, `CLOSE`, `FD_READ`, `FD_WRITE`, `PIPE`, `DUP2`.
- **Process & OS**: `FORK`, `EXECVE`, `EXEC_CMD`.
- **Networking**: `SOCKET`, `BIND`, `LISTEN`, `ACCEPT`, `CONNECT`.
- **Graphics & Audio Engine**: `PAGE`, `LINE`, `ARC`, `INTERSECT`, `SEND_AUDIO`.

