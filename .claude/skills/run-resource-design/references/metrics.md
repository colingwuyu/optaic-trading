# Standard Metrics by Run Type

Recommended metrics to track for each Run type.

## BacktestRun Metrics

### Return Metrics
| Metric | Description | Formula |
|--------|-------------|---------|
| `total_return` | Cumulative return | Final NAV / Initial NAV - 1 |
| `annualized_return` | Annualized total return | (1 + total_return)^(252/days) - 1 |
| `cagr` | Compound annual growth rate | Same as annualized_return |

### Risk Metrics
| Metric | Description | Target |
|--------|-------------|--------|
| `volatility` | Annualized volatility | Lower is better |
| `max_drawdown` | Maximum peak-to-trough decline | > -20% typically |
| `avg_drawdown` | Average drawdown | |
| `drawdown_duration` | Max days in drawdown | |
| `var_95` | 95% Value at Risk | |
| `cvar_95` | Conditional VaR | |

### Risk-Adjusted Returns
| Metric | Description | Good Range |
|--------|-------------|------------|
| `sharpe_ratio` | Excess return / volatility | > 1.0 |
| `sortino_ratio` | Excess return / downside vol | > 1.5 |
| `calmar_ratio` | CAGR / Max drawdown | > 1.0 |
| `information_ratio` | Alpha / tracking error | > 0.5 |

### Trading Metrics
| Metric | Description |
|--------|-------------|
| `num_trades` | Total trades executed |
| `win_rate` | Winning trades / total |
| `profit_factor` | Gross profit / gross loss |
| `avg_trade_return` | Average per-trade return |
| `turnover` | Annual portfolio turnover |
| `avg_holding_period` | Average position duration |

### Benchmark Metrics
| Metric | Description |
|--------|-------------|
| `alpha` | Excess return vs benchmark |
| `beta` | Sensitivity to benchmark |
| `tracking_error` | Volatility of excess returns |

## PortfolioOptimizationRun Metrics

| Metric | Description |
|--------|-------------|
| `expected_return` | Portfolio expected return |
| `expected_volatility` | Portfolio expected volatility |
| `expected_sharpe` | Expected Sharpe ratio |
| `diversification_ratio` | Weighted avg vol / portfolio vol |
| `effective_n` | Effective number of bets |
| `concentration` | Herfindahl index of weights |
| `gross_exposure` | Sum of absolute weights |
| `net_exposure` | Sum of weights |
| `long_weight` | Sum of positive weights |
| `short_weight` | Sum of negative weights |
| `solver_status` | Optimizer convergence status |
| `iterations` | Solver iterations |

## TrainingRun Metrics

### Regression
| Metric | Description |
|--------|-------------|
| `train_rmse` | Root mean squared error (train) |
| `val_rmse` | RMSE (validation) |
| `train_mae` | Mean absolute error (train) |
| `val_mae` | MAE (validation) |
| `train_r2` | R-squared (train) |
| `val_r2` | R-squared (validation) |
| `train_ic` | Information coefficient (train) |
| `val_ic` | IC (validation) |

### Classification
| Metric | Description |
|--------|-------------|
| `train_accuracy` | Classification accuracy |
| `val_accuracy` | Validation accuracy |
| `train_auc` | Area under ROC curve |
| `val_auc` | Validation AUC |
| `precision` | True positives / predicted positives |
| `recall` | True positives / actual positives |
| `f1` | Harmonic mean of precision/recall |

### Model Info
| Metric | Description |
|--------|-------------|
| `feature_importance` | Dict of feature → importance |
| `num_features` | Number of input features |
| `training_samples` | Training set size |
| `validation_samples` | Validation set size |

## InferenceRun Metrics

| Metric | Description |
|--------|-------------|
| `num_predictions` | Count of predictions made |
| `mean_prediction` | Average prediction value |
| `std_prediction` | Prediction standard deviation |
| `confidence_mean` | Average prediction confidence |
| `latency_ms` | Inference latency |

## MonitoringRun Metrics

### Data Drift
| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `psi` | Population Stability Index | > 0.20 |
| `ks_statistic` | Kolmogorov-Smirnov statistic | > 0.10 |
| `drift_score` | Overall drift score | Context-dependent |

### Model Performance
| Metric | Description |
|--------|-------------|
| `direction_accuracy` | Realized direction accuracy |
| `ic` | Realized information coefficient |
| `ic_ir` | IC information ratio |
| `hit_rate` | Realized prediction hit rate |

### Data Quality
| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `missing_pct` | Percentage missing values | > 1% |
| `outlier_pct` | Percentage outliers | > 5% |
| `duplicate_pct` | Percentage duplicates | > 0% |
| `staleness_hours` | Hours since last update | Context-dependent |

## PipelineRun Metrics

| Metric | Description |
|--------|-------------|
| `rows_fetched` | Rows retrieved from source |
| `rows_inserted` | New rows inserted |
| `rows_updated` | Existing rows updated |
| `rows_deleted` | Rows removed |
| `last_data_date` | Most recent data date |
| `duration_seconds` | Pipeline execution time |
| `bytes_processed` | Data volume processed |

## ExperimentRun Metrics

| Metric | Description |
|--------|-------------|
| `rows_computed` | Result set size |
| `nan_pct` | Percentage NaN values |
| `mean` | Mean of computed values |
| `std` | Standard deviation |
| `min` | Minimum value |
| `max` | Maximum value |
| `skewness` | Distribution skewness |
| `kurtosis` | Distribution kurtosis |
