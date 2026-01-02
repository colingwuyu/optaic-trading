"""API Services for Quant Domain.

Services bridge the API layer with domain logic:
1. Load Resources and Extension tables from DB
2. Get Definition.code_ref to identify the implementation
3. Use FACTORY.build(code_ref, config) to instantiate execution objects
4. Execute domain logic
5. Emit activities for audit trail

Key Pattern:
    Service methods follow this flow:
    - Authorize: authorize_or_403(db, actor, Permission.X, resource_id)
    - Load: Get Resource + Extension table (e.g., DatasetInstance)
    - Resolve: Get Definition.code_ref -> Factory key
    - Build: FACTORY.build(code_ref, **config)
    - Execute: Run the built object
    - Emit: record_activity_with_outbox(session, envelope)

Activity Actions:
    Dataset: dataset.created, dataset.previewed, dataset.refresh_started, dataset.refresh_completed
    Signal: signal.registered, signal.validated, signal.promoted
    Pipeline: pipeline_def.submitted, pipeline_def.deployed, pipeline_instance.created, pipeline.run_started
    Experiment: experiment.created, experiment.run_completed, experiment.run_failed, experiment.updated
    Expression: expression.evaluated
    Macro: macro.saved
"""

from apps.api.services.dataset_service import DatasetService
from apps.api.services.experiment_service import ExperimentService
from apps.api.services.op_service import OpService
from apps.api.services.pipeline_service import PipelineService
from apps.api.services.signal_service import SignalService

__all__ = [
    "DatasetService",
    "ExperimentService",
    "OpService",
    "PipelineService",
    "SignalService",
]
