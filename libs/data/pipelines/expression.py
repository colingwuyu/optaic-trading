"""Expression Pipeline Implementation.

Runs expression chains to generate computed datasets.
Ported from optaic-v0/pipelines/data/expression.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from libs.data.pipelines.base import DataPipeline
from libs.data.registry import register_pipeline

if TYPE_CHECKING:
    import pandas as pd


@register_pipeline("ExpressionPipeline")
class ExpressionPipeline(DataPipeline):
    """Pipeline that evaluates expressions to generate data.

    Bridges the Data Layer (Pipelines) and Function Layer (Expressions).

    Config Options:
    - expression: Expression string, list, or dict to evaluate
    - constituents: List of input dataset names (loaded into context)

    Expressions can be:
    - Single: "MEAN($close, 20)"
    - Named: "ma: MEAN($close, 20)"
    - Multi-line:
        ma_fast: MEAN($close, 5)
        ma_slow: MEAN($close, 20)
        signal: $ma_fast - $ma_slow
    - Dict: {"ma_fast": "MEAN($close, 5)", "ma_slow": "MEAN($close, 20)"}
    """

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        store: Any | None = None,
        context_loader: Any | None = None,
        **kwargs: Any,
    ):
        """Initialize ExpressionPipeline.

        Args:
            resource_id: Pipeline resource ID
            config: Configuration containing 'expression' and 'constituents'
            store: Optional store for saving results
            context_loader: Callable to load datasets into context
            **kwargs: Additional config
        """
        super().__init__(resource_id, config, store, **kwargs)

        if "expression" not in config:
            raise ValueError("ExpressionPipeline requires 'expression' in config")

        self.expression = config["expression"]
        self.constituents = config.get("constituents", [])
        self.context_loader = context_loader

    def extract(self, **kwargs: Any) -> dict[str, Any]:
        """Load constituent datasets into context.

        For ExpressionPipeline, extraction is loading input datasets.

        Returns:
            Dict mapping dataset names to DataFrames
        """
        context = {}

        if self.context_loader is not None:
            for name in self.constituents:
                try:
                    data = self.context_loader(
                        name,
                        start_date=kwargs.get("start_date"),
                        end_date=kwargs.get("end_date"),
                        as_of_date=kwargs.get("as_of_date"),
                    )
                    context[name] = data
                except Exception as e:
                    raise RuntimeError(f"Failed to load constituent '{name}': {e}") from e

        # Also accept pre-loaded context from kwargs
        for key, value in kwargs.items():
            if key not in ["start_date", "end_date", "as_of_date", "mode"]:
                context[key] = value

        return context

    def transform(
        self,
        raw_data: dict[str, Any],
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Execute expression chain.

        Args:
            raw_data: Context dict from extract()
            **kwargs: Additional parameters

        Returns:
            Result DataFrame
        """
        import pandas as pd

        from libs.data.expression import ExpressionEngine

        engine = ExpressionEngine()

        # Build context
        context = raw_data.copy()

        # Parse expressions
        expressions = self._parse_expressions()

        # Execute each expression in order
        current_result = None
        for var_name, expr_str in expressions:
            # Add previous result as '_' for chaining
            if current_result is not None:
                context["_"] = current_result

            # Evaluate
            result = engine.evaluate(expr_str, context)

            # Extract series if single-column DataFrame
            if isinstance(result, pd.DataFrame) and len(result.columns) == 1:
                result = result.iloc[:, 0]
                result.name = var_name

            current_result = result
            context[var_name] = result

        # Return all intermediates if requested
        if kwargs.get("return_all_intermediates", False):
            return self._combine_intermediates(context, expressions)

        # Return final result
        if current_result is None:
            return pd.DataFrame()

        if isinstance(current_result, pd.Series):
            return current_result.to_frame(name=current_result.name or "result")

        return current_result

    def run(
        self,
        mode: str = "overwrite",
        **kwargs: Any,
    ) -> "pd.DataFrame | dict[str, Any]":
        """Execute expression pipeline.

        Unlike base class, ExpressionPipeline returns the DataFrame directly
        when used for preview. The service layer handles persistence.

        Args:
            mode: Write mode
            **kwargs: Context and parameters

        Returns:
            Result DataFrame or run statistics
        """
        # Extract (load constituents)
        context = self.extract(**kwargs)

        # Transform (evaluate expressions)
        result = self.transform(context, **kwargs)

        # Save if store is configured and not in preview mode
        if self.store is not None and not kwargs.get("preview", False):
            self.store.write(result, mode=mode)

        return result

    def _parse_expressions(self) -> list[tuple[str, str]]:
        """Parse expression config into ordered list of (name, expr) tuples."""
        expr = self.expression

        if isinstance(expr, dict):
            return list(expr.items())

        if isinstance(expr, list):
            return [("_", e) for e in expr]

        if isinstance(expr, str):
            lines = [
                ln.strip()
                for ln in expr.replace("\r\n", "\n").split("\n")
                if ln.strip() and not ln.strip().startswith("#")
            ]

            result = []
            for ln in lines:
                if ":" in ln:
                    name, expr_str = ln.split(":", 1)
                    result.append((name.strip(), expr_str.strip()))
                else:
                    result.append(("_", ln.strip()))
            return result

        raise ValueError(f"Invalid expression type: {type(expr)}")

    def _combine_intermediates(
        self,
        context: dict[str, Any],
        expressions: list[tuple[str, str]],
    ) -> "pd.DataFrame":
        """Combine all intermediate variables into single DataFrame.

        Used for preview mode to show all expression results.
        """
        import pandas as pd

        expr_names = {name for name, _ in expressions if name != "_"}

        dfs = []
        for name in expr_names:
            if name not in context or context[name] is None:
                continue

            data = context[name]
            if isinstance(data, pd.Series):
                dfs.append(data.to_frame(name=name))
            elif isinstance(data, pd.DataFrame):
                if len(data.columns) == 1:
                    renamed = data.copy()
                    renamed.columns = [name]
                    dfs.append(renamed)
                else:
                    renamed = data.copy()
                    renamed.columns = [f"{name}_{col}" for col in data.columns]
                    dfs.append(renamed)

        if not dfs:
            return pd.DataFrame()

        return pd.concat(dfs, axis=1)

    def is_up_to_date(self) -> bool:
        """Expression is up-to-date if all constituents are up-to-date.

        This would require checking constituent statuses, which
        is handled by the service layer.
        """
        return True
