# Generic Framework Compliance Tests

## Lazy Import Tests

```python
import sys

def test_no_heavy_imports_at_module_level():
    """Core modules should not import heavy deps at module level."""
    heavy_deps = ["pandas", "numpy", "torch", "pyarrow", "mlflow", "prefect"]

    # Clear cached imports
    for mod in list(sys.modules.keys()):
        if mod.startswith("libs.core"):
            del sys.modules[mod]

    # Import core module
    import libs.core.domain.signal_service

    # Check no heavy deps loaded
    for dep in heavy_deps:
        assert dep not in sys.modules, f"{dep} imported at module level"

def test_heavy_imports_in_function_body():
    """Verify heavy deps are imported inside function bodies."""
    import ast
    import inspect
    from libs.core.domain import signal_service

    source = inspect.getsource(signal_service)
    tree = ast.parse(source)

    # Find top-level imports
    top_imports = [
        node.names[0].name for node in ast.walk(tree)
        if isinstance(node, ast.Import) and node.col_offset == 0
    ]

    heavy = ["pandas", "numpy", "torch", "pyarrow"]
    for dep in heavy:
        assert dep not in top_imports, f"{dep} imported at top level"
```

## DTO Pattern Tests

```python
def test_dto_is_pydantic_model(self):
    """Verify DTOs inherit from Pydantic BaseModel."""
    from pydantic import BaseModel
    from libs.core.domain.signal import SignalCreateDTO, SignalReadDTO

    assert issubclass(SignalCreateDTO, BaseModel)
    assert issubclass(SignalReadDTO, BaseModel)

def test_dto_round_trip(self):
    """Verify DTO serialization round-trip works."""
    dto = SignalCreateDTO(name="test", signal_type="alpha", frequency="daily")

    # Serialize
    data = dto.model_dump()

    # Deserialize
    restored = SignalCreateDTO.model_validate(data)

    assert restored.name == dto.name
    assert restored.signal_type == dto.signal_type

def test_api_returns_dto_not_model(self, client):
    """Verify API endpoints return DTOs, not SQLAlchemy models."""
    response = client.get("/signals/123")

    # Response should be JSON-serializable (not ORM model)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
```

## Service Layer Pattern Tests

```python
def test_service_requires_session_actor_tenant(self):
    """Verify service constructor requires proper context."""
    import inspect
    from libs.core.domain.signal_service import SignalService

    sig = inspect.signature(SignalService.__init__)
    params = list(sig.parameters.keys())

    assert "session" in params
    assert "actor_id" in params
    assert "tenant_id" in params

def test_service_methods_are_async(self):
    """Verify service mutation methods are async."""
    import inspect
    from libs.core.domain.signal_service import SignalService

    for name in ["create", "update", "delete"]:
        method = getattr(SignalService, name, None)
        if method:
            assert inspect.iscoroutinefunction(method), f"{name} should be async"
```

## SDK Pattern Tests

```python
def test_sdk_model_has_from_dict(self):
    """Verify SDK models have from_dict factory."""
    from libs.sdk_py.optaic.models import Signal

    assert hasattr(Signal, "from_dict")
    assert callable(Signal.from_dict)

def test_sdk_exception_hierarchy(self):
    """Verify SDK exceptions follow hierarchy."""
    from libs.sdk_py.optaic.exceptions import (
        OptAICError, AuthenticationError, NotFoundError, GuardrailsBlockedError
    )

    assert issubclass(AuthenticationError, OptAICError)
    assert issubclass(NotFoundError, OptAICError)
    assert issubclass(GuardrailsBlockedError, OptAICError)
```
