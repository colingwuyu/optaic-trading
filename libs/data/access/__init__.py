"""Data Accessor Implementations.

Accessors provide business logic on top of raw data storage. They handle
data transformations, field selection, and point-in-time (PIT) correctness.

Available Accessors:
- SimpleAccessor: Direct read from store with basic filtering
- PITAccessor: Point-in-time aware access for vintage data
- EconomicsAccessor: Macroeconomic data with revision support
- SQLTableStaticAccessor: Universal SQL table accessor
- GenericSQLAccessor: Custom SQL query accessor
- GenericFuturesAccessor: Continuous futures contract rolling
- FieldsAccessor: Dynamic field (column) selection
- TickerAccessor: Ticker-based data selection
- UniverseSearchAccessor: Search column names using regex

Usage in Definitions:
AccessorDef resources reference accessors by their factory key.
When a DatasetInstance is queried, the system instantiates the accessor
using ACCESSOR_FACTORY.build(code_ref, **config).
"""

from libs.data.access.base import BaseAccessor as BaseAccessor
from libs.data.access.base import BaseRequest as BaseRequest

# Import to register accessors
from libs.data.access import economics as _economics  # noqa: F401
from libs.data.access import fields as _fields  # noqa: F401
from libs.data.access import futures as _futures  # noqa: F401
from libs.data.access import generic as _generic  # noqa: F401
from libs.data.access import pit as _pit  # noqa: F401
from libs.data.access import search as _search  # noqa: F401
from libs.data.access import simple as _simple  # noqa: F401
from libs.data.access import ticker as _ticker  # noqa: F401
