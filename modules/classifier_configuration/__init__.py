"""Application-owned T4 Source Message classifier configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

CLASSIFIER_MODEL_KEY = "CLASSIFIER_MODEL"
CLASSIFIER_REASONING_EFFORT_KEY = "CLASSIFIER_REASONING_EFFORT"
T4_CLASSIFIER_CONFIGURATION_KEYS = frozenset(
    {CLASSIFIER_MODEL_KEY, CLASSIFIER_REASONING_EFFORT_KEY}
)

DEFAULT_CLASSIFIER_MODEL = "gpt-5.6-sol"
DEFAULT_CLASSIFIER_REASONING_EFFORT = "high"


class ClassifierConfigurationError(ValueError):
    """A T4 classifier configuration key is missing, malformed, or unsupported."""

    def __init__(self, *, key: str, status: str) -> None:
        self.key = key
        self.status = status
        super().__init__(f"classifier configuration {status}: {key}")


@dataclass(frozen=True, slots=True)
class T4ClassifierProjection:
    """Validated classifier-only configuration passed to the T4 role."""

    model: str = DEFAULT_CLASSIFIER_MODEL
    reasoning_effort: str = DEFAULT_CLASSIFIER_REASONING_EFFORT

    def __post_init__(self) -> None:
        if not isinstance(self.model, str):
            raise ClassifierConfigurationError(
                key=CLASSIFIER_MODEL_KEY, status="malformed"
            )
        if not self.model:
            raise ClassifierConfigurationError(key=CLASSIFIER_MODEL_KEY, status="empty")
        if self.model != DEFAULT_CLASSIFIER_MODEL:
            raise ClassifierConfigurationError(
                key=CLASSIFIER_MODEL_KEY, status="unsupported"
            )
        if not isinstance(self.reasoning_effort, str):
            raise ClassifierConfigurationError(
                key=CLASSIFIER_REASONING_EFFORT_KEY, status="malformed"
            )
        if not self.reasoning_effort:
            raise ClassifierConfigurationError(
                key=CLASSIFIER_REASONING_EFFORT_KEY, status="empty"
            )
        if self.reasoning_effort != DEFAULT_CLASSIFIER_REASONING_EFFORT:
            raise ClassifierConfigurationError(
                key=CLASSIFIER_REASONING_EFFORT_KEY, status="unsupported"
            )

    @classmethod
    def from_t4_projection(
        cls, projection: Mapping[str, object]
    ) -> T4ClassifierProjection:
        """Parse the T4 keys from an explicit application projection."""
        unexpected = tuple(
            key for key in projection if key not in T4_CLASSIFIER_CONFIGURATION_KEYS
        )
        if unexpected:
            key = unexpected[0]
            raise ClassifierConfigurationError(
                key=key if isinstance(key, str) else "T4", status="unknown_key"
            )
        model = _projection_string(projection, CLASSIFIER_MODEL_KEY)
        reasoning_effort = _projection_string(
            projection, CLASSIFIER_REASONING_EFFORT_KEY
        )
        return cls(
            model=model,
            reasoning_effort=reasoning_effort,
        )

    def to_role_projection(self) -> dict[str, str]:
        """Return only the stable model-policy keys admitted by T4."""
        return {
            CLASSIFIER_MODEL_KEY: self.model,
            CLASSIFIER_REASONING_EFFORT_KEY: self.reasoning_effort,
        }


def _projection_string(projection: Mapping[str, object], key: str) -> str:
    if key not in projection:
        raise ClassifierConfigurationError(key=key, status="missing")
    value = projection[key]
    if not isinstance(value, str):
        raise ClassifierConfigurationError(key=key, status="malformed")
    if not value:
        raise ClassifierConfigurationError(key=key, status="empty")
    return value
