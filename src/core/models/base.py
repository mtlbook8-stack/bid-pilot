"""
CamelModel — shared base for every persisted/serialized domain model.

WHY this exists: the canonical wire + storage schema for BidPilot is camelCase.
The build doc's Cosmos document schemas (sections 6.3, 6.4), the DataQueryAgent's
data dictionary (section 7, Agent 9), and — critically — the container partition
key paths (section 6.1: `/projectId`, `/userId`, `/agentName`, `/bidId`,
`/entityType`) are all camelCase. If a document serialized its partition-key field
as snake_case (`project_id`) it would not sit at the container's `/projectId`
path, breaking partition routing and point reads.

So every model inherits this base, which:
  - emits camelCase keys on `model_dump(by_alias=True)` / `model_dump_json(by_alias=True)`
    (the stores always dump by alias), and
  - still accepts BOTH camelCase and snake_case on input (`populate_by_name=True`),
    so internal Python code can construct models with natural snake_case kwargs.

Python attribute access stays snake_case everywhere; only the serialized form is
camelCase. This keeps the domain code idiomatic while the persisted shape matches
the infrastructure exactly.
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that serializes to camelCase and accepts either casing."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        # Domain models carry fields like `model_config_`; silence the pydantic
        # protected-namespace warning rather than rename a documented field.
        protected_namespaces=(),
    )
