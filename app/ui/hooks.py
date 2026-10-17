"""A widget's hooks: the handlers the app plugs into it, declared once on the class and checked when wired."""
from collections.abc import Callable
from typing import Any


class Hook:
    """A widget's slot for one handler from the app; unset (or set to None), calling it does nothing and returns
    `default`."""

    def __init__(self, default: Any = None) -> None:
        self.default = default
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self
        return obj.__dict__.get(self.name) or self._unset

    def __set__(self, obj: Any, handler: Callable | None) -> None:
        obj.__dict__[self.name] = handler

    def _unset(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.default


def is_wired(widget: Any, name: str) -> bool:
    """True once the app plugged a handler into the widget's hook `name`."""
    return widget.__dict__.get(_hook(widget, name).name) is not None


def wire(widget: Any, **handlers: Callable | None) -> None:
    """Plug the app's handlers into a widget's hooks; a name that isn't a hook fails here instead of never firing."""
    for name, handler in handlers.items():
        _hook(widget, name)
        setattr(widget, name, handler)


def _hook(widget: Any, name: str) -> Hook:
    hook = getattr(type(widget), name, None)
    if not isinstance(hook, Hook):
        raise AttributeError(f"{type(widget).__name__} has no hook {name!r}")
    return hook
