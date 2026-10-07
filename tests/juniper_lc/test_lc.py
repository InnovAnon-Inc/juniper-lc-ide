import pytest
import sys
from juniper_lc.lc import (
    DBVar,
    DBAbs,
    DBApp,
    DBBuiltin,
    SVar,
    SDBVar,
    SAbs,
    SApp,
    shift,
    db_substitute,
    db_equal,
    try_decode_church,
    debruijn_to_str,
    surface_to_debruijn,
    normalize,
    preprocess_source,
    execute_program,
    MODULE_EXPORTS_CACHE,
    GRAPHICS_STATE,
    LC_GRAMMAR,
    LCTransformer,
)
from lark import Lark


@pytest.fixture(autouse=True)
def reset_global_state():
    """Resets global cache and graphics state between test runs."""
    MODULE_EXPORTS_CACHE.clear()
    GRAPHICS_STATE["papers"] = {}
    yield
    MODULE_EXPORTS_CACHE.clear()
    GRAPHICS_STATE["papers"] = {}


# =====================================================================
# 1. De Bruijn Arithmetic & AST Manipulation Tests
# =====================================================================

class TestDeBruijnCore:
    def test_db_equal_identical(self):
        t1 = DBAbs(DBApp(DBVar(0), DBVar(1)))
        t2 = DBAbs(DBApp(DBVar(0), DBVar(1)))
        assert db_equal(t1, t2) is True

    def test_db_equal_distinct(self):
        t1 = DBAbs(DBVar(0))
        t2 = DBAbs(DBVar(1))
        assert db_equal(t1, t2) is False

    def test_shift_variable(self):
        var = DBVar(0)
        assert shift(var, 2, cutoff=0).index == 2
        assert shift(var, 2, cutoff=1).index == 0

    def test_shift_abs(self):
        # \. [0] [1] -> shifted cutoff increases inside abstraction
        term = DBAbs(DBApp(DBVar(0), DBVar(1)))
        shifted = shift(term, 1, cutoff=0)
        assert isinstance(shifted, DBAbs)
        assert shifted.body.fun.index == 0  # Below cutoff (0 < 1)
        assert shifted.body.arg.index == 2  # Shifted (1 >= 1 -> 2)

    def test_db_substitute_basic(self):
        # Substitute [0] with [5] in ([0] [1])
        term = DBApp(DBVar(0), DBVar(1))
        substituted = db_substitute(term, DBVar(5), index=0)
        assert substituted.fun.index == 5
        assert substituted.arg.index == 0  # Indices > 0 decrement by 1

    def test_db_substitute_under_abs(self):
        # (\. [1]) applied to [5] -> [1] index 1 maps to target index 0 inside DBAbs body
        term = DBAbs(DBVar(1))
        substituted = db_substitute(term.body, DBVar(5), index=0)
        assert substituted.index == 5


# =====================================================================
# 2. Parsing, Preprocessing & Surface Transformer Tests
# =====================================================================

class TestParsingAndAST:
    def test_preprocess_source_line_continuation(self):
        raw_code = "ID := \\x.\\\n  x\n# comment line\n"
        processed = preprocess_source(raw_code)
        assert "#" not in processed
        assert "ID := \\x. x" in processed or "ID := \\x.  x" in processed

    def test_surface_to_debruijn_identity(self):
        # Identity function \x. x -> DBAbs(DBVar(0))
        s_ast = SAbs("x", SVar("x"))
        db_ast = surface_to_debruijn(s_ast, env={})
        assert isinstance(db_ast, DBAbs)
        assert isinstance(db_ast.body, DBVar)
        assert db_ast.body.index == 0

    def test_surface_to_debruijn_church_int(self):
        parser = Lark(LC_GRAMMAR, parser="lalr")
        tree = parser.parse("2")
        s_ast = LCTransformer().transform(tree)[0][2]
        db_ast = surface_to_debruijn(s_ast, env={})
        
        # Church 2: \f. \x. f (f x)
        assert isinstance(db_ast, DBAbs)
        assert isinstance(db_ast.body, DBAbs)
        assert try_decode_church(db_ast) == 2


# =====================================================================
# 3. Normalization & Beta Reduction Tests
# =====================================================================

class TestNormalization:
    def test_identity_application(self):
        # (\x. x) y -> y
        id_fun = DBAbs(DBVar(0))
        arg = DBVar(10)
        app = DBApp(id_fun, arg)
        normalized = normalize(app)
        assert isinstance(normalized, DBVar)
        assert normalized.index == 10

    def test_church_addition_execution(self):
        code = """
        PLUS := \\m n f x. m f (n f x)
        TWO := 2
        THREE := 3
        FIVE := PLUS TWO THREE
        ASSERT_EQ FIVE, 5
        """
        env, declared = {}, {}
        execute_program("<test>", code, env, declared, quiet=True)
        assert "FIVE" in declared
        assert try_decode_church(normalize(declared["FIVE"])) == 5


# =====================================================================
# 4. Resugaring & Formatting Tests
# =====================================================================

class TestResugaring:
    def test_decode_church_numeral(self):
        church_0 = DBAbs(DBAbs(DBVar(0)))
        church_1 = DBAbs(DBAbs(DBApp(DBVar(1), DBVar(0))))
        assert try_decode_church(church_0) == 0
        assert try_decode_church(church_1) == 1

    def test_debruijn_to_str_symbol_preservation(self):
        declared = {}
        env = {}
        code = "ID := \\x. x\n"
        execute_program("<test>", code, env, declared, quiet=True)
        
        # Checking that declared symbols are resugared back to their identifiers
        resugared = debruijn_to_str(declared["ID"], declared)
        assert resugared == "ID"


# =====================================================================
# 5. Program Execution & Statement Tests
# =====================================================================

class TestProgramExecution:
    def test_assign_and_eval(self):
        code = """
        I := \\x. x
        K := \\x y. x
        I K
        """
        env, declared = {}, {}
        outputs, env, declared = execute_program("<test>", code, env, declared, quiet=True)
        assert "I" in declared
        assert "K" in declared
        assert outputs[-1] == "K"

    def test_assert_pass(self):
        code = """
        TRUE := \\x y. x
        ASSERT TRUE
        """
        env, declared = {}, {}
        outputs, env, declared = execute_program("<test>", code, env, declared, quiet=True)
