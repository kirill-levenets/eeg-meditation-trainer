import math
import unittest

from app.metrics.custom_formula import CustomFormulaEvaluator


class TestFormulaValidation(unittest.TestCase):
    """Test formula parsing and validation."""

    def setUp(self):
        self.ev = CustomFormulaEvaluator()

    def test_empty_formula_is_valid(self):
        ok, err = self.ev.set_formula("")
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertFalse(self.ev.is_valid)

    def test_whitespace_only_treated_as_empty(self):
        ok, _ = self.ev.set_formula("   ")
        self.assertTrue(ok)
        self.assertFalse(self.ev.is_valid)

    def test_simple_variable(self):
        ok, _ = self.ev.set_formula("alpha1")
        self.assertTrue(ok)
        self.assertTrue(self.ev.is_valid)

    def test_arithmetic_expression(self):
        ok, _ = self.ev.set_formula("(alpha1 + alpha2) / (beta1 + beta2 + 1)")
        self.assertTrue(ok)

    def test_function_call(self):
        ok, _ = self.ev.set_formula("sqrt(alpha_norm) * 100")
        self.assertTrue(ok)

    def test_conditional_expression(self):
        ok, _ = self.ev.set_formula("alpha1 if alpha1 > beta1 else beta1")
        self.assertTrue(ok)

    def test_comparison_operators(self):
        for op in ["<", "<=", ">", ">=", "==", "!="]:
            ok, _ = self.ev.set_formula(f"1.0 if alpha1 {op} beta1 else 0.0")
            self.assertTrue(ok, f"Comparison {op} should be valid")

    def test_all_allowed_variables(self):
        variables = [
            "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2",
            "theta", "delta", "alpha", "beta", "gamma",
            "alpha_norm", "beta_norm", "gamma_norm", "theta_norm", "delta_norm",
            "total_power", "meditation_score", "shamatha_score",
            "distraction", "sinking", "subtle_distraction",
            "stability", "calmness", "native_attention", "native_meditation",
        ]
        for var in variables:
            ok, err = self.ev.set_formula(var)
            self.assertTrue(ok, f"Variable '{var}' should be valid: {err}")

    def test_all_allowed_functions(self):
        funcs = [
            "sqrt(alpha1)", "abs(alpha1)", "log(alpha1 + 1)",
            "log10(alpha1 + 1)", "log2(alpha1 + 1)", "exp(alpha_norm)",
            "pow(alpha1, 2)", "min(alpha1, beta1)", "max(alpha1, beta1)",
            "sin(alpha_norm)", "cos(alpha_norm)", "tanh(alpha_norm)",
        ]
        for f in funcs:
            ok, err = self.ev.set_formula(f)
            self.assertTrue(ok, f"Function call '{f}' should be valid: {err}")

    def test_nested_functions(self):
        ok, _ = self.ev.set_formula("sqrt(abs(log(alpha1 + 1)))")
        self.assertTrue(ok)

    def test_unary_operators(self):
        ok, _ = self.ev.set_formula("-alpha1")
        self.assertTrue(ok)
        ok, _ = self.ev.set_formula("+alpha1")
        self.assertTrue(ok)

    def test_floor_division_and_modulo(self):
        ok, _ = self.ev.set_formula("alpha1 // 100")
        self.assertTrue(ok)
        ok, _ = self.ev.set_formula("alpha1 % 10")
        self.assertTrue(ok)

    def test_formula_property(self):
        self.ev.set_formula("alpha1 + beta1")
        self.assertEqual(self.ev.formula, "alpha1 + beta1")


class TestFormulaRejection(unittest.TestCase):
    """Test that invalid formulas are properly rejected."""

    def setUp(self):
        self.ev = CustomFormulaEvaluator()

    def test_syntax_error(self):
        ok, err = self.ev.set_formula("alpha1 +")
        self.assertFalse(ok)
        self.assertIn("Syntax", err)

    def test_import_statement(self):
        ok, err = self.ev.set_formula("import os")
        self.assertFalse(ok)

    def test_dunder_import(self):
        ok, err = self.ev.set_formula("__import__('os')")
        self.assertFalse(ok)
        self.assertIn("Unknown function", err)

    def test_unknown_variable(self):
        ok, err = self.ev.set_formula("foobar")
        self.assertFalse(ok)
        self.assertIn("Unknown variable", err)

    def test_unknown_function(self):
        ok, err = self.ev.set_formula("eval('1')")
        self.assertFalse(ok)
        self.assertIn("Unknown function", err)

    def test_string_constant(self):
        ok, err = self.ev.set_formula("'hello'")
        self.assertFalse(ok)
        self.assertIn("Unsupported constant", err)

    def test_keyword_arguments(self):
        ok, err = self.ev.set_formula("pow(alpha1, n=2)")
        self.assertFalse(ok)
        self.assertIn("Keyword", err)

    def test_attribute_access(self):
        ok, err = self.ev.set_formula("alpha1.__class__")
        self.assertFalse(ok)

    def test_formula_too_long(self):
        ok, err = self.ev.set_formula("alpha1 + " * 100)
        self.assertFalse(ok)
        self.assertIn("too long", err)

    def test_last_error_persists(self):
        self.ev.set_formula("unknown_var")
        self.assertIn("Unknown variable", self.ev.last_error)

    def test_last_error_clears_on_success(self):
        self.ev.set_formula("unknown_var")
        self.ev.set_formula("alpha1")
        self.assertEqual(self.ev.last_error, "")


class TestFormulaEvaluation(unittest.TestCase):
    """Test formula evaluation with known variable values."""

    def setUp(self):
        self.ev = CustomFormulaEvaluator()
        self.vars = {
            "alpha1": 70000.0, "alpha2": 30000.0,
            "beta1": 10000.0, "beta2": 12000.0,
            "gamma1": 3000.0, "gamma2": 2000.0,
            "theta": 8000.0, "delta": 11000.0,
            "alpha": 100000.0, "beta": 22000.0, "gamma": 5000.0,
            "alpha_norm": 0.45, "beta_norm": 0.15, "gamma_norm": 0.05,
            "theta_norm": 0.10, "delta_norm": 0.25,
            "total_power": 146000.0,
            "meditation_score": 65.0, "shamatha_score": 42.0,
            "distraction": 30.0, "sinking": 20.0,
            "subtle_distraction": 5.0, "stability": 3.5, "calmness": 2.8,
            "native_attention": 55.0, "native_meditation": 60.0,
        }

    def test_single_variable(self):
        self.ev.set_formula("alpha1")
        self.assertAlmostEqual(self.ev.evaluate(self.vars), 70000.0)

    def test_addition(self):
        self.ev.set_formula("alpha1 + alpha2")
        self.assertAlmostEqual(self.ev.evaluate(self.vars), 100000.0)

    def test_division(self):
        self.ev.set_formula("(alpha1 + alpha2) / (beta1 + beta2 + 1)")
        expected = 100000.0 / 22001.0
        self.assertAlmostEqual(self.ev.evaluate(self.vars), expected, places=2)

    def test_sqrt_function(self):
        self.ev.set_formula("sqrt(alpha_norm) * 100")
        expected = math.sqrt(0.45) * 100
        self.assertAlmostEqual(self.ev.evaluate(self.vars), expected, places=2)

    def test_log_function(self):
        self.ev.set_formula("log(total_power + 1)")
        expected = math.log(146001.0)
        self.assertAlmostEqual(self.ev.evaluate(self.vars), expected, places=2)

    def test_weighted_blend(self):
        self.ev.set_formula("meditation_score * 0.7 + shamatha_score * 0.3")
        expected = 65.0 * 0.7 + 42.0 * 0.3
        self.assertAlmostEqual(self.ev.evaluate(self.vars), expected, places=2)

    def test_max_function(self):
        self.ev.set_formula("max(meditation_score, shamatha_score)")
        self.assertAlmostEqual(self.ev.evaluate(self.vars), 65.0)

    def test_min_function(self):
        self.ev.set_formula("min(meditation_score, shamatha_score)")
        self.assertAlmostEqual(self.ev.evaluate(self.vars), 42.0)

    def test_conditional_true(self):
        self.ev.set_formula("alpha1 if alpha1 > beta1 else beta1")
        self.assertAlmostEqual(self.ev.evaluate(self.vars), 70000.0)

    def test_conditional_false(self):
        self.ev.set_formula("alpha1 if alpha1 < beta1 else beta1")
        self.assertAlmostEqual(self.ev.evaluate(self.vars), 10000.0)

    def test_negation(self):
        self.ev.set_formula("-alpha1")
        self.assertAlmostEqual(self.ev.evaluate(self.vars), -70000.0)

    def test_power(self):
        self.ev.set_formula("pow(alpha_norm, 2)")
        self.assertAlmostEqual(self.ev.evaluate(self.vars), 0.45 ** 2, places=4)

    def test_missing_variable_defaults_to_zero(self):
        self.ev.set_formula("alpha1 + beta1")
        result = self.ev.evaluate({"alpha1": 10.0})
        self.assertAlmostEqual(result, 10.0)

    def test_empty_vars_returns_zero(self):
        self.ev.set_formula("alpha1")
        self.assertAlmostEqual(self.ev.evaluate({}), 0.0)

    def test_no_formula_returns_zero(self):
        self.assertAlmostEqual(self.ev.evaluate(self.vars), 0.0)


class TestFormulaErrorHandling(unittest.TestCase):
    """Test graceful handling of runtime errors."""

    def setUp(self):
        self.ev = CustomFormulaEvaluator()

    def test_division_by_zero(self):
        self.ev.set_formula("1 / 0")
        self.assertAlmostEqual(self.ev.evaluate({}), 0.0)

    def test_overflow_power(self):
        self.ev.set_formula("pow(999, 999)")
        self.assertAlmostEqual(self.ev.evaluate({}), 0.0)

    def test_large_exponent_clamped(self):
        self.ev.set_formula("alpha1 ** 200")
        self.assertAlmostEqual(self.ev.evaluate({"alpha1": 2.0}), 0.0)

    def test_pow_function_overflow_clamped(self):
        self.ev.set_formula("pow(alpha1, 200)")
        result = self.ev.evaluate({"alpha1": 2.0})
        self.assertLessEqual(result, 1e12)

    def test_log_of_zero(self):
        self.ev.set_formula("log(alpha1)")
        result = self.ev.evaluate({"alpha1": 0.0})
        self.assertAlmostEqual(result, 0.0)

    def test_sqrt_of_negative(self):
        self.ev.set_formula("sqrt(alpha1)")
        result = self.ev.evaluate({"alpha1": -1.0})
        self.assertAlmostEqual(result, 0.0)

    def test_result_clamped_to_max(self):
        self.ev.set_formula("alpha1 * alpha2")
        result = self.ev.evaluate({"alpha1": 1e8, "alpha2": 1e8})
        self.assertLessEqual(result, 1e12)


class TestAvgValidation(unittest.TestCase):
    """Test avg() function validation."""

    def setUp(self):
        self.ev = CustomFormulaEvaluator()

    def test_avg_simple_variable(self):
        ok, _ = self.ev.set_formula("avg(alpha1, 10)")
        self.assertTrue(ok)

    def test_avg_expression(self):
        ok, _ = self.ev.set_formula("avg(alpha1 + beta1, 10)")
        self.assertTrue(ok)

    def test_avg_nested_expression(self):
        ok, _ = self.ev.set_formula("avg(sqrt(alpha_norm) * 100, 30)")
        self.assertTrue(ok)

    def test_avg_missing_window_size(self):
        ok, err = self.ev.set_formula("avg(alpha1)")
        self.assertFalse(ok)
        self.assertIn("2 arguments", err)

    def test_avg_unknown_variable(self):
        ok, err = self.ev.set_formula("avg(unknown_var, 5)")
        self.assertFalse(ok)
        self.assertIn("Unknown variable", err)

    def test_avg_window_too_large(self):
        ok, err = self.ev.set_formula("avg(alpha1, 99999)")
        self.assertFalse(ok)
        self.assertIn("window size", err)

    def test_avg_window_zero(self):
        ok, err = self.ev.set_formula("avg(alpha1, 0)")
        self.assertFalse(ok)
        self.assertIn("window size", err)

    def test_avg_window_negative(self):
        ok, err = self.ev.set_formula("avg(alpha1, -5)")
        self.assertFalse(ok)

    def test_avg_in_larger_expression(self):
        ok, _ = self.ev.set_formula("avg(alpha1, 3) / (avg(beta1, 3) + 1)")
        self.assertTrue(ok)


class TestAvgEvaluation(unittest.TestCase):
    """Test avg() windowed average evaluation."""

    def setUp(self):
        self.ev = CustomFormulaEvaluator()

    def test_avg_simple_variable_windowed(self):
        self.ev.set_formula("avg(meditation_score, 5)")
        for i in range(10):
            self.ev.push_variables({"meditation_score": 50.0 + i * 5.0})
        result = self.ev.evaluate({"meditation_score": 95.0})
        # Last 5 pushed: 75, 80, 85, 90, 95 → avg = 85
        self.assertAlmostEqual(result, 85.0, places=2)

    def test_avg_expression_windowed(self):
        self.ev.set_formula("avg(alpha1 + beta1, 4)")
        for i in range(6):
            self.ev.push_variables({
                "alpha1": 100.0 * (i + 1),
                "beta1": 50.0 * (i + 1),
            })
        result = self.ev.evaluate({"alpha1": 600.0, "beta1": 300.0})
        # pushed sums: 150, 300, 450, 600, 750, 900; last 4: 450+600+750+900 / 4 = 675
        self.assertAlmostEqual(result, 675.0, places=2)

    def test_avg_sqrt_expression(self):
        self.ev.set_formula("avg(sqrt(alpha_norm) * 100, 3)")
        for val in [0.25, 0.49, 0.64, 0.81, 1.0]:
            self.ev.push_variables({"alpha_norm": val})
        result = self.ev.evaluate({"alpha_norm": 1.0})
        # pushed: 50, 70, 80, 90, 100; last 3: 80+90+100 / 3 = 90
        self.assertAlmostEqual(result, 90.0, places=1)

    def test_avg_no_history_returns_current(self):
        self.ev.set_formula("avg(alpha1, 10)")
        result = self.ev.evaluate({"alpha1": 42.0})
        self.assertAlmostEqual(result, 42.0)

    def test_avg_fewer_points_than_window(self):
        self.ev.set_formula("avg(alpha1, 100)")
        for i in range(3):
            self.ev.push_variables({"alpha1": float(i + 1) * 10.0})
        result = self.ev.evaluate({"alpha1": 30.0})
        # Only 3 values: 10, 20, 30 → avg = 20
        self.assertAlmostEqual(result, 20.0, places=2)

    def test_avg_compound_expression(self):
        self.ev.set_formula("avg(alpha1, 3) / (avg(beta1, 3) + 1)")
        for i in range(5):
            self.ev.push_variables({
                "alpha1": 100.0 * (i + 1),
                "beta1": 50.0 * (i + 1),
            })
        result = self.ev.evaluate({"alpha1": 500.0, "beta1": 250.0})
        # alpha1 last 3: 300,400,500→avg=400; beta1 last 3: 150,200,250→avg=200
        expected = 400.0 / 201.0
        self.assertAlmostEqual(result, expected, places=3)

    def test_history_clears_on_new_formula(self):
        self.ev.set_formula("avg(alpha1, 5)")
        for i in range(10):
            self.ev.push_variables({"alpha1": 100.0})
        # Set new formula — history should reset
        self.ev.set_formula("avg(alpha1, 5)")
        result = self.ev.evaluate({"alpha1": 50.0})
        # No history yet → falls back to current value
        self.assertAlmostEqual(result, 50.0)

    def test_avg_with_division_by_zero_in_expr(self):
        self.ev.set_formula("avg(alpha1 / beta1, 3)")
        self.ev.push_variables({"alpha1": 10.0, "beta1": 0.0})
        self.ev.push_variables({"alpha1": 10.0, "beta1": 2.0})
        self.ev.push_variables({"alpha1": 10.0, "beta1": 5.0})
        result = self.ev.evaluate({"alpha1": 10.0, "beta1": 5.0})
        # pushed: 0 (div by zero → 0), 5.0, 2.0 → avg = (0+5+2)/3 = 2.333
        self.assertAlmostEqual(result, 2.333, places=2)


if __name__ == "__main__":
    unittest.main()
