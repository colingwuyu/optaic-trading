# Quant-Specific Contracts

## Signal Contracts

| Contract | Purpose | Enforcement |
|----------|---------|-------------|
| `signal.bounds` | Value range [-1, 1] | Block in official |
| `signal.schema` | Arrow schema match | Block always |
| `signal.coverage` | Date/symbol coverage | Warn in staging |

## Dataset Contracts

| Contract | Purpose | Enforcement |
|----------|---------|-------------|
| `dataset.pit` | No lookahead bias | Block in official |
| `dataset.schema` | Column types match | Block always |
| `dataset.freshness` | Data not stale | Warn then escalate |
| `dataset.coverage` | Required dates/symbols | Warn in staging |

## Portfolio Contracts

| Contract | Purpose | Enforcement |
|----------|---------|-------------|
| `portfolio.weights` | Sum-to-one, bounds | Block in official |
| `portfolio.leverage` | Gross/net limits | Block in official |
| `portfolio.turnover` | Max turnover | Warn then block |
| `portfolio.concentration` | Max single position | Block in official |

## Model Contracts

| Contract | Purpose | Enforcement |
|----------|---------|-------------|
| `model.performance` | Min Sharpe/accuracy | Block in official |
| `model.stability` | Parameter stability | Warn in staging |
| `model.freshness` | Retrain schedule | Warn then escalate |

## Common Validation Patterns

### Numeric Range Check
```python
def check_range(values, min_val, max_val):
    violations = [v for v in values if v < min_val or v > max_val]
    return len(violations) == 0, violations
```

### Coverage Check
```python
def check_coverage(dates, symbols, min_dates, min_symbols):
    return len(set(dates)) >= min_dates and len(set(symbols)) >= min_symbols
```

### Sum-to-One Check
```python
def check_sum_to_one(weights, tolerance=0.001):
    total = sum(weights.values())
    return abs(total - 1.0) <= tolerance
```

### PIT Correctness Check
```python
def check_pit(df, kd_col, ad_col):
    violations = df[df[kd_col] < df[ad_col]]
    return len(violations) == 0, violations.index.tolist()
```
