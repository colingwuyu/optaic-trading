from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Type

from pydantic import BaseModel, Field


class DatasetContent(BaseModel):
    pipeline_refs: list[str] = Field(default_factory=list)
    store_refs: list[str] = Field(default_factory=list)
    accessor_refs: list[str] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)


class ExperimentContent(BaseModel):
    tabs: list[Dict[str, Any]] = Field(default_factory=list)
    expressions: list[str] = Field(default_factory=list)


class ExtensionContent(BaseModel):
    files: list[Dict[str, Any]] = Field(default_factory=list)
    tests: list[Dict[str, Any]] = Field(default_factory=list)


class OpsMacroContent(BaseModel):
    signature: str = ""
    body: str = ""


class ProjectContent(BaseModel):
    refs: Dict[str, Any] = Field(default_factory=dict)


_VERSIONED_TYPES: dict[str, Type[BaseModel]] = {
    "Dataset": DatasetContent,
    "Experiment": ExperimentContent,
    "Extension": ExtensionContent,
    "OpsMacro": OpsMacroContent,
    "Project": ProjectContent,
}

_MERGE_STRATEGIES = {"source_wins", "target_wins"}
_MergeFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


def is_versioned_type(resource_type: str) -> bool:
    return resource_type in _VERSIONED_TYPES


def get_content_model(resource_type: str) -> Optional[Type[BaseModel]]:
    return _VERSIONED_TYPES.get(resource_type)


def serialize_content(
    resource_type: str, content: BaseModel | Dict[str, Any]
) -> Dict[str, Any]:
    model_type = get_content_model(resource_type)
    if model_type is None:
        raise ValueError(f"Resource type '{resource_type}' is not versioned")
    if isinstance(content, BaseModel):
        return content.model_dump()
    return model_type.model_validate(content).model_dump()


def deserialize_content(resource_type: str, payload: Dict[str, Any]) -> BaseModel:
    model_type = get_content_model(resource_type)
    if model_type is None:
        raise ValueError(f"Resource type '{resource_type}' is not versioned")
    return model_type.model_validate(payload)


def default_content(resource_type: str) -> Dict[str, Any]:
    model_type = get_content_model(resource_type)
    if model_type is None:
        raise ValueError(f"Resource type '{resource_type}' is not versioned")
    return model_type().model_dump()


def _merge_strategy(target: Dict[str, Any], source: Dict[str, Any]) -> str:
    for payload in (source, target):
        config = payload.get("config")
        if isinstance(config, dict):
            strategy = config.get("merge_strategy")
            if isinstance(strategy, str) and strategy in _MERGE_STRATEGIES:
                return strategy
    return "source_wins"


def _merge_source_wins(
    target: Dict[str, Any], source: Dict[str, Any]
) -> Dict[str, Any]:
    merged = dict(target)
    merged.update(source)
    return merged


def _merge_target_wins(
    target: Dict[str, Any], source: Dict[str, Any]
) -> Dict[str, Any]:
    merged = dict(source)
    merged.update(target)
    return merged


_MERGE_FNS: dict[str, _MergeFn] = {
    "Dataset": _merge_source_wins,
    "Experiment": _merge_source_wins,
    "Extension": _merge_source_wins,
    "OpsMacro": _merge_source_wins,
    "Project": _merge_source_wins,
}


def merge_content(
    resource_type: str, target: Dict[str, Any], source: Dict[str, Any]
) -> Dict[str, Any]:
    model_type = get_content_model(resource_type)
    if model_type is None:
        raise ValueError(f"Resource type '{resource_type}' is not versioned")

    target_payload = model_type.model_validate(target or {}).model_dump()
    source_payload = model_type.model_validate(source or {}).model_dump()

    strategy = _merge_strategy(target_payload, source_payload)
    merge_fn = _MERGE_FNS.get(resource_type, _merge_source_wins)
    merged = merge_fn(target_payload, source_payload)
    if strategy == "target_wins":
        merged = _merge_target_wins(target_payload, source_payload)

    return model_type.model_validate(merged).model_dump()
