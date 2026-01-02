# Instance Resource Examples

Complete examples for each Instance type.

## DatasetInstance: SPX OHLCV

```python
spx_ohlcv_dataset = {
    "type": "DatasetInstance",
    "name": "SPX_OHLCV_Daily",
    "parent_id": "project-uuid",
    "status": "active",
    "metadata_json": {
        # Composition references
        "pipeline_instance_id": "bloomberg-pipeline-instance-uuid",
        "store_instance_id": "parquet-store-instance-uuid",
        "accessor_instance_id": "pit-accessor-instance-uuid",

        # Freshness tracking
        "freshness_status": "fresh",
        "last_data_date": "2024-12-31",
        "last_refresh_at": "2024-12-31T18:30:00Z",
        "row_count": 25000
    }
}

# Extension table record
dataset_instance_ext = {
    "resource_id": "uuid",
    "pipeline_instance_id": "bloomberg-pipeline-instance-uuid",
    "store_instance_id": "parquet-store-instance-uuid",
    "accessor_instance_id": "pit-accessor-instance-uuid",
    "freshness_status": "fresh",
    "last_data_date": date(2024, 12, 31),
    "row_count": 25000
}
```

## SignalInstance: Momentum

```python
momentum_signal = {
    "type": "SignalInstance",
    "name": "12M_Momentum",
    "parent_id": "project-uuid",
    "status": "active",
    "space_kind": "team",
    "subspace_kind": "official",  # Promoted to official
    "metadata_json": {
        # Inherits from DatasetInstance pattern
        "pipeline_instance_id": "expression-pipeline-instance-uuid",
        "store_instance_id": "parquet-store-instance-uuid",
        "accessor_instance_id": "simple-accessor-instance-uuid",

        # Signal-specific spec
        "signal_spec": {
            "min_value": -1.0,
            "max_value": 1.0,
            "allow_nan": False,
            "neutral_value": 0.0,
            "index_schema": {
                "columns": ["date", "entity"],
                "date_frequency": "daily"
            }
        },

        # Source expression
        "expression": "ZSCORE(DELTA(close, 252))",
        "input_datasets": ["price-dataset-uuid"]
    }
}

# Extension table record
signal_spec_ext = {
    "resource_id": "uuid",
    "min_value": -1.0,
    "max_value": 1.0,
    "allow_nan": False,
    "neutral_value": 0.0,
    "index_schema_json": {"columns": ["date", "entity"]}
}
```

## ExperimentInstance: Alpha Research

```python
alpha_experiment = {
    "type": "ExperimentInstance",
    "name": "Mean_Reversion_Alpha",
    "parent_id": "project-uuid",
    "status": "draft",
    "space_kind": "personal",
    "subspace_kind": "staging",
    "metadata_json": {
        "expression": "ZSCORE(REF(close, 5) / close - 1)",
        "input_datasets": {
            "close": "price-dataset-uuid"
        },
        "preview_config": {
            "date_range": {"start": "2023-01-01", "end": "2024-01-01"},
            "universe": ["SPY", "QQQ", "IWM"]
        }
    }
}

# Extension table record
experiment_instance_ext = {
    "resource_id": "uuid",
    "expression_text": "ZSCORE(REF(close, 5) / close - 1)",
    "input_datasets_json": {"close": "price-dataset-uuid"}
}
```

## ModelInstance: XGBoost

```python
xgboost_model = {
    "type": "ModelInstance",
    "name": "Return_Predictor_v3",
    "parent_id": "project-uuid",
    "status": "active",
    "metadata_json": {
        "definition_resource_id": "xgboost-module-def-uuid",
        "definition_version_id": "version-uuid",

        "config_json": {
            "n_estimators": 200,
            "max_depth": 8,
            "learning_rate": 0.05,
            "feature_columns": ["momentum_12m", "volatility_20d", "volume_zscore"]
        },

        "artifact_path": "s3://optaic-models/xgb_return_v3/",
        "training_dataset_id": "training-data-uuid",
        "last_trained_at": "2024-12-15T10:00:00Z"
    }
}

# Extension table record
model_instance_ext = {
    "resource_id": "uuid",
    "definition_resource_id": "xgboost-module-def-uuid",
    "config_json": {...},
    "artifact_path": "s3://optaic-models/xgb_return_v3/"
}
```

## PortfolioOptimizerInstance: MVO

```python
mvo_optimizer = {
    "type": "PortfolioOptimizerInstance",
    "name": "Conservative_MVO",
    "parent_id": "project-uuid",
    "status": "active",
    "metadata_json": {
        "definition_resource_id": "mvo-optimizer-def-uuid",

        "config_json": {
            "solver": "ECOS",
            "risk_aversion": 2.0
        },

        "constraints_json": {
            "sum_to_one": True,
            "min_weight": 0.0,
            "max_weight": 0.15,
            "max_gross_leverage": 1.0,
            "sector_limits": {
                "Technology": 0.3,
                "Financials": 0.25
            }
        },

        "input_signal_ids": ["momentum-signal-uuid"],
        "covariance_dataset_id": "cov-matrix-uuid"
    }
}

# Extension table record
portfolio_optimizer_instance_ext = {
    "resource_id": "uuid",
    "definition_resource_id": "mvo-optimizer-def-uuid",
    "constraints_json": {...},
    "config_json": {...}
}
```

## BacktestInstance: No Definition

```python
backtest_instance = {
    "type": "BacktestInstance",
    "name": "Q1_2024_Momentum_Backtest",
    "parent_id": "project-uuid",
    "status": "active",
    "metadata_json": {
        # No definition_resource_id - procedure is fixed

        "assets_json": {
            "universe_dataset_id": "sp500-constituents-uuid",
            "benchmark": "SPY"
        },

        "signals_json": {
            "primary": "momentum-signal-uuid",
            "secondary": [],
            "optimizer_instance_id": "mvo-optimizer-uuid"
        },

        "date_range_json": {
            "start": "2024-01-01",
            "end": "2024-03-31",
            "frequency": "daily"
        },

        "config_json": {
            "rebalance_frequency": "weekly",
            "rebalance_day": "friday",
            "transaction_costs": {
                "commission": 0.001,
                "slippage": 0.0005
            },
            "initial_capital": 1000000
        }
    }
}

# Extension table record
backtest_instance_ext = {
    "resource_id": "uuid",
    "assets_json": {...},
    "signals_json": {...},
    "date_range_json": {...},
    "config_json": {...}
}
```

## DB Model Pattern

```python
# libs/db/models/quant.py

class DatasetInstance(Base):
    __tablename__ = "dataset_instances"

    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    pipeline_instance_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))
    store_instance_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))
    accessor_instance_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))
    freshness_status: Mapped[str] = mapped_column(String(50), default="unknown")
    last_data_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class BacktestInstance(Base):
    __tablename__ = "backtest_instances"

    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    assets_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    signals_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    date_range_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    config_json: Mapped[dict] = mapped_column(JSONType, default=dict)
```
