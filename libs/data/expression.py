"""Expression Engine.

Evaluates string expressions that reference datasets and operators.
Adapted from optaic-v0/function/expression.py.

Syntax:
- $dataset: Refers to a dataset by name from context
- $dataset.col: Access column 'col' from dataset
- FUNC(arg1, arg2): Call operator from OPS_REGISTRY
- |expr|: Absolute value (converted to ABS(expr))
- Standard operators: +, -, *, / work natively with pandas

Example expressions:
    "MEAN($close, 20)"
    "($close - MEAN($close, 20)) / STD($close, 20)"
    "log_price: LOG($close)"
    "returns: DELTA($log_price, 1)"

Key Difference from optaic-v0:
- Instead of using data_api.get(name), this works with pre-loaded context
- The service layer is responsible for loading datasets into the context
- This keeps the expression engine stateless and testable
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


class ExpressionEngine:
    """Stateless expression evaluator.

    Evaluates expressions against a context of pre-loaded DataFrames.
    The service layer should load datasets into the context before calling.

    Example:
        engine = ExpressionEngine()
        context = {
            "prices": prices_df,
            "volume": volume_df,
        }
        result = engine.evaluate(
            expression="MEAN($prices.close, 20)",
            context=context,
        )
    """

    def evaluate(
        self,
        expression: str,
        context: dict[str, Any],
    ) -> "pd.DataFrame":
        """Evaluate an expression against a context.

        Args:
            expression: Expression string or dict of named expressions
            context: Dict mapping names to DataFrames

        Returns:
            DataFrame with evaluation result

        Raises:
            ValueError: If expression is invalid or references missing data
            RuntimeError: If evaluation fails
        """

        # Parse expression format
        expression_dict = self._parse_expression(expression)

        # Execute expressions in order, building up results
        results: dict[str, pd.DataFrame | pd.Series] = {}
        exec_context = dict(context)

        for var_name, expr_str in expression_dict.items():
            result = self._evaluate_single(expr_str, exec_context)
            results[var_name] = result
            exec_context[var_name] = result  # Available for subsequent expressions

        # Combine results
        return self._combine_results(results)

    def _parse_expression(self, expression: str | dict) -> dict[str, str]:
        """Parse expression into dict of name -> expression.

        Supports:
        - Dict: {"name": "EXPR", ...}
        - Multi-line: "name1: EXPR1\nname2: EXPR2"
        - Single named: "name: EXPR"
        - Simple: "EXPR" (named "result")
        """
        if isinstance(expression, dict):
            return expression

        expression_dict: dict[str, str] = {}

        if ":" in expression and "\n" in expression:
            # Multi-line named expressions
            for line in expression.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    var_name, expr_value = line.split(":", 1)
                    expression_dict[var_name.strip()] = expr_value.strip()
        elif ":" in expression and expression.count(":") == 1:
            # Single named expression
            var_name, expr_value = expression.split(":", 1)
            expression_dict[var_name.strip()] = expr_value.strip()
        else:
            # Simple expression
            expression_dict["result"] = expression.strip()

        return expression_dict

    def _evaluate_single(
        self,
        expression: str,
        context: dict[str, Any],
    ) -> "pd.DataFrame | pd.Series":
        """Evaluate a single expression string.

        Steps:
        1. Convert |expr| to ABS(expr)
        2. Replace $name.field with context access
        3. Replace $name with context access
        4. Evaluate with operators in scope
        """
        import pandas as pd

        from libs.data.ops import OPS_REGISTRY

        # Step 1: Convert |expr| to ABS(expr)
        abs_pattern = re.compile(r"\|([^|]+)\|")
        expression = abs_pattern.sub(r"ABS(\1)", expression)

        # Step 2 & 3: Replace $references with context access
        # Pattern: $identifier(.identifier)?
        ref_pattern = re.compile(r"\$([a-zA-Z0-9_]*)(?:\.([a-zA-Z0-9_]+))?")

        def ref_replacer(match: re.Match) -> str:
            ds_name = match.group(1) or "_"  # Standalone $ -> "_"
            field_suffix = match.group(2)

            if ds_name not in context:
                if ds_name == "_":
                    raise ValueError(
                        "Expression uses '$' but no previous result ('_') in context"
                    )
                raise ValueError(
                    f"Expression references ${ds_name}, but '{ds_name}' not in context. "
                    f"Available: {list(context.keys())}"
                )

            if field_suffix:
                if field_suffix.isdigit():
                    return f"__ctx['{ds_name}'][{field_suffix}]"
                return f"__ctx['{ds_name}'].{field_suffix}"

            return f"__ctx['{ds_name}']"

        safe_expr = ref_pattern.sub(ref_replacer, expression)

        # Step 4: Evaluate with operators in scope
        eval_globals = {"__builtins__": None}
        eval_globals.update(OPS_REGISTRY)

        eval_locals = {"__ctx": context}

        try:
            result = eval(safe_expr, eval_globals, eval_locals)  # noqa: S307
        except Exception as e:
            raise RuntimeError(
                f"Failed to evaluate expression '{expression}': {e}"
            ) from e

        # Ensure result is DataFrame or Series
        if isinstance(result, pd.Series):
            return result
        if isinstance(result, pd.DataFrame):
            return result

        # Handle scalar results (e.g., "1 + 2")
        # Convert to a single-element Series
        return pd.Series([result])

    def _combine_results(
        self,
        results: dict[str, "pd.DataFrame | pd.Series"],
    ) -> "pd.DataFrame":
        """Combine named results into a single DataFrame."""
        import pandas as pd

        if len(results) == 0:
            return pd.DataFrame()

        if len(results) == 1:
            result = next(iter(results.values()))
            result_name = next(iter(results.keys()))
            if isinstance(result, pd.DataFrame):
                if "result" in result.columns and result_name != "result":
                    return result.rename(columns={"result": result_name})
                return result
            return pd.DataFrame({result_name: result})

        # Multiple results: join on index
        dfs_to_combine = []
        for name, r in results.items():
            if isinstance(r, pd.DataFrame):
                if len(r.columns) == 1:
                    df = r.rename(columns={r.columns[0]: name})
                else:
                    df = r.add_prefix(f"{name}_")
            else:
                df = pd.Series(r, name=name).to_frame()
            dfs_to_combine.append(df)

        if not dfs_to_combine:
            return pd.DataFrame()

        combined = dfs_to_combine[0]
        for df in dfs_to_combine[1:]:
            combined = combined.join(df, how="outer")

        return combined

    def validate_expression(self, expression: str) -> list[str]:
        """Validate expression syntax and return referenced dataset names.

        Args:
            expression: Expression to validate

        Returns:
            List of dataset names referenced in the expression

        Raises:
            ValueError: If expression has syntax errors
        """
        # Parse to ensure valid format
        expression_dict = self._parse_expression(expression)

        # Extract referenced dataset names
        ref_pattern = re.compile(r"\$([a-zA-Z0-9_]+)")
        referenced = set()

        for expr_str in expression_dict.values():
            for match in ref_pattern.finditer(expr_str):
                referenced.add(match.group(1))

        return list(referenced)

    def get_used_operators(self, expression: str) -> list[str]:
        """Extract operator names used in the expression.

        Args:
            expression: Expression to analyze

        Returns:
            List of operator names (e.g., ["MEAN", "STD"])
        """
        from libs.data.ops import OPS_REGISTRY

        expression_dict = self._parse_expression(expression)

        used = set()
        for expr_str in expression_dict.values():
            for op_name in OPS_REGISTRY.keys():
                # Look for operator as function call: OP_NAME(
                if re.search(rf"\b{op_name}\s*\(", expr_str, re.IGNORECASE):
                    used.add(op_name)

        return list(used)
