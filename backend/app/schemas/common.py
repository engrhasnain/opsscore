"""Base classes for request and response bodies."""

from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

# Values a client may store in free-form ``attributes`` on sites and assets.
Scalar = str | int | float | bool
ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class In(BaseModel):
    """Request bodies: unknown fields are an error, so typos never pass silently."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    def provided(self) -> dict[str, Any]:
        """Only the fields the caller actually sent (for partial updates)."""
        return {name: getattr(self, name) for name in self.model_fields_set}


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
