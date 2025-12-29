# Point-in-Time (PIT) Patterns

## Core Concept

**PIT correctness prevents lookahead bias** - the model should only see data that was actually available at each point in time.

```
Timeline:
─────────────────────────────────────────────────────────►
Jan 1       Jan 15        Jan 30        Feb 1
│           │             │             │
│           ▼             │             │
│       GDP Q4 estimate   │             │
│       (first release)   ▼             │
│                     GDP Q4 revised     │
│                     (second release)   ▼
│                                    Today
│
▼ as_of_date = Jan 1
  What was known on Jan 15? Only the first estimate.
  What was known on Feb 1? Both estimates, use latest.
```

## Data Model

Always include both timestamps:

```python
@dataclass
class PITRecord:
    as_of_date: date        # When the data is "for" (e.g., Q4 2023)
    knowledge_date: datetime # When we learned this value
    value: float
    source: str
```

## Storage Pattern

```python
class PITStore:
    """Store with vintage tracking."""

    async def append(
        self,
        as_of_date: date,
        data: dict,
        knowledge_date: datetime = None
    ):
        """Append new observation with knowledge timestamp."""
        knowledge_date = knowledge_date or datetime.utcnow()

        record = PITRecord(
            as_of_date=as_of_date,
            knowledge_date=knowledge_date,
            **data
        )
        await self._store.append(record)

    async def query_pit(
        self,
        as_of_date: date,
        knowledge_cutoff: datetime
    ) -> Optional[dict]:
        """Get latest known value as of knowledge_cutoff."""
        records = await self._store.query(
            filter=f"as_of_date = '{as_of_date}' AND knowledge_date <= '{knowledge_cutoff}'",
            order_by="knowledge_date DESC",
            limit=1
        )
        return records[0] if records else None
```

## Accessor Pattern

```python
class PITAccessor:
    """Point-in-time data accessor."""

    async def get(
        self,
        symbols: List[str],
        as_of_dates: List[date],
        knowledge_date: datetime
    ) -> pd.DataFrame:
        """
        Get data as it was known at knowledge_date.

        Args:
            symbols: Securities to fetch
            as_of_dates: Dates to fetch
            knowledge_date: What was known as of this time

        Returns:
            DataFrame with no lookahead bias
        """
        # Query with PIT filter
        query = f"""
            SELECT DISTINCT ON (symbol, as_of_date)
                symbol, as_of_date, close, volume
            FROM prices
            WHERE symbol IN ({symbols})
            AND as_of_date IN ({as_of_dates})
            AND knowledge_date <= '{knowledge_date}'
            ORDER BY symbol, as_of_date, knowledge_date DESC
        """
        return await self._execute(query)
```

## Backtest Integration

```python
async def backtest_step(
    strategy,
    as_of_date: date,
    knowledge_date: datetime  # Usually as_of_date + market_close_time
):
    """Single backtest step with strict PIT."""

    # Get data as known at decision time
    prices = await price_accessor.get(
        symbols=strategy.universe,
        as_of_dates=[as_of_date],
        knowledge_date=knowledge_date
    )

    # Get signals (which internally use PIT for their inputs)
    signals = await signal_accessor.get(
        as_of_date=as_of_date,
        knowledge_date=knowledge_date
    )

    # Generate trades
    return strategy.generate_trades(prices, signals)
```

## Common Pitfalls

### Pitfall 1: Using "latest" data
```python
# BAD - uses future data
df = pd.read_sql("SELECT * FROM prices WHERE date = ?", [date])

# GOOD - respects knowledge boundary
df = await pit_accessor.get(dates=[date], knowledge_date=cutoff)
```

### Pitfall 2: Stale joins
```python
# BAD - joins may bring in future vintages
merged = df1.merge(df2, on="date")

# GOOD - join with matched knowledge dates
merged = pit_join(df1, df2, knowledge_date=cutoff)
```

### Pitfall 3: Corporate actions
```python
# BAD - adjusted prices use future adjustments
df["adj_close"]  # Contains future splits/dividends

# GOOD - use PIT adjustment factors
df["close"] * pit_adj_factor(knowledge_date)
```
