"""TypeValidationMixin — Generic[I, O] resolution and Pydantic model validation."""

from __future__ import annotations

from abc import ABC
from typing import Any, TypeVar, get_args

from pydantic import BaseModel

I = TypeVar("I")
O = TypeVar("O")


class TypeValidationMixin(ABC):
    """Mixin providing Generic type-parameter introspection and model parsing.

    Methods:
        __init_subclass__   : Enforces Pydantic BaseModel bounds on I and O.
        _get_node_type_args : Resolves the concrete (InputType, OutputType) pair.
        get_input           : Parses a raw dict into the node's input model.
        get_output          : Parses a raw dict into the node's output model.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Enforce that concrete subclasses parameterise BaseNode with Pydantic BaseModel types."""
        super().__init_subclass__(**kwargs)
        for base in getattr(cls, "__orig_bases__", []):
            args = get_args(base)
            if not args or len(args) < 2:
                continue
            i_type, o_type = args[0], args[1]
            # Skip TypeVar params — class is still abstract/generic.
            if isinstance(i_type, TypeVar) or isinstance(o_type, TypeVar):
                continue
            if isinstance(i_type, type) and not issubclass(i_type, BaseModel):
                raise TypeError(
                    f"{cls.__name__}: input type '{i_type.__name__}' must be a Pydantic BaseModel subclass"
                )
            if isinstance(o_type, type) and not issubclass(o_type, BaseModel):
                raise TypeError(
                    f"{cls.__name__}: output type '{o_type.__name__}' must be a Pydantic BaseModel subclass"
                )

    @classmethod
    def _get_node_type_args(cls) -> tuple[type[BaseModel], type[BaseModel]]:
        """Resolve the concrete (InputType, OutputType) from the Generic parameters.

        Walks the MRO so multi-level inheritance is handled correctly.

        Returns:
            Two-tuple of (InputType, OutputType) Pydantic model classes.

        Raises:
            TypeError: When no concrete type args can be found.
        """
        for klass in cls.__mro__:
            for base in getattr(klass, "__orig_bases__", []):
                args = get_args(base)
                if not args or len(args) < 2:
                    continue
                i_type, o_type = args[0], args[1]
                if isinstance(i_type, type) and isinstance(o_type, type):
                    return i_type, o_type  # type: ignore[return-value]
        raise TypeError(
            f"{cls.__name__} does not provide concrete Generic[InputType, OutputType] type args"
        )

    def get_input(self, data: dict[str, Any]) -> Any:
        """Parse and validate a data dict into the node's input Pydantic model.

        Args:
            data: Raw dict to deserialise.

        Returns:
            Validated instance of the node's input type.
        """
        input_type, _ = type(self)._get_node_type_args()
        return input_type.model_validate(data)

    def get_output(self, data: dict[str, Any]) -> Any:
        """Parse and validate a data dict into the node's output Pydantic model.

        Args:
            data: Raw dict to deserialise.

        Returns:
            Validated instance of the node's output type.
        """
        _, output_type = type(self)._get_node_type_args()
        return output_type.model_validate(data)


__all__ = ["TypeValidationMixin"]
