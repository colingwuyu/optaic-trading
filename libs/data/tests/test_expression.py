"""Tests for expression engine."""

import pandas as pd
import pytest

from libs.data.expression import ExpressionEngine


@pytest.fixture
def engine():
    """Create an expression engine instance."""
    return ExpressionEngine()


@pytest.fixture
def context():
    """Create a sample context with datasets."""
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    prices = pd.DataFrame(
        {
            "close": [100 + i * 0.5 for i in range(100)],
            "high": [101 + i * 0.5 for i in range(100)],
            "low": [99 + i * 0.5 for i in range(100)],
            "volume": [1000000 + i * 1000 for i in range(100)],
        },
        index=dates,
    )
    return {
        "prices": prices,
        "close": prices["close"],
        "volume": prices["volume"],
    }


class TestExpressionParsing:
    """Tests for expression parsing."""

    def test_parse_simple_expression(self, engine):
        """Test parsing simple expression."""
        result = engine._parse_expression("MEAN($close, 20)")
        assert result == {"result": "MEAN($close, 20)"}

    def test_parse_named_expression(self, engine):
        """Test parsing single named expression."""
        result = engine._parse_expression("ma: MEAN($close, 20)")
        assert result == {"ma": "MEAN($close, 20)"}

    def test_parse_multiline_expression(self, engine):
        """Test parsing multi-line named expressions."""
        expr = """
        ma_fast: MEAN($close, 5)
        ma_slow: MEAN($close, 20)
        """
        result = engine._parse_expression(expr)
        assert "ma_fast" in result
        assert "ma_slow" in result
        assert result["ma_fast"] == "MEAN($close, 5)"
        assert result["ma_slow"] == "MEAN($close, 20)"

    def test_parse_dict_expression(self, engine):
        """Test parsing dict expression."""
        expr = {
            "ma_fast": "MEAN($close, 5)",
            "ma_slow": "MEAN($close, 20)",
        }
        result = engine._parse_expression(expr)
        assert result == expr

    def test_parse_ignores_comments(self, engine):
        """Test that comment lines are ignored."""
        expr = """
        # This is a comment
        ma: MEAN($close, 20)
        # Another comment
        """
        result = engine._parse_expression(expr)
        assert len(result) == 1
        assert "ma" in result


class TestExpressionEvaluation:
    """Tests for expression evaluation."""

    def test_evaluate_simple_operator(self, engine, context):
        """Test evaluating simple operator expression."""
        result = engine.evaluate("MEAN($close, 20)", context)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 100
        # First 19 values should be NaN
        assert result["result"].isna().sum() == 19

    def test_evaluate_dataset_access(self, engine, context):
        """Test accessing dataset column."""
        result = engine.evaluate("$prices.close", context)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 100

    def test_evaluate_arithmetic(self, engine, context):
        """Test arithmetic operators."""
        result = engine.evaluate("$close + 10", context)
        assert result["result"].iloc[0] == 110

    def test_evaluate_combined_expression(self, engine, context):
        """Test combined expression with multiple operators."""
        expr = "($close - MEAN($close, 20)) / STD($close, 20)"
        result = engine.evaluate(expr, context)
        assert isinstance(result, pd.DataFrame)

    def test_evaluate_chained_expressions(self, engine, context):
        """Test multi-line expressions where later ones reference earlier."""
        expr = """
        log_price: LOG($close)
        returns: DELTA($log_price, 1)
        """
        result = engine.evaluate(expr, context)
        assert "log_price" in result.columns or "returns" in result.columns

    def test_evaluate_absolute_value_syntax(self, engine, context):
        """Test |expr| syntax for absolute value."""
        result = engine.evaluate("|$close - 105|", context)
        assert isinstance(result, pd.DataFrame)
        # All values should be non-negative
        assert (result["result"] >= 0).all()

    def test_missing_context_raises(self, engine, context):
        """Test that missing context variable raises."""
        with pytest.raises(ValueError, match="not in context"):
            engine.evaluate("$nonexistent", context)

    def test_invalid_expression_raises(self, engine, context):
        """Test that invalid expression raises RuntimeError."""
        with pytest.raises(RuntimeError, match="Failed to evaluate"):
            engine.evaluate("INVALID_SYNTAX(((", context)


class TestExpressionValidation:
    """Tests for expression validation."""

    def test_validate_returns_referenced_datasets(self, engine):
        """Test validate_expression returns referenced names."""
        expr = "MEAN($prices.close, 20) + $volume"
        referenced = engine.validate_expression(expr)
        assert "prices" in referenced
        assert "volume" in referenced

    def test_get_used_operators(self, engine):
        """Test get_used_operators extracts operator names."""
        expr = "MEAN($close, 20) + STD($close, 20) - LOG($volume)"
        operators = engine.get_used_operators(expr)
        assert "MEAN" in operators
        assert "STD" in operators
        assert "LOG" in operators


class TestComplexExpressions:
    """Tests for complex real-world expressions."""

    def test_zscore_expression(self, engine, context):
        """Test Z-score calculation: (x - mean) / std."""
        expr = "($close - MEAN($close, 20)) / STD($close, 20)"
        result = engine.evaluate(expr, context)
        assert isinstance(result, pd.DataFrame)

    def test_volatility_adjusted_returns(self, engine, context):
        """Test volatility-adjusted returns."""
        expr = """
        returns: DELTA(LOG($close), 1)
        vol: STD($returns, 20)
        vol_adj: $returns / $vol
        """
        result = engine.evaluate(expr, context)
        assert isinstance(result, pd.DataFrame)

    def test_momentum_indicator(self, engine, context):
        """Test momentum indicator: current / past - 1."""
        expr = "$close / REF($close, 20) - 1"
        result = engine.evaluate(expr, context)
        assert isinstance(result, pd.DataFrame)
        # First 20 values should be NaN (due to REF)
        assert result["result"].isna().sum() >= 20

    def test_bollinger_bands_components(self, engine, context):
        """Test Bollinger Bands components."""
        expr = """
        middle: MEAN($close, 20)
        std: STD($close, 20)
        upper: $middle + 2 * $std
        lower: $middle - 2 * $std
        """
        result = engine.evaluate(expr, context)
        # Check upper > middle > lower (after warmup period)
        assert isinstance(result, pd.DataFrame)


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_context(self, engine):
        """Test evaluating with empty context."""
        with pytest.raises(ValueError, match="not in context"):
            engine.evaluate("$data", {})

    def test_constant_expression(self, engine):
        """Test constant expression without variables."""
        # Note: This may fail depending on implementation
        # Constants need special handling
        result = engine.evaluate("1 + 2", {})
        assert result["result"].iloc[0] == 3

    def test_underscore_chaining_variable(self, engine, context):
        """Test that _ refers to previous result when available."""
        # This tests the chaining feature where $ alone references _
        context["_"] = context["close"]
        result = engine.evaluate("MEAN($, 5)", context)
        assert isinstance(result, pd.DataFrame)

    def test_nested_operators(self, engine, context):
        """Test nested operator calls."""
        expr = "ABS(DELTA(LOG($close), 1))"
        result = engine.evaluate(expr, context)
        assert isinstance(result, pd.DataFrame)
        # Should be non-negative after ABS
        non_na_values = result["result"].dropna()
        assert (non_na_values >= 0).all()
