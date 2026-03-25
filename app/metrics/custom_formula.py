import ast
import math
import operator
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from app.logger import logger

# Allowed variable names the user can reference in formulas
ALLOWED_VARIABLES = {
    "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2",
    "theta", "delta",
    "alpha", "beta", "gamma",
    "alpha_norm", "beta_norm", "gamma_norm", "theta_norm", "delta_norm",
    "total_power",
    # sqrt-normalized relative bands: sqrt(band / sum_of_6_bands)
    "s_alpha1", "s_alpha2", "s_beta1", "s_beta2", "s_theta", "s_delta",
    "meditation_score", "shamatha_score", "distraction", "sinking",
    "subtle_distraction", "stability", "calmness",
    "native_attention", "native_meditation",
}

# Safe math functions the user can call
ALLOWED_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "pow": pow,
    "min": min,
    "max": max,
    "sin": math.sin,
    "cos": math.cos,
    "tanh": math.tanh,
}

# Functions that operate on windowed history — handled specially
_WINDOWED_FUNCTIONS = {"avg"}

_MAX_WINDOW = 600

# Safe binary/unary operators
_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_MAX_RESULT = 1e12
_MAX_FORMULA_LEN = 500


class CustomFormulaEvaluator:
    """Safe evaluator for user-defined EEG metric formulas.

    Parses a Python-style math expression using AST and evaluates it
    against EEG band powers and computed metrics. Only allows whitelisted
    variables, functions, and operators. Handles division by zero,
    overflow, and malformed expressions gracefully.
    """

    def __init__(self) -> None:
        self._formula: str = ""
        self._ast_tree: Optional[ast.Expression] = None
        self._last_error: str = ""
        self._history: Dict[str, Deque[float]] = {}
        self._avg_exprs: List[Tuple[str, ast.AST]] = []

    @property
    def formula(self) -> str:
        return self._formula

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def is_valid(self) -> bool:
        return self._ast_tree is not None and self._formula != ""

    def set_formula(self, formula: str) -> Tuple[bool, str]:
        """Parse and validate a formula string.

        Returns (success, error_message).
        """
        formula = formula.strip()
        if not formula:
            self._formula = ""
            self._ast_tree = None
            self._last_error = ""
            return True, ""

        if len(formula) > _MAX_FORMULA_LEN:
            err = f"Formula too long (max {_MAX_FORMULA_LEN} chars)"
            self._last_error = err
            logger.warning(f"Custom formula rejected: {err}")
            return False, err

        try:
            tree = ast.parse(formula, mode="eval")
        except SyntaxError as e:
            err = f"Syntax error: {e.msg}"
            self._last_error = err
            logger.warning(f"Custom formula syntax error: {err}")
            return False, err

        # Validate AST nodes
        ok, err = self._validate_ast(tree.body)
        if not ok:
            self._last_error = err
            logger.warning(f"Custom formula validation error: {err}")
            return False, err

        self._formula = formula
        self._ast_tree = tree
        self._last_error = ""
        self._history.clear()
        self._avg_exprs = self._collect_avg_exprs(tree.body)
        logger.info(f"Custom formula set: {formula}")
        return True, ""

    def push_variables(self, variables: Dict[str, float]) -> None:
        """Record current tick's variable values into the history buffer.

        Call this once per tick BEFORE evaluate(). Evaluates each avg()
        expression subtree and stores the result.
        """
        for key, expr_node in self._avg_exprs:
            if key not in self._history:
                self._history[key] = deque(maxlen=_MAX_WINDOW)
            try:
                val = self._eval_node(expr_node, variables)
                if not math.isfinite(val):
                    val = 0.0
            except Exception:
                val = 0.0
            self._history[key].append(val)

    def evaluate(self, variables: Dict[str, float]) -> float:
        """Evaluate the formula against the given variables.

        Returns 0.0 on any error (division by zero, overflow, etc.).
        """
        if not self._ast_tree:
            return 0.0
        try:
            result = self._eval_node(self._ast_tree.body, variables)
            if not math.isfinite(result):
                return 0.0
            return max(-_MAX_RESULT, min(result, _MAX_RESULT))
        except (ZeroDivisionError, ValueError, OverflowError, TypeError, KeyError):
            return 0.0
        except Exception as e:
            logger.debug(f"Custom formula eval error: {e}")
            return 0.0

    def _validate_ast(self, node: ast.AST) -> Tuple[bool, str]:
        """Recursively validate that all AST nodes are safe."""
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                return False, f"Unsupported constant type: {type(node.value).__name__}"
            return True, ""

        if isinstance(node, ast.Name):
            if node.id not in ALLOWED_VARIABLES and node.id not in ALLOWED_FUNCTIONS:
                return False, f"Unknown variable: '{node.id}'"
            return True, ""

        if isinstance(node, ast.UnaryOp):
            if type(node.op) not in _OPERATORS:
                return False, f"Unsupported operator: {type(node.op).__name__}"
            return self._validate_ast(node.operand)

        if isinstance(node, ast.BinOp):
            if type(node.op) not in _OPERATORS:
                return False, f"Unsupported operator: {type(node.op).__name__}"
            ok, err = self._validate_ast(node.left)
            if not ok:
                return False, err
            return self._validate_ast(node.right)

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                return False, "Only simple function calls allowed"
            fname = node.func.id
            if fname not in ALLOWED_FUNCTIONS and fname not in _WINDOWED_FUNCTIONS:
                return False, f"Unknown function: '{fname}'"
            if node.keywords:
                return False, "Keyword arguments not allowed"
            if fname in _WINDOWED_FUNCTIONS:
                return self._validate_windowed_call(node)
            for arg in node.args:
                ok, err = self._validate_ast(arg)
                if not ok:
                    return False, err
            return True, ""

        if isinstance(node, ast.IfExp):
            for sub in (node.test, node.body, node.orelse):
                ok, err = self._validate_ast(sub)
                if not ok:
                    return False, err
            return True, ""

        if isinstance(node, ast.Compare):
            ok, err = self._validate_ast(node.left)
            if not ok:
                return False, err
            for comp in node.comparators:
                ok, err = self._validate_ast(comp)
                if not ok:
                    return False, err
            for op in node.ops:
                if type(op) not in (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq):
                    return False, f"Unsupported comparison: {type(op).__name__}"
            return True, ""

        return False, f"Unsupported expression: {type(node).__name__}"

    def _validate_windowed_call(self, node: ast.Call) -> Tuple[bool, str]:
        """Validate avg(expression, N) call."""
        fname = node.func.id
        if len(node.args) != 2:
            return False, f"{fname}() requires exactly 2 arguments: {fname}(expr, N)"
        arg0 = node.args[0]
        ok, err = self._validate_ast(arg0)
        if not ok:
            return False, f"In {fname}() first argument: {err}"
        arg1 = node.args[1]
        if not isinstance(arg1, ast.Constant) or not isinstance(arg1.value, (int, float)):
            return False, f"{fname}() second argument must be a number"
        n = int(arg1.value)
        if n < 1 or n > _MAX_WINDOW:
            return False, f"{fname}() window size must be 1-{_MAX_WINDOW}"
        return True, ""

    def _collect_avg_exprs(self, node: ast.AST) -> List[Tuple[str, ast.AST]]:
        """Walk the AST and collect (key, expr_node) for each avg() call."""
        exprs: Dict[str, ast.AST] = {}
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                if child.func.id in _WINDOWED_FUNCTIONS and child.args:
                    key = ast.dump(child.args[0])
                    exprs[key] = child.args[0]
        return list(exprs.items())

    def _eval_node(self, node: ast.AST, variables: Dict[str, float]) -> float:
        if isinstance(node, ast.Constant):
            return float(node.value)

        if isinstance(node, ast.Name):
            if node.id in ALLOWED_FUNCTIONS:
                return 0.0
            return float(variables.get(node.id, 0.0))

        if isinstance(node, ast.UnaryOp):
            op_func = _OPERATORS[type(node.op)]
            return op_func(self._eval_node(node.operand, variables))

        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left, variables)
            right = self._eval_node(node.right, variables)
            op_func = _OPERATORS[type(node.op)]
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                return 0.0
            return op_func(left, right)

        if isinstance(node, ast.Call):
            fname = node.func.id
            if fname in _WINDOWED_FUNCTIONS:
                return self._eval_windowed(node, variables)
            func = ALLOWED_FUNCTIONS[fname]
            args = [self._eval_node(a, variables) for a in node.args]
            return float(func(*args))

        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, variables)
            for op, comp in zip(node.ops, node.comparators):
                right = self._eval_node(comp, variables)
                if isinstance(op, ast.Lt):
                    if not (left < right):
                        return 0.0
                elif isinstance(op, ast.LtE):
                    if not (left <= right):
                        return 0.0
                elif isinstance(op, ast.Gt):
                    if not (left > right):
                        return 0.0
                elif isinstance(op, ast.GtE):
                    if not (left >= right):
                        return 0.0
                elif isinstance(op, ast.Eq):
                    if not (left == right):
                        return 0.0
                elif isinstance(op, ast.NotEq):
                    if not (left != right):
                        return 0.0
                left = right
            return 1.0

        if isinstance(node, ast.IfExp):
            test = self._eval_node(node.test, variables)
            if test:
                return self._eval_node(node.body, variables)
            return self._eval_node(node.orelse, variables)

        return 0.0

    def _eval_windowed(self, node: ast.Call, variables: Dict[str, float]) -> float:
        """Evaluate avg(expression, N) using the history buffer."""
        key = ast.dump(node.args[0])
        n = int(node.args[1].value)
        buf = self._history.get(key)
        if not buf:
            return self._eval_node(node.args[0], variables)
        values = list(buf)[-n:]
        if not values:
            return 0.0
        return sum(values) / len(values)


if __name__ == "__main__":
    ev = CustomFormulaEvaluator()

    test_vars = {
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

    formulas = [
        ("(alpha1 + alpha2) / (beta1 + beta2 + 1)", "Alpha/Beta ratio"),
        ("sqrt(alpha_norm) * 100", "Sqrt alpha norm scaled"),
        ("meditation_score * 0.7 + shamatha_score * 0.3", "Weighted blend"),
        ("log(total_power + 1)", "Log total power"),
        ("alpha / (beta + gamma + 1)", "Alpha dominance"),
        ("100 * alpha_norm / (beta_norm + 0.001)", "Alpha/Beta norm ratio"),
        ("max(meditation_score, shamatha_score)", "Max of med/sham"),
        ("1 / 0", "Division by zero (should return 0)"),
        ("pow(999, 999)", "Overflow (should return 0)"),
        ("import os", "Should fail validation"),
        ("__import__('os')", "Should fail validation"),
        ("alpha1 if alpha1 > beta1 else beta1", "Conditional expression"),
    ]

    for formula, desc in formulas:
        ok, err = ev.set_formula(formula)
        if ok:
            result = ev.evaluate(test_vars)
            print(f"  {desc}: {formula} = {result:.2f}")
        else:
            print(f"  {desc}: REJECTED - {err}")

    # --- avg() windowed average tests ---
    print("\n--- avg() windowed average tests ---")

    ok, err = ev.set_formula("avg(meditation_score, 5)")
    assert ok, f"avg formula should be valid: {err}"
    for i in range(10):
        tick_vars = {**test_vars, "meditation_score": 50.0 + i * 5.0}
        ev.push_variables(tick_vars)
    result = ev.evaluate({"meditation_score": 95.0})
    print(f"  avg(meditation_score, 5) after 10 ticks: {result:.2f} (expected 85.00)")

    ok, err = ev.set_formula("avg(alpha1, 3) / (avg(beta1, 3) + 1)")
    assert ok, f"compound avg formula should be valid: {err}"
    for i in range(5):
        tick_vars = {"alpha1": 100.0 * (i + 1), "beta1": 50.0 * (i + 1)}
        ev.push_variables(tick_vars)
    result = ev.evaluate({"alpha1": 500.0, "beta1": 250.0})
    print(f"  avg(alpha1,3)/(avg(beta1,3)+1) = {result:.4f} (expected ~1.9900)")

    # avg() with expression as first arg
    ok, err = ev.set_formula("avg(alpha1 + beta1, 4)")
    assert ok, f"avg(expr, N) should be valid: {err}"
    for i in range(6):
        tick_vars = {"alpha1": 100.0 * (i + 1), "beta1": 50.0 * (i + 1)}
        ev.push_variables(tick_vars)
    result = ev.evaluate({"alpha1": 600.0, "beta1": 300.0})
    # pushed: 150, 300, 450, 600, 750, 900; last 4: 450, 600, 750, 900 → avg=675
    print(f"  avg(alpha1 + beta1, 4) = {result:.2f} (expected 675.00)")

    ok, err = ev.set_formula("avg(sqrt(alpha_norm) * 100, 3)")
    assert ok, f"avg(sqrt(x)*100, N) should be valid: {err}"
    for val in [0.25, 0.49, 0.64, 0.81, 1.0]:
        ev.push_variables({"alpha_norm": val})
    result = ev.evaluate({"alpha_norm": 1.0})
    # pushed: 50, 70, 80, 90, 100; last 3: 80, 90, 100 → avg=90
    print(f"  avg(sqrt(alpha_norm)*100, 3) = {result:.2f} (expected 90.00)")

    # Validation errors
    ok, err = ev.set_formula("avg(alpha1)")
    print(f"  avg(alpha1) → REJECTED: {err}" if not ok else "  ERROR: should have been rejected")
    ok, err = ev.set_formula("avg(unknown_var, 5)")
    print(f"  avg(unknown_var, 5) → REJECTED: {err}" if not ok else "  ERROR: should have been rejected")
    ok, err = ev.set_formula("avg(alpha1, 99999)")
    print(f"  avg(alpha1, 99999) → REJECTED: {err}" if not ok else "  ERROR: should have been rejected")

    print("\nAll custom formula tests completed.")
