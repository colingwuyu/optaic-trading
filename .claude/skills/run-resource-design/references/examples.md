# Run Resource Examples

Complete examples for each Run type.

## PipelineRun

```python
pipeline_run = {
    "type": "PipelineRun",
    "name": "SPX_OHLCV_refresh_20241231",
    "parent_id": "dataset-instance-uuid",  # Parent is DatasetInstance
    "status": "completed",
    "metadata_json": {
        "started_at": "2024-12-31T06:00:00Z",
        "ended_at": "2024-12-31T06:01:45Z",
        "duration_seconds": 105,

        "trigger": "scheduled",
        "worker_id": "worker-1",

        "metrics_json": {
            "rows_fetched": 500,
            "rows_inserted": 100,
            "rows_updated": 0,
            "last_data_date": "2024-12-31"
        },

        "input_versions": {
            "pipeline_def_version": "v1.2.0"
        }
    }
}
```

## ExperimentRun

```python
experiment_run = {
    "type": "ExperimentRun",
    "name": "alpha_preview_20241231_143022",
    "parent_id": "experiment-instance-uuid",
    "status": "completed",
    "metadata_json": {
        "started_at": "2024-12-31T14:30:22Z",
        "ended_at": "2024-12-31T14:30:25Z",

        "expression": "ZSCORE(REF(close, 5) / close - 1)",
        "preview_params": {
            "start_date": "2023-01-01",
            "end_date": "2024-01-01",
            "entities": ["AAPL", "MSFT", "GOOGL"]
        },

        "metrics_json": {
            "rows_computed": 756,
            "nan_pct": 0.02,
            "mean": 0.001,
            "std": 0.98,
            "min": -2.8,
            "max": 3.2
        },

        "preview_data_ref": "s3://runs/exp123/preview.parquet",

        "input_versions": {
            "close_dataset_version": "version-uuid"
        }
    }
}
```

## BacktestRun

```python
backtest_run = {
    "type": "BacktestRun",
    "name": "Q1_2024_backtest_run_001",
    "parent_id": "backtest-instance-uuid",
    "status": "completed",
    "metadata_json": {
        "started_at": "2024-12-31T10:00:00Z",
        "ended_at": "2024-12-31T10:05:32Z",
        "duration_seconds": 332,

        "date_range": {
            "start": "2024-01-01",
            "end": "2024-03-31"
        },

        "metrics_json": {
            "total_return": 0.152,
            "annualized_return": 0.608,
            "sharpe_ratio": 1.85,
            "sortino_ratio": 2.31,
            "max_drawdown": -0.082,
            "calmar_ratio": 7.41,
            "win_rate": 0.58,
            "profit_factor": 1.92,
            "avg_trade_return": 0.0012,
            "num_trades": 245,
            "turnover": 0.42
        },

        "artifacts_ref": {
            "equity_curve": "s3://runs/bt123/equity_curve.parquet",
            "trades": "s3://runs/bt123/trades.parquet",
            "weights_history": "s3://runs/bt123/weights.parquet",
            "daily_returns": "s3://runs/bt123/returns.parquet"
        },

        "input_versions": {
            "signal_instance_version": "version-uuid",
            "price_dataset_version": "version-uuid",
            "optimizer_instance_version": "version-uuid"
        }
    }
}

# Extension table
backtest_run_ext = {
    "resource_id": "uuid",
    "backtest_instance_id": "backtest-instance-uuid",
    "metrics_json": {...},
    "trades_json": [...],  # For small trade lists
    "equity_curve_ref": "s3://runs/bt123/equity_curve.parquet"
}
```

## PortfolioOptimizationRun

```python
optimization_run = {
    "type": "PortfolioOptimizationRun",
    "name": "mvo_optimization_20241231",
    "parent_id": "optimizer-instance-uuid",
    "status": "completed",
    "metadata_json": {
        "started_at": "2024-12-31T16:00:00Z",
        "ended_at": "2024-12-31T16:00:05Z",

        "weights_json": {
            "AAPL": 0.12,
            "MSFT": 0.15,
            "GOOGL": 0.10,
            "AMZN": 0.08,
            "META": 0.05,
            # ... more weights
        },

        "optimization_metrics_json": {
            "expected_return": 0.12,
            "expected_volatility": 0.18,
            "sharpe_ratio": 0.67,
            "diversification_ratio": 1.45,
            "effective_n": 8.2,
            "concentration": 0.15,
            "solver_status": "optimal",
            "iterations": 42
        },

        "constraints_satisfied": True,
        "active_constraints": ["max_weight", "sum_to_one"],

        "input_versions": {
            "signal_version": "version-uuid",
            "covariance_version": "version-uuid"
        }
    }
}
```

## TrainingRun

```python
training_run = {
    "type": "TrainingRun",
    "name": "xgb_return_predictor_v3_train",
    "parent_id": "model-instance-uuid",
    "status": "completed",
    "metadata_json": {
        "started_at": "2024-12-31T08:00:00Z",
        "ended_at": "2024-12-31T08:45:00Z",

        "training_config": {
            "n_estimators": 200,
            "max_depth": 8,
            "learning_rate": 0.05
        },

        "metrics_json": {
            "train_rmse": 0.015,
            "val_rmse": 0.018,
            "train_r2": 0.85,
            "val_r2": 0.78,
            "feature_importance": {
                "momentum_12m": 0.25,
                "volatility_20d": 0.18,
                "volume_zscore": 0.12
            }
        },

        "artifact_ref": "s3://models/xgb_v3/model.joblib",
        "artifact_version": "v3.0.0",

        "dataset_versions": {
            "features_version": "version-uuid",
            "target_version": "version-uuid"
        }
    }
}
```

## InferenceRun

```python
inference_run = {
    "type": "InferenceRun",
    "name": "xgb_inference_20241231",
    "parent_id": "model-instance-uuid",
    "status": "completed",
    "metadata_json": {
        "started_at": "2024-12-31T16:30:00Z",
        "ended_at": "2024-12-31T16:30:02Z",

        "inference_params": {
            "as_of_date": "2024-12-31",
            "universe": "SP500"
        },

        "metrics_json": {
            "num_predictions": 500,
            "mean_prediction": 0.002,
            "std_prediction": 0.015
        },

        "predictions_ref": "s3://runs/inf123/predictions.parquet",

        "input_versions": {
            "model_version": "v3.0.0",
            "features_version": "version-uuid"
        }
    }
}
```

## MonitoringRun

```python
monitoring_run = {
    "type": "MonitoringRun",
    "name": "model_drift_check_20241231",
    "parent_id": "model-instance-uuid",
    "status": "completed",
    "metadata_json": {
        "started_at": "2024-12-31T17:00:00Z",
        "ended_at": "2024-12-31T17:00:30Z",

        "monitoring_type": "model_drift",  # or "data_quality", "performance"

        "metrics_json": {
            # Data drift
            "feature_drift": {
                "momentum_12m": {"psi": 0.08, "status": "ok"},
                "volatility_20d": {"psi": 0.22, "status": "warning"},
                "volume_zscore": {"psi": 0.05, "status": "ok"}
            },
            "overall_drift_score": 0.12,

            # Model performance
            "prediction_accuracy": {
                "direction_accuracy": 0.54,
                "ic": 0.03,
                "ic_ir": 0.8
            },

            # Data quality
            "data_quality": {
                "missing_pct": 0.001,
                "outlier_pct": 0.02
            }
        },

        "alerts_json": [
            {
                "type": "feature_drift_warning",
                "feature": "volatility_20d",
                "psi": 0.22,
                "threshold": 0.20
            }
        ],

        "report_ref": "s3://runs/mon123/report.html"
    }
}
```

## DB Model Pattern

```python
class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    backtest_instance_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    metrics_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    trades_json: Mapped[list] = mapped_column(JSONType, default=list)
    equity_curve_ref: Mapped[str | None] = mapped_column(String(1024))


class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"

    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    parent_instance_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    monitoring_type: Mapped[str] = mapped_column(String(50))  # model_drift|data_quality|performance
    metrics_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    alerts_json: Mapped[list] = mapped_column(JSONType, default=list)
    report_ref: Mapped[str | None] = mapped_column(String(1024))
```
