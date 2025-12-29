from __future__ import annotations

from uuid import UUID

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.types import TypeDecorator

JSONType = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class UUIDArrayType(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(PG_UUID))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None or dialect.name == "postgresql":
            return value
        return [str(item) for item in value]

    def process_result_value(self, value, dialect):
        if value is None or dialect.name == "postgresql":
            return value
        return [item if isinstance(item, UUID) else UUID(str(item)) for item in value]
