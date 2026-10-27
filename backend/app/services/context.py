"""Who is acting, and for which client."""

import uuid
from dataclasses import dataclass, field

from app.enums import ActorType, Role
from app.models import Organization


@dataclass(frozen=True)
class Actor:
    type: ActorType
    id: str | None = None
    user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None

    @classmethod
    def system(cls, name: str = "system") -> "Actor":
        return cls(type=ActorType.SYSTEM, id=name)

    @classmethod
    def for_user(cls, user_id: uuid.UUID) -> "Actor":
        return cls(type=ActorType.USER, id=str(user_id), user_id=user_id)

    @classmethod
    def for_api_key(cls, api_key_id: uuid.UUID) -> "Actor":
        return cls(type=ActorType.API_KEY, id=str(api_key_id), api_key_id=api_key_id)


@dataclass
class Ctx:
    """Everything a service needs to act safely inside one tenant."""

    org: Organization
    actor: Actor
    role: Role | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def org_id(self) -> uuid.UUID:
        return self.org.id

    @classmethod
    def system(cls, org: Organization, name: str = "system") -> "Ctx":
        return cls(org=org, actor=Actor.system(name))
