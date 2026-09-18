from collections.abc import Mapping
from types import MappingProxyType
from typing import TypeAlias

DomainContextValue: TypeAlias = str | int | bool | tuple[str, ...]


class DomainError(Exception):
    code: str
    message: str
    context: Mapping[str, DomainContextValue]

    def __init__(
        self,
        code: str,
        message: str,
        context: Mapping[str, DomainContextValue],
    ) -> None:
        if not isinstance(code, str):
            raise TypeError("DomainError code must be a string")
        if not isinstance(message, str):
            raise TypeError("DomainError message must be a string")
        if not isinstance(context, Mapping):
            raise TypeError("DomainError context must be a mapping")

        copied_context: dict[str, DomainContextValue] = {}
        for key, value in context.items():
            if type(key) is not str:
                raise TypeError("DomainError context keys must be strings")
            if type(value) in (str, int, bool):
                copied_context[key] = value
                continue
            if type(value) is tuple and all(type(item) is str for item in value):
                copied_context[key] = value
                continue
            raise TypeError("DomainError context values must be str, int, bool, or tuple[str, ...]")

        self.code = code
        self.message = message
        self.context = MappingProxyType(copied_context)
        super().__init__(message)


__all__ = ["DomainError"]
