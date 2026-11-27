"""Parse batch steps and bind new request arguments from earlier results."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .registry import ClientError

NonemptyString = Annotated[str, Field(min_length=1)]
PathIndex = Annotated[int, Field(ge=0)]


class _Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: list[PathIndex | str] = Field(min_length=1)
    between: (
        Annotated[list[NonemptyString], Field(min_length=2, max_length=2)] | None
    ) = None


class _Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bind: dict[NonemptyString, _Binding] = Field(default_factory=dict)


class _MethodStep(_Step):
    method: NonemptyString
    params: dict[str, Any] = Field(default_factory=dict)


class _ToolStep(_Step):
    tool: NonemptyString
    arguments: dict[str, Any] = Field(default_factory=dict)


_STEPS = TypeAdapter(Annotated[list[_MethodStep | _ToolStep], Field(min_length=1)])


def parse_steps(requests: list[dict[str, Any]]) -> list[_MethodStep | _ToolStep]:
    try:
        steps = _STEPS.validate_python(requests, strict=True)
    except ValidationError:
        raise ClientError(
            "invalid_request", "Expected a nonempty array of method or tool steps"
        ) from None

    for index, step in enumerate(steps):
        params = step.arguments if isinstance(step, _ToolStep) else step.params
        if params.keys() & step.bind.keys():
            raise ClientError(
                "invalid_request", f"Batch step {index} binds an existing parameter"
            )
        for binding in step.bind.values():
            source = binding.path[0]
            if not isinstance(source, int) or source >= index:
                raise ClientError(
                    "invalid_request",
                    f"Batch step {index} must bind from an earlier step",
                )
    return steps


def _resolve(binding: _Binding, items: list[dict[str, Any]]) -> Any:
    source, *path = binding.path
    assert isinstance(source, int)
    value: Any = items[source]["result"]
    try:
        for part in path:
            if isinstance(value, dict) and isinstance(part, str):
                value = value[part]
            elif isinstance(value, list) and isinstance(part, int):
                value = value[part]
            else:
                raise KeyError
    except (KeyError, IndexError):
        raise ClientError(
            "invalid_binding", "Batch binding path is missing from the earlier result"
        ) from None

    if binding.between is None:
        return value
    if isinstance(value, str):
        start, end = binding.between
        _, opening, remainder = value.partition(start)
        extracted, closing, _ = remainder.partition(end)
        if opening and closing:
            return extracted
    raise ClientError(
        "invalid_binding", "Batch binding delimiters did not match result text"
    )


def prepare_step(
    step: _MethodStep | _ToolStep, items: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    bound = {key: _resolve(binding, items) for key, binding in step.bind.items()}
    if isinstance(step, _ToolStep):
        return "tools/call", {
            "name": step.tool,
            "arguments": {**step.arguments, **bound},
        }
    return step.method, {**step.params, **bound}
