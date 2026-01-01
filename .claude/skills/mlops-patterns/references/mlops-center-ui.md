# MLOps Center UI Architecture

Two-view architecture for the MLOps Center in OptAIC's web UI.

## Overview

The MLOps Center is the **real instance hub** for ML models, analogous to Dataset Inventory for datasets. It provides two main views:

1. **Model Instance View** - List and manage registered model instances
2. **Model Execution/Operation View** - Monitor training, inference, and model health

## View 1: Model Instance View

### Purpose
Display registered model instances with their configurations, datasets, and current status.

### Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MLOps Center                                            [+ New Model]      │
├─────────────────────────────────────────────────────────────────────────────┤
│  [Model Instances]  [Executions]                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  🟢 SPX_Alpha_Signal_Model                          v2.3.1 (prod)   │   │
│  │  XGBoost signal model for SPX alpha generation                      │   │
│  │  ─────────────────────────────────────────────────────────────────  │   │
│  │  Definition: xgb-signal-model@2.1.0                                 │   │
│  │  Training: SPX_Features, SPX_Returns → Weekly                       │   │
│  │  Inference: SPX_Features → Daily 6pm                                │   │
│  │  Output: SPX_Alpha_Signal                                           │   │
│  │  ─────────────────────────────────────────────────────────────────  │   │
│  │  IC: 0.082 | Last trained: 2h ago | Next: Sun 00:00                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  🟡 Market_Regime_Classifier                        v1.1.0 (staging)│   │
│  │  LSTM model for regime classification                               │   │
│  │  ...                                                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Model Instance Card Components

```typescript
// apps/web/src/components/mlops/ModelInstanceCard.tsx
interface ModelInstanceCardProps {
  instance: {
    id: string;
    name: string;
    description: string;
    status: 'pending' | 'training' | 'ready' | 'error';

    // Definition reference
    modelDefId: string;
    modelDefName: string;
    modelDefVersion: string;

    // Datasets
    trainingDatasets: DatasetRef[];
    inferenceDatasets: DatasetRef[];
    outputDataset: DatasetRef;

    // Current version
    activeVersion: {
      id: string;
      version: string;
      stage: 'staging' | 'production' | 'archived';
      metrics: Record<string, number>;
      promotedAt: string | null;
    } | null;

    // Schedule
    schedule: {
      training: ScheduleConfig;
      inference: ScheduleConfig;
    };

    // Metadata
    ownerId: string;
    createdAt: string;
    updatedAt: string;
  };
}

function ModelInstanceCard({ instance }: ModelInstanceCardProps) {
  const statusColor = {
    pending: 'yellow',
    training: 'blue',
    ready: 'green',
    error: 'red',
  }[instance.status];

  return (
    <Card>
      <CardHeader>
        <StatusIndicator color={statusColor} />
        <Title>{instance.name}</Title>
        <VersionBadge
          version={instance.activeVersion?.version}
          stage={instance.activeVersion?.stage}
        />
      </CardHeader>

      <CardBody>
        <Description>{instance.description}</Description>

        <Section title="Definition">
          <Link to={`/definitions/${instance.modelDefId}`}>
            {instance.modelDefName}@{instance.modelDefVersion}
          </Link>
        </Section>

        <Section title="Datasets">
          <DatasetList label="Training" datasets={instance.trainingDatasets} />
          <DatasetList label="Inference" datasets={instance.inferenceDatasets} />
          <DatasetLink label="Output" dataset={instance.outputDataset} />
        </Section>

        <Section title="Schedule">
          <ScheduleDisplay
            training={instance.schedule.training}
            inference={instance.schedule.inference}
          />
        </Section>

        <MetricsBar metrics={instance.activeVersion?.metrics} />
      </CardBody>

      <CardActions>
        <Button onClick={() => triggerTraining(instance.id)}>Train Now</Button>
        <Button onClick={() => triggerInference(instance.id)}>Run Inference</Button>
        <Button onClick={() => openExecutions(instance.id)}>View Executions</Button>
      </CardActions>
    </Card>
  );
}
```

### New Model Instance Form

```typescript
// apps/web/src/components/mlops/NewModelInstanceForm.tsx
interface NewModelInstanceFormData {
  name: string;
  description: string;

  // Definition selection
  modelDefId: string;
  modelDefVersion: string;

  // Dataset selection
  trainingDatasetIds: string[];
  inferenceDatasetIds: string[];
  outputDatasetId: string;

  // Configuration
  config: {
    targetCol: string;
    featureCols: string[] | null;
    featureLag: number;
    trainWindow: number;
  };

  // Schedule
  trainingSchedule: {
    cron: string;
    enabled: boolean;
  };
  inferenceSchedule: {
    cron: string;
    enabled: boolean;
  };
}
```

## View 2: Model Execution/Operation View

### Purpose
Monitor and manage the operational aspects of a specific model instance.

### Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ← Back to Models    SPX_Alpha_Signal_Model                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  [Training]  [Registry]  [Inference]  [Monitoring]                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Training History                                          [Train Now ▶]   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Run #42  │  ✅ Completed  │  2024-12-29 00:00  │  IC: 0.082        │   │
│  │  Run #41  │  ✅ Completed  │  2024-12-22 00:00  │  IC: 0.079        │   │
│  │  Run #40  │  ❌ Failed     │  2024-12-15 00:00  │  OOM error        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Training Metrics                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  [Chart: IC over time]                                              │   │
│  │  [Chart: Loss curves]                                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Tab Components

#### Training Tab
```typescript
// apps/web/src/components/mlops/TrainingTab.tsx
interface TrainingTabProps {
  modelInstanceId: string;
  trainingRuns: TrainingRun[];
}

function TrainingTab({ modelInstanceId, trainingRuns }: TrainingTabProps) {
  return (
    <div>
      <Header>
        <Title>Training History</Title>
        <Button onClick={() => triggerTraining(modelInstanceId)}>
          Train Now
        </Button>
      </Header>

      <TrainingRunsTable runs={trainingRuns} />

      <MetricsCharts>
        <ICHistoryChart runs={trainingRuns} />
        <LossCurvesChart runs={trainingRuns} />
        <HyperparamsComparison runs={trainingRuns} />
      </MetricsCharts>
    </div>
  );
}
```

#### Registry Tab
```typescript
// apps/web/src/components/mlops/RegistryTab.tsx
interface RegistryTabProps {
  modelInstanceId: string;
  versions: ModelVersion[];
  activeVersionId: string | null;
}

function RegistryTab({ modelInstanceId, versions, activeVersionId }: RegistryTabProps) {
  return (
    <div>
      <Header>
        <Title>Model Versions</Title>
      </Header>

      <VersionsTable>
        {versions.map(version => (
          <VersionRow key={version.id}>
            <VersionNumber>{version.version}</VersionNumber>
            <StageBadge stage={version.stage} />
            <Metrics>{formatMetrics(version.metrics)}</Metrics>
            <CreatedAt>{version.createdAt}</CreatedAt>
            <Actions>
              {version.stage === 'staging' && (
                <Button onClick={() => promote(version.id)}>
                  Promote to Production
                </Button>
              )}
              {version.stage === 'archived' && (
                <Button onClick={() => rollback(modelInstanceId, version.id)}>
                  Rollback to This
                </Button>
              )}
              {version.id === activeVersionId && (
                <Badge>Active</Badge>
              )}
            </Actions>
          </VersionRow>
        ))}
      </VersionsTable>

      <ComparisonView>
        <VersionComparisonChart versions={versions} />
      </ComparisonView>
    </div>
  );
}
```

#### Inference Tab
```typescript
// apps/web/src/components/mlops/InferenceTab.tsx
interface InferenceTabProps {
  modelInstanceId: string;
  inferenceRuns: InferenceRun[];
  endpointStatus: EndpointStatus | null;
}

function InferenceTab({ modelInstanceId, inferenceRuns, endpointStatus }: InferenceTabProps) {
  return (
    <div>
      <Header>
        <Title>Inference</Title>
        <Button onClick={() => triggerInference(modelInstanceId)}>
          Run Inference Now
        </Button>
      </Header>

      {/* Endpoint status (if real-time inference enabled) */}
      {endpointStatus && (
        <EndpointCard>
          <EndpointUrl>{endpointStatus.url}</EndpointUrl>
          <StatusIndicator status={endpointStatus.status} />
          <LatencyMetrics p50={endpointStatus.p50ms} p99={endpointStatus.p99ms} />
          <RequestCount>{endpointStatus.requestsToday}</RequestCount>
        </EndpointCard>
      )}

      {/* Batch inference history */}
      <InferenceRunsTable runs={inferenceRuns} />

      <InferenceMetrics>
        <LatencyChart runs={inferenceRuns} />
        <ThroughputChart runs={inferenceRuns} />
      </InferenceMetrics>
    </div>
  );
}
```

#### Monitoring Tab
```typescript
// apps/web/src/components/mlops/MonitoringTab.tsx
interface MonitoringTabProps {
  modelInstanceId: string;
  driftReports: DriftReport[];
  perfReports: PerformanceReport[];
  alerts: Alert[];
}

function MonitoringTab({
  modelInstanceId,
  driftReports,
  perfReports,
  alerts,
}: MonitoringTabProps) {
  return (
    <div>
      <Header>
        <Title>Monitoring</Title>
      </Header>

      {/* Active alerts */}
      <AlertsSection>
        {alerts.filter(a => a.active).map(alert => (
          <AlertCard key={alert.id} alert={alert} />
        ))}
      </AlertsSection>

      {/* Data drift monitoring */}
      <Section title="Data Drift">
        <DriftHeatmap reports={driftReports} />
        <FeatureDistributionCharts reports={driftReports} />
      </Section>

      {/* Performance monitoring */}
      <Section title="Model Performance">
        <PerformanceChart reports={perfReports} />
        <RealizedVsPredictedChart reports={perfReports} />
        <DegradationIndicator reports={perfReports} />
      </Section>

      {/* Monitoring configuration */}
      <Section title="Alert Configuration">
        <AlertRulesEditor modelInstanceId={modelInstanceId} />
      </Section>
    </div>
  );
}
```

## State Management (Zustand)

```typescript
// apps/web/src/stores/mlopsStore.ts
import { create } from 'zustand';

interface MLOpsStore {
  // Model instances
  modelInstances: ModelInstance[];
  selectedInstanceId: string | null;

  // Execution data for selected instance
  trainingRuns: TrainingRun[];
  inferenceRuns: InferenceRun[];
  modelVersions: ModelVersion[];
  driftReports: DriftReport[];
  perfReports: PerformanceReport[];

  // Actions
  fetchModelInstances: () => Promise<void>;
  selectInstance: (id: string) => void;
  fetchExecutionData: (instanceId: string) => Promise<void>;
  triggerTraining: (instanceId: string) => Promise<void>;
  triggerInference: (instanceId: string, asOfDate: string) => Promise<void>;
  promoteVersion: (versionId: string) => Promise<void>;
  rollbackVersion: (instanceId: string, targetVersionId: string) => Promise<void>;
}

export const useMLOpsStore = create<MLOpsStore>((set, get) => ({
  modelInstances: [],
  selectedInstanceId: null,
  trainingRuns: [],
  inferenceRuns: [],
  modelVersions: [],
  driftReports: [],
  perfReports: [],

  fetchModelInstances: async () => {
    const response = await api.get('/mlops/instances');
    set({ modelInstances: response.data });
  },

  selectInstance: (id) => {
    set({ selectedInstanceId: id });
    get().fetchExecutionData(id);
  },

  fetchExecutionData: async (instanceId) => {
    const [training, inference, versions, drift, perf] = await Promise.all([
      api.get(`/mlops/instances/${instanceId}/training-runs`),
      api.get(`/mlops/instances/${instanceId}/inference-runs`),
      api.get(`/mlops/instances/${instanceId}/versions`),
      api.get(`/mlops/instances/${instanceId}/drift-reports`),
      api.get(`/mlops/instances/${instanceId}/performance-reports`),
    ]);

    set({
      trainingRuns: training.data,
      inferenceRuns: inference.data,
      modelVersions: versions.data,
      driftReports: drift.data,
      perfReports: perf.data,
    });
  },

  // ... other actions
}));
```

## Real-Time Updates

Subscribe to activity events via Centrifugo for live updates:

```typescript
// apps/web/src/hooks/useMLOpsSubscription.ts
import { useCentrifugo } from './useCentrifugo';
import { useMLOpsStore } from '../stores/mlopsStore';

export function useMLOpsSubscription(modelInstanceId: string) {
  const { subscribe } = useCentrifugo();
  const { fetchExecutionData } = useMLOpsStore();

  useEffect(() => {
    const channel = `resource:${modelInstanceId}`;

    const unsubscribe = subscribe(channel, (event) => {
      // Handle real-time events
      switch (event.action) {
        case 'training.started':
        case 'training.completed':
        case 'training.failed':
        case 'inference.completed':
        case 'model_version.created':
        case 'model_version.promoted':
        case 'monitoring.drift_alert':
        case 'monitoring.performance_alert':
          // Refresh execution data
          fetchExecutionData(modelInstanceId);
          break;
      }
    });

    return unsubscribe;
  }, [modelInstanceId]);
}
```

## Navigation Structure

```
/mlops
├── /                          # Model Instance View (list)
├── /new                       # New Model Instance form
└── /:instanceId
    ├── /                      # Redirect to /training
    ├── /training              # Training tab
    ├── /registry              # Registry tab
    ├── /inference             # Inference tab
    └── /monitoring            # Monitoring tab
```
