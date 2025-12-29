# Data Quality Checks

## Standard Check Types

```python
from dataclasses import dataclass
from typing import Callable, List
from enum import Enum

class QualityLevel(Enum):
    CRITICAL = "critical"  # Blocks pipeline
    WARNING = "warning"    # Logs only
    INFO = "info"         # Informational

@dataclass
class QualityCheck:
    name: str
    level: QualityLevel
    check_fn: Callable
    description: str
```

## Common Checks

### No Future Dates
```python
def no_future_dates(cutoff: datetime):
    """Prevent lookahead bias."""
    async def check(df):
        max_date = df["date"].max()
        if max_date > cutoff.date():
            return False, f"Future date found: {max_date}"
        return True, None

    return QualityCheck(
        name="no_future_dates",
        level=QualityLevel.CRITICAL,
        check_fn=check,
        description="Data contains future dates (lookahead bias)"
    )
```

### No Duplicates
```python
def no_duplicates(key_cols: List[str]):
    """Ensure key uniqueness."""
    async def check(df):
        dups = df.duplicated(subset=key_cols)
        if dups.any():
            return False, f"Found {dups.sum()} duplicate rows"
        return True, None

    return QualityCheck(
        name="no_duplicates",
        level=QualityLevel.CRITICAL,
        check_fn=check,
        description=f"Duplicate rows on {key_cols}"
    )
```

### Coverage Check
```python
def coverage_check(min_symbols: int, min_dates: int):
    """Ensure sufficient data coverage."""
    async def check(df):
        n_symbols = df["symbol"].nunique()
        n_dates = df["date"].nunique()
        if n_symbols < min_symbols:
            return False, f"Only {n_symbols} symbols (need {min_symbols})"
        if n_dates < min_dates:
            return False, f"Only {n_dates} dates (need {min_dates})"
        return True, None

    return QualityCheck(
        name="coverage",
        level=QualityLevel.WARNING,
        check_fn=check,
        description=f"Require {min_symbols} symbols, {min_dates} dates"
    )
```

### Value Range
```python
def value_range(column: str, min_val: float, max_val: float):
    """Check values are in expected range."""
    async def check(df):
        out_of_range = df[(df[column] < min_val) | (df[column] > max_val)]
        if len(out_of_range) > 0:
            return False, f"{len(out_of_range)} values outside [{min_val}, {max_val}]"
        return True, None

    return QualityCheck(
        name=f"{column}_range",
        level=QualityLevel.WARNING,
        check_fn=check,
        description=f"{column} must be in [{min_val}, {max_val}]"
    )
```

### Schema Conformance
```python
def schema_conformance(expected_schema: pa.Schema):
    """Validate Arrow schema match."""
    async def check(df):
        import pyarrow as pa
        actual = pa.Schema.from_pandas(df)

        missing = set(expected_schema.names) - set(actual.names)
        if missing:
            return False, f"Missing columns: {missing}"

        for field in expected_schema:
            if field.name in actual.names:
                actual_type = actual.field(field.name).type
                if actual_type != field.type:
                    return False, f"{field.name}: expected {field.type}, got {actual_type}"

        return True, None

    return QualityCheck(
        name="schema_conformance",
        level=QualityLevel.CRITICAL,
        check_fn=check,
        description="Schema must match expected Arrow schema"
    )
```

## Validator Composition

```python
class DataQualityValidator:
    """Compose multiple quality checks."""

    def __init__(self):
        self.checks: List[QualityCheck] = []

    def add(self, check: QualityCheck) -> "DataQualityValidator":
        self.checks.append(check)
        return self

    async def validate(self, df) -> List[dict]:
        """Run all checks, return issues."""
        issues = []

        for check in self.checks:
            try:
                passed, message = await check.check_fn(df)
                if not passed:
                    issues.append({
                        "check": check.name,
                        "level": check.level.value,
                        "message": message or check.description
                    })
            except Exception as e:
                issues.append({
                    "check": check.name,
                    "level": "error",
                    "message": str(e)
                })

        return issues

    def has_critical_issues(self, issues: List[dict]) -> bool:
        return any(i["level"] == "critical" for i in issues)
```

## Usage in Pipeline

```python
@task
async def validate_data(df, config) -> bool:
    validator = DataQualityValidator()
    validator.add(no_future_dates(datetime.utcnow()))
    validator.add(no_duplicates(["date", "symbol"]))
    validator.add(coverage_check(min_symbols=100, min_dates=252))

    issues = await validator.validate(df)

    if validator.has_critical_issues(issues):
        # Log and fail
        await emit_quality_failure(issues)
        return False

    if issues:
        # Log warnings but continue
        await emit_quality_warnings(issues)

    return True
```
