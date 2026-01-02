---
trigger: model_decision
description: Agent trigger: Load this file when implementing MLOps features, ML model definitions, training/inference pipelines, model registry, or monitoring.
---

# MLOps Patterns Rules

Guide for implementing MLOps features in OptAIC.

## 1. MLOps Three-Tier Model

`
MLModuleDef (Definition)    ModelInstance (Config)       Execution (Runs)
------------------------   ----------------------       ----------------
XGBSignalModelDef       -> SPX_Alpha_Model          ->  TrainingRun
  (5 code components)       (datasets + config)         InferenceRun
                                                        MonitoringRun
`

## 2. ML Model Categories

| Category | Purpose | Typical Outputs |
|----------|---------|-----------------|
| Signal Model | Generate alpha signals | Signal dataset [-1, 1] |
| Macro Regime Model | Classify market regimes | Regime labels/probabilities |
| Relevance Model | Score feature importance | Relevance scores |
| Signal Combining Model | Combine multiple signals | Combined signal |
| Signal Filtering Model | Filter/rank signals | Filtered signal set |

## 3. MLModuleDef Structure (5 Components)

`
MLModelDef/
 model/           # Model architecture + hyperparameter schema
 training/        # Trainer + evaluator
 inference/       # Predictor + batch inference
 monitoring/      # Data drift + performance monitoring
 tests/           # Test suite for all components
`

## 4. Tech Stack

| Tool | Purpose | Mode |
|------|---------|------|
| MLflow | Experiment tracking, model registry | Optional (--with-mlflow) |
| Evidently | Data drift, performance monitoring | Always available |
| Prefect | Workflow orchestration | Optional (--with-prefect) |

## 5. Critical Rules

1. **5-component structure** - MLModuleDef must have model, training, inference, monitoring, tests
2. **Activity emission** - All runs emit activities
3. **Lineage tracking** - Link dataset versions -> model version -> predictions
4. **Guardrails** - Validate model outputs
5. **PIT correctness** - No lookahead in training or inference

## 6. References

See `.claude/skills/mlops-patterns/` for complete patterns:
- `SKILL.md` - Full MLOps implementation guide
- `references/unified-sdk.md` - optaic.mlops SDK patterns
- `references/mlmodule-structure.md` - 5-component package
- `references/mlops-pipelines.md` - Training/inference/monitoring
- `references/mlflow-evidently-integration.md` - Experiment tracking & monitoring
