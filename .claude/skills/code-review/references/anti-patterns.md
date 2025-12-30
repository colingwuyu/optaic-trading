# Anti-Patterns to Flag in Code Review

## Activity Logging Anti-Patterns

### ❌ Activity in API Handler
```python
# WRONG - API layer should not emit activities
@router.post("/signals")
async def create_signal(dto: SignalCreateDTO):
    signal = await signal_service.create(dto)
    # DON'T DO THIS HERE
    await record_activity(action="signal.created", ...)
    return signal
```

### ❌ Missing Activity on Mutation
```python
# WRONG - Update without activity
async def update(self, signal_id: UUID, dto: SignalUpdateDTO):
    signal = await self._get_or_404(signal_id)
    signal.config = dto.config
    # Missing: record_activity_with_outbox(...)
    return signal
```

---

## Guardrails Anti-Patterns

### ❌ Skipping Validation
```python
# WRONG - No guardrails at create gate
async def create(self, dto: SignalCreateDTO):
    signal = await self._create(dto)
    # Missing: GuardrailsEngine.validate_at_gate()
    return signal
```

### ❌ Hardcoded Enforcement
```python
# WRONG - Should use policy
if not report.ok:
    raise ValidationError()  # Always blocks

# CORRECT - Policy-driven
if not report.ok and report.enforced_as == "block":
    raise GuardrailsBlocked(report)
```

---

## PIT Anti-Patterns

### ❌ Missing knowledge_date
```python
# WRONG - Only effective date
schema = pa.schema([
    pa.field("date", pa.date32()),
    pa.field("value", pa.float64()),
    # Missing: knowledge_date
])
```

### ❌ Lookahead Query
```python
# WRONG - Can access future data
df = pd.read_sql("SELECT * FROM prices WHERE date = ?", [target_date])

# CORRECT - PIT safe
df = pd.read_sql("""
    SELECT * FROM prices
    WHERE as_of_date <= ? AND knowledge_date <= ?
""", [target_date, knowledge_cutoff])
```

---

## Import Anti-Patterns

### ❌ Heavy Imports at Module Level
```python
# WRONG - Breaks optaic[sdk] install
import pandas as pd
import numpy as np
import torch

class SignalService:
    ...
```

### ✅ Correct Lazy Import
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

def process_data(df: "pd.DataFrame"):
    import pandas as pd  # Runtime import
    ...
```

---

## DTO Anti-Patterns

### ❌ Exposing SQLAlchemy Models
```python
# WRONG - Leaks ORM to API
@router.get("/signals/{id}")
async def get_signal(id: UUID) -> Signal:  # SQLAlchemy model!
    return await signal_repo.get(id)
```

### ✅ Correct DTO Pattern
```python
@router.get("/signals/{id}")
async def get_signal(id: UUID) -> SignalReadDTO:  # Pydantic DTO
    signal = await signal_repo.get(id)
    return SignalReadDTO.model_validate(signal)
```
