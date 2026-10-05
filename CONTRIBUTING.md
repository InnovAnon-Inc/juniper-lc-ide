# Developer & Agent Directives

## Code Conventions for `.lc` Files

1. **Prefer Unicode**: Use specialized Unicode symbols wherever available (`λ`, `≡`, `:=`, `∈`, `∪`, `∩`, `∖`) over ASCII equivalents.
2. **Builtin Naming**: Keep hardware and system primitives in ALL_CAPS to distinguish them from lambda terms.
3. **Assertions**: Every new module or primitive addition must include explicit `ASSERT` or `ASSERT_EQ` statements to verify correctness.
4. **Structured Comments**: Annotate complex terms with Kolmogorov complexity $K(x)$ and asymptotic bounds.

## Guidelines for `lc.py` Modifications

- Modify `lc.py` only when expanding system primitives in `BUILTIN_TABLE`, updating De Bruijn index shifting/substitution logic, or adding resugaring rules.
- Do not perform full rewrites of `lc.py`; extend existing AST transformers (`LCTransformer`) and builtin execution handlers (`execute_builtin_effect`).
- Preserve De Bruijn indexing invariants during AST transformations.

## Resugaring & Visual Representation Rules

- **Symbol Matching**: Resugar normalized terms against declared names in the environment (e.g., resugaring `λa b. b` to `FALSE` or `λ. I`).
- **No Over-Expansion**: Avoid resugaring or expanding internal definitions for basic application terms (e.g., `PLUS ONE ONE` must render as three inscribed terms, not unrolled lambda expressions).
- **Visual IDE / Bubble Notation**: Render application arguments clockwise in visual bubble AST output.

## Verification & Divergence Testing

- Always run script executions with a safety timeout to capture divergent (non-terminating) beta reductions:
  ```bash
  timeout 300s lc stdlib.lc

  ```

* Exit code `124` indicates term divergence. Investigate non-terminating recursion loops if encountered.

