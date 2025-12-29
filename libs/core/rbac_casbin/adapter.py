from __future__ import annotations

from typing import Sequence

from casbin.persist import load_policy_line
from casbin.persist.adapter import Adapter

from libs.db.models.rbac import RoleBinding


class CasbinAdapter(Adapter):
    def __init__(
        self,
        bindings: Sequence[RoleBinding],
        allowed_bindings: Sequence[RoleBinding],
        tenant_id: str,
        perm_name: str,
        object_edges: Sequence[tuple[str, str]],
    ) -> None:
        self._bindings = bindings
        self._allowed_binding_ids = {binding.id for binding in allowed_bindings}
        self._tenant_id = tenant_id
        self._perm_name = perm_name
        self._object_edges = object_edges

    def load_policy(self, model) -> None:
        for binding in self._bindings:
            load_policy_line(
                f"g, {binding.principal_id}, {binding.role_name}, {self._tenant_id}",
                model,
            )
            if binding.id in self._allowed_binding_ids:
                load_policy_line(
                    f"p, {binding.role_name}, {self._tenant_id}, res:{binding.scope_resource_id}, {self._perm_name}",
                    model,
                )

        for child, parent in self._object_edges:
            load_policy_line(f"g2, {child}, {parent}", model)

    def save_policy(self, model) -> None:  # pragma: no cover - not used
        raise NotImplementedError("CasbinAdapter is read-only.")

    def add_policy(self, sec, ptype, rule) -> None:  # pragma: no cover - not used
        raise NotImplementedError("CasbinAdapter is read-only.")

    def remove_policy(self, sec, ptype, rule) -> None:  # pragma: no cover - not used
        raise NotImplementedError("CasbinAdapter is read-only.")

    def remove_filtered_policy(self, sec, ptype, field_index, *field_values) -> None:  # pragma: no cover - not used
        raise NotImplementedError("CasbinAdapter is read-only.")
