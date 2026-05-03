from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from backend.app.tools.protocol import ToolBindableDescription, ToolProtocol


_CONTRACT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ToolRegistryError(RuntimeError):
    error_code = "tool_registry_error"

    def __init__(
        self,
        message: str,
        *,
        tool_name: Any | None = None,
        category: Any | None = None,
        field_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.category = category
        self.field_name = field_name


class InvalidToolDefinitionError(ToolRegistryError):
    error_code = "tool_definition_invalid"


class DuplicateToolRegistrationError(ToolRegistryError):
    error_code = "tool_registration_duplicate"


class UnknownToolError(ToolRegistryError):
    error_code = "tool_unknown"


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolProtocol] | None = None) -> None:
        self._tools_by_name: dict[str, ToolProtocol] = {}
        self._tools_by_category_name: dict[tuple[str, str], ToolProtocol] = {}
        self._bindables_by_name: dict[str, ToolBindableDescription] = {}
        self._bindables_by_category_name: dict[
            tuple[str, str], ToolBindableDescription
        ] = {}
        for tool in tools or ():
            self.register(tool)

    def register(self, tool: ToolProtocol) -> None:
        name = self._validate_contract_name(tool.name, field_name="tool.name")
        category = self._validate_contract_name(
            tool.category,
            field_name="tool.category",
            tool_name=name,
            category=tool.category,
        )
        bindable = tool.bindable_description()
        if bindable.name != name:
            raise InvalidToolDefinitionError(
                "Bindable tool description name must match tool.name.",
                tool_name=name,
                category=category,
                field_name="name",
            )
        if bindable.description != tool.description:
            raise InvalidToolDefinitionError(
                "Bindable tool description must use the tool description.",
                tool_name=name,
                category=category,
                field_name="description",
            )
        if dict(bindable.input_schema) != dict(tool.input_schema):
            raise InvalidToolDefinitionError(
                "Bindable tool input schema must match tool.input_schema.",
                tool_name=name,
                category=category,
                field_name="input_schema",
            )
        if dict(bindable.result_schema) != dict(tool.result_schema):
            raise InvalidToolDefinitionError(
                "Bindable tool result schema must match tool.result_schema.",
                tool_name=name,
                category=category,
                field_name="result_schema",
            )
        if bindable.risk_level != tool.default_risk_level:
            raise InvalidToolDefinitionError(
                "Bindable tool risk level must match tool.default_risk_level.",
                tool_name=name,
                category=category,
                field_name="risk_level",
            )
        if tuple(bindable.risk_categories) != tuple(tool.risk_categories):
            raise InvalidToolDefinitionError(
                "Bindable tool risk categories must match tool.risk_categories.",
                tool_name=name,
                category=category,
                field_name="risk_categories",
            )
        if name in self._tools_by_name:
            raise DuplicateToolRegistrationError(
                "Tool names must be globally unique for model binding.",
                tool_name=name,
                category=category,
            )

        key = (category, name)
        if key in self._tools_by_category_name:
            raise DuplicateToolRegistrationError(
                "Tool category/name pair is already registered.",
                tool_name=name,
                category=category,
            )

        self._tools_by_name[name] = tool
        self._tools_by_category_name[key] = tool
        bindable_snapshot = bindable.model_copy(deep=True)
        self._bindables_by_name[name] = bindable_snapshot
        self._bindables_by_category_name[key] = bindable_snapshot

    def resolve(self, name: str, *, category: str | None = None) -> ToolProtocol:
        validated_name = self._validate_contract_name(name, field_name="name")
        if category is None:
            tool = self._tools_by_name.get(validated_name)
            if tool is None:
                raise UnknownToolError(
                    "Tool is not registered.",
                    tool_name=validated_name,
                )
            return tool

        validated_category = self._validate_contract_name(
            category,
            field_name="category",
            tool_name=validated_name,
            category=category,
        )
        tool = self._tools_by_category_name.get((validated_category, validated_name))
        if tool is None:
            raise UnknownToolError(
                "Tool is not registered in the requested category.",
                tool_name=validated_name,
                category=validated_category,
            )
        return tool

    def list_bindable_tools(
        self,
        *,
        category: str | None = None,
    ) -> tuple[ToolBindableDescription, ...]:
        if category is None:
            descriptions = self._bindables_by_name.values()
        else:
            validated_category = self._validate_contract_name(
                category,
                field_name="category",
            )
            descriptions = [
                description
                for (
                    tool_category,
                    _,
                ), description in self._bindables_by_category_name.items()
                if tool_category == validated_category
            ]
        return tuple(
            description.model_copy(deep=True)
            for description in sorted(descriptions, key=lambda candidate: candidate.name)
        )

    @staticmethod
    def _validate_contract_name(
        value: object,
        *,
        field_name: str,
        tool_name: Any | None = None,
        category: Any | None = None,
    ) -> str:
        error_tool_name = (
            value if tool_name is None and field_name in {"tool.name", "name"} else tool_name
        )
        error_category = (
            value
            if category is None and field_name in {"tool.category", "category"}
            else category
        )
        if not isinstance(value, str):
            raise InvalidToolDefinitionError(
                f"{field_name} must be a string lower snake-case identifier.",
                tool_name=error_tool_name,
                category=error_category,
                field_name=field_name,
            )
        if not _CONTRACT_NAME_PATTERN.fullmatch(value):
            raise InvalidToolDefinitionError(
                f"{field_name} must be a lower snake-case tool contract identifier.",
                tool_name=error_tool_name,
                category=error_category,
                field_name=field_name,
            )
        return value


__all__ = [
    "DuplicateToolRegistrationError",
    "InvalidToolDefinitionError",
    "ToolRegistry",
    "ToolRegistryError",
    "UnknownToolError",
]
