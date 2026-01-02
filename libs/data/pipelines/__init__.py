"""Data Pipeline Implementations.

Pipelines handle data ingestion and transformation. They are the "run" logic
for DatasetInstance resources.

Available Pipelines:
- ExpressionPipeline: Evaluate expressions on other datasets
- FredPipeline: Fetch data from FRED API (requires fredapi package)
- SQLiteUpdatePipeline: Update SQLite database file from production
- BloombergPipeline: Fetch data from Bloomberg Terminal (requires xbbg package)
- OHLCVBloombergPipeline: Pre-configured OHLCV data from Bloomberg

Usage in Definitions:
PipelineDef resources reference pipelines by their factory key.
When a DatasetInstance is refreshed, the system instantiates the pipeline
using PIPELINE_FACTORY.build(code_ref, **config).
"""

from libs.data.pipelines.base import DataPipeline as DataPipeline

# Import to register pipelines
from libs.data.pipelines import bloomberg as _bloomberg  # noqa: F401
from libs.data.pipelines import expression as _expression  # noqa: F401
from libs.data.pipelines import fred as _fred  # noqa: F401
from libs.data.pipelines import sqlite as _sqlite  # noqa: F401
