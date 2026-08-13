"""Provider base class with capability declaration.

A provider declares the coarse-grained capabilities it supports, and engines
query ``supports``/``require`` before calling a method so an unsupported call
fails fast. Engines must depend on this abstraction, never on a vendor SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ashare_contracts.providers import Capability


class Provider(ABC):
    """Base class for all data providers."""

    @abstractmethod
    def capabilities(self) -> frozenset[Capability]:
        """Declare the capabilities this provider supports."""

    def supports(self, capability: Capability) -> bool:
        """Whether this provider declares the given capability."""
        return capability in self.capabilities()

    def require(self, capability: Capability) -> None:
        """Raise :class:`NotImplementedError` if the capability is missing."""
        if not self.supports(capability):
            raise NotImplementedError(f"provider does not support {capability.value}")
