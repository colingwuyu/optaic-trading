"""Base Accessor Interface.

Defines the abstract interface for data access patterns.
Adapted from optaic-v0/data/access/base.py.

Key Difference from optaic-v0:
- Takes resource_id and store instance instead of data_api and DatasetInfo
- Designed to work with Resource model and service layer
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import pandas as pd

    from libs.data.store.base import BaseStore


class BaseRequest(BaseModel):
    """Standard request parameters for data access.

    Pydantic model for validating accessor requests.
    """

    start_date: date = Field(
        default=date(1900, 1, 1),
        description="Start date filter (inclusive)",
    )
    end_date: date = Field(
        default=date(2099, 12, 31),
        description="End date filter (inclusive)",
    )
    as_of_date: date | None = Field(
        default=None,
        description="Point-in-time retrieval date for PIT correctness",
    )


class BaseAccessor(ABC):
    """Abstract base class for data accessors.

    An Accessor provides business logic on top of a Store:
    - Field selection and transformation
    - Point-in-time (PIT) handling
    - Multi-dataset joins (for composite data)

    Accessors do NOT handle:
    - Authorization (done by service layer)
    - Activity logging (done by service layer)
    - Physical storage (done by Store)

    Attributes:
        resource_id: The DatasetInstance resource ID
        store: The underlying data store
        config: Configuration from AccessorDef + DatasetInstance
    """

    def __init__(
        self,
        resource_id: str,
        store: "BaseStore",
        config: dict[str, Any],
    ) -> None:
        """Initialize the accessor.

        Args:
            resource_id: The DatasetInstance resource ID
            store: The underlying data store instance
            config: Merged config from AccessorDef + DatasetInstance
        """
        self.resource_id = resource_id
        self.store = store
        self.config = config

    def get_request_model(self) -> type[BaseModel]:
        """Get the Pydantic model for validating requests.

        Override to provide accessor-specific request parameters.
        """
        return BaseRequest

    @abstractmethod
    def get(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Retrieve data with business logic applied.

        Args:
            start_date: Filter start date (inclusive)
            end_date: Filter end date (inclusive)
            as_of_date: Point-in-time date for PIT correctness
            **kwargs: Accessor-specific arguments

        Returns:
            DataFrame with the requested data
        """

    def get_output_columns(self) -> list[str]:
        """Get the expected output column names.

        Used for UI autocomplete without fetching data.
        Override if the accessor transforms columns.

        Returns:
            List of column names that get() would return
        """
        return self.store.get_columns()

    def get_date_range(self) -> tuple[date | None, date | None]:
        """Get the available date range for this accessor.

        Returns:
            Tuple of (min_date, max_date)
        """
        return self.store.get_date_range()

    def validate_request(self, request: BaseRequest) -> None:
        """Validate a request before execution.

        Override to add accessor-specific validation.

        Raises:
            ValueError: If request is invalid
        """
        if request.start_date > request.end_date:
            raise ValueError("start_date cannot be after end_date")
