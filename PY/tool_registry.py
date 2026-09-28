"""Single binding of advertised tool contracts to callable handlers.

Existing tool definitions remain compatible; families can replace their legacy
handler incrementally without maintaining a second list of advertised names.
This module imports no native libraries or MCP transport.
"""
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolBinding:
    definition: Any
    handler: Callable
    capabilities: tuple[str, ...] = ()


class ToolRegistry:
    def __init__(self):
        self._bindings = {}

    @property
    def initialized(self):
        return bool(self._bindings)

    def bind(self, definitions, fallback_handler):
        bindings = {}
        for definition in definitions:
            name = definition.name
            if name in bindings:
                raise ValueError(f"Duplicate tool definition: {name}")
            prior = self._bindings.get(name)
            bindings[name] = ToolBinding(definition, prior.handler if prior else fallback_handler,
                                         prior.capabilities if prior else ())
        self._bindings = bindings
        return self.definitions()

    def replace_handler(self, name, handler, capabilities=()):
        old = self._bindings[name]
        self._bindings[name] = ToolBinding(old.definition, handler, tuple(capabilities))

    def definitions(self):
        return [binding.definition for binding in self._bindings.values()]

    async def dispatch(self, name, arguments):
        if name not in self._bindings:
            raise ValueError(f"Unknown tool: {name}")
        return await self._bindings[name].handler(name, arguments)
