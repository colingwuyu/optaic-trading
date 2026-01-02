"""Operator Registry and Implementations.

Operators are pure functions that transform pandas Series/DataFrames.
They are used in expressions like: MEAN($dataset.close, 20)

Usage:
- Operators are registered via @register_op decorator
- OpDef resources reference operators by their factory key
- Expression engine uses OPS_REGISTRY to look up operators

Available operators are organized by category:
- Time Series: REF, DELTA, TS_CONCAT, TS_RANK, TS_ZSCORE, DECAY_LINEAR, etc.
- Statistics: MEAN, STD, CORR, BETA, MAX, MIN
- Math: LOG, ABS, SIGN, ADD, SUB, MUL, DIV, CUMRET
- PIT: VALUES, MERGE_PIT, DROP_META, AS_OF_DATE
- Futures: ROLL_FUTURES, FUTURES_UNIVERSE
"""

from libs.data.ops.core import OPS_REGISTRY as OPS_REGISTRY
from libs.data.ops.core import register_op as register_op

# Import modules to register their operators
from libs.data.ops import futures as _futures  # noqa: F401
from libs.data.ops import ts as _ts  # noqa: F401
