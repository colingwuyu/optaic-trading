"""Tests for FactoryRegistry."""

import pytest

from libs.data.registry import FactoryRegistry


class TestFactoryRegistry:
    """Tests for FactoryRegistry."""

    def test_register_function(self):
        """Test registering a function."""
        registry = FactoryRegistry("test")

        @registry.register("my_func")
        def my_func(x):
            return x * 2

        assert "my_func" in registry
        assert registry.get("my_func") == my_func

    def test_register_class(self):
        """Test registering a class."""
        registry = FactoryRegistry("test")

        @registry.register("MyClass")
        class MyClass:
            def __init__(self, value):
                self.value = value

        assert "MyClass" in registry
        instance = registry.build("MyClass", value=42)
        assert instance.value == 42

    def test_register_with_inferred_name(self):
        """Test registration uses class/function name if name not provided."""
        registry = FactoryRegistry("test")

        @registry.register()
        class AutoNamed:
            pass

        assert "AutoNamed" in registry

    def test_build_from_config(self):
        """Test building from config dict."""
        registry = FactoryRegistry("test")

        @registry.register("multiplier")
        def multiplier(value, factor):
            return value * factor

        result = registry.build_from_config(
            {"name": "multiplier", "params": {"value": 10, "factor": 3}}
        )
        assert result == 30

    def test_build_from_config_requires_name(self):
        """Test build_from_config requires 'name' field."""
        registry = FactoryRegistry("test")

        with pytest.raises(KeyError, match="'name'"):
            registry.build_from_config({"params": {}})

    def test_get_unknown_raises(self):
        """Test getting unknown key raises KeyError."""
        registry = FactoryRegistry("test")

        with pytest.raises(KeyError, match="Unknown test"):
            registry.get_constructor("unknown")

    def test_get_returns_default(self):
        """Test get returns default for unknown key."""
        registry = FactoryRegistry("test")

        result = registry.get("unknown", default="fallback")
        assert result == "fallback"

    def test_contains(self):
        """Test __contains__ works."""
        registry = FactoryRegistry("test")

        @registry.register("exists")
        def exists():
            pass

        assert "exists" in registry
        assert "not_exists" not in registry

    def test_keys(self):
        """Test keys() returns registered names."""
        registry = FactoryRegistry("test")

        @registry.register("a")
        def a():
            pass

        @registry.register("b")
        def b():
            pass

        keys = registry.keys()
        assert "a" in keys
        assert "b" in keys

    def test_len(self):
        """Test __len__ returns count."""
        registry = FactoryRegistry("test")

        @registry.register("a")
        def a():
            pass

        @registry.register("b")
        def b():
            pass

        assert len(registry) == 2

    def test_base_type_validation(self):
        """Test base_type enforcement for classes."""

        class BasePlugin:
            pass

        registry = FactoryRegistry("plugin", base_type=BasePlugin)

        # Valid subclass
        @registry.register("valid")
        class ValidPlugin(BasePlugin):
            pass

        assert "valid" in registry

        # Invalid class should raise
        with pytest.raises(TypeError, match="must inherit from"):

            @registry.register("invalid")
            class InvalidPlugin:
                pass
