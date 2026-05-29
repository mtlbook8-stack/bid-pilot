"""PromptTemplate + ModelConfig — the no-code model/prompt swap mechanism."""

from datetime import UTC, datetime

from pydantic import Field

from src.core.models.base import CamelModel


class ModelConfig(CamelModel):
    """
    Per-agent model parameters. Lives inside the prompt document so a model swap
    is a data change (new active version), never a code change. `fallback_model`
    is used by BaseAgent when the primary returns a deprecation/capacity error.

    Serializes camelCase via CamelModel (model_name -> modelName, etc.) to match
    the build doc's `modelConfig` schema (section 6.3).
    """

    model_name: str
    max_tokens: int = Field(..., gt=0)
    temperature: float = Field(0.1, ge=0.0, le=2.0)
    fallback_model: str | None = None


class PromptTemplate(CamelModel):
    """
    Versioned prompt for one agent. Exactly one version per agent is active.

    `system_prompt_template` and `user_message_template` use `{placeholder}`
    fields that BaseAgent fills, including the `{learned_rules}` slot that
    correction-derived rules are injected into.

    The nested config is named `model_config_` (trailing underscore avoids the
    pydantic reserved attribute) and keeps the explicit `modelConfig` alias; all
    other fields get camelCase aliases from CamelModel automatically.
    """

    id: str
    agent_name: str
    version: int = Field(..., ge=1)
    is_active: bool = True
    model_config_: ModelConfig = Field(..., alias="modelConfig")
    system_prompt_template: str
    user_message_template: str

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_by: str = "seed"
