# Definition Resource Examples

Complete examples for each Definition type.

## PipelineDef: Bloomberg Data

```python
bloomberg_pipeline_def = {
    "type": "PipelineDef",
    "name": "BloombergEquityPipeline",
    "status": "official",
    "metadata_json": {
        "interface_spec": "optaic.interfaces.BasePipeline",
        "version": "1.0.0",
        "category": "etl",
        "code_ref": "s3://optaic-plugins/pipelines/bloomberg_v1.py",

        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {"type": "array", "items": {"type": "string"}},
                "fields": {"type": "array", "items": {"type": "string"}},
                "start_date": {"type": "string", "format": "date"}
            },
            "required": ["symbols", "fields"]
        },

        "output_schema": {
            "type": "DataFrame",
            "columns": [
                {"name": "date", "dtype": "datetime64[ns]"},
                {"name": "symbol", "dtype": "string"},
                {"name": "field", "dtype": "string"},
                {"name": "value", "dtype": "float64"}
            ]
        },

        "parameters_schema": {
            "type": "object",
            "properties": {
                "api_key_ref": {"type": "string", "format": "secret-ref"},
                "rate_limit": {"type": "integer", "default": 100}
            },
            "required": ["api_key_ref"]
        },

        "guardrail_contracts": [
            {
                "kind": "pit.policy",
                "config": {"knowledge_date_required": True},
                "enforcement": "block"
            }
        ],

        "compatibility_rules": {
            "upstream_types": [],
            "downstream_types": ["DatasetInstance"]
        }
    }
}
```

## OpDef: Rolling Mean

```python
rolling_mean_op_def = {
    "type": "OpDef",
    "name": "MEAN",
    "status": "official",
    "metadata_json": {
        "interface_spec": "optaic.interfaces.BaseOperator",
        "version": "1.0.0",
        "category": "rolling",
        "signature": "MEAN(x: Series, window: int) -> Series",

        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "Series"},
                "window": {"type": "integer", "minimum": 1}
            },
            "required": ["x", "window"]
        },

        "output_schema": {
            "type": "Series",
            "dtype": "float64",
            "constraints": {"same_index_as_input": True}
        },

        "parameters_schema": {
            "type": "object",
            "properties": {
                "min_periods": {"type": "integer", "default": 1}
            }
        }
    }
}
```

## PortfolioOptimizerDef: Mean-Variance

```python
mvo_optimizer_def = {
    "type": "PortfolioOptimizerDef",
    "name": "MeanVarianceOptimizer",
    "status": "official",
    "metadata_json": {
        "interface_spec": "optaic.interfaces.BaseOptimizer",
        "version": "1.0.0",
        "algorithm_type": "convex",
        "code_ref": "s3://optaic-plugins/optimizers/mvo_v1.py",

        "input_schema": {
            "type": "object",
            "properties": {
                "signals": {
                    "type": "DataFrame",
                    "columns": ["date", "entity", "value"]
                },
                "covariance": {"type": "DataFrame"},
                "risk_aversion": {"type": "number", "minimum": 0}
            },
            "required": ["signals"]
        },

        "output_schema": {
            "type": "object",
            "properties": {
                "weights": {"type": "Series"},
                "expected_return": {"type": "number"},
                "expected_risk": {"type": "number"}
            }
        },

        "parameters_schema": {
            "type": "object",
            "properties": {
                "solver": {"type": "string", "enum": ["ECOS", "SCS", "OSQP"]},
                "max_iterations": {"type": "integer", "default": 1000}
            }
        },

        "guardrail_contracts": [
            {
                "kind": "portfolio.weights",
                "config": {
                    "sum_to_one": True,
                    "min_weight": -0.1,
                    "max_weight": 0.2,
                    "allow_short": True
                },
                "enforcement": "block"
            },
            {
                "kind": "portfolio.leverage",
                "config": {"max_gross": 2.0, "max_net": 1.0},
                "enforcement": "block"
            }
        ],

        "compatibility_rules": {
            "upstream_types": ["SignalInstance", "DatasetInstance"],
            "downstream_types": ["PortfolioOptimizerInstance"]
        }
    }
}
```

## MLModuleDef: XGBoost Regressor

```python
xgboost_module_def = {
    "type": "MLModuleDef",
    "name": "XGBoostRegressor",
    "status": "official",
    "metadata_json": {
        "interface_spec": "optaic.interfaces.BaseMLModule",
        "version": "1.0.0",
        "module_type": "regressor",
        "code_ref": "s3://optaic-plugins/ml/xgboost_v1.py",

        "input_schema": {
            "type": "object",
            "properties": {
                "features": {"type": "DataFrame"},
                "target": {"type": "Series"}
            },
            "required": ["features", "target"]
        },

        "output_schema": {
            "type": "object",
            "properties": {
                "predictions": {"type": "Series"},
                "feature_importance": {"type": "dict"}
            }
        },

        "parameters_schema": {
            "type": "object",
            "properties": {
                "n_estimators": {"type": "integer", "default": 100},
                "max_depth": {"type": "integer", "default": 6},
                "learning_rate": {"type": "number", "default": 0.1}
            }
        },

        "guardrail_contracts": [
            {
                "kind": "ml.validation",
                "config": {
                    "require_train_test_split": True,
                    "min_samples": 100
                },
                "enforcement": "warn"
            }
        ]
    }
}
```

## DB Model Pattern

```python
# libs/db/models/quant.py

class PipelineDefinition(Base):
    __tablename__ = "pipeline_definitions"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(100))
    interface_spec: Mapped[str] = mapped_column(String(255))
    code_ref: Mapped[str | None] = mapped_column(String(1024))
    input_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    compatibility_rules: Mapped[dict] = mapped_column(JSONType, default=dict)
    guardrail_contracts: Mapped[list] = mapped_column(JSONType, default=list)
    parameters_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
```
