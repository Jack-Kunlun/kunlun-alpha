"""Feature registry validation and deterministic dependency ordering."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterable, Mapping
from types import MappingProxyType

from .spec import FeatureSpec

_NAMESPACE_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")


class FeatureRegistryError(ValueError):
    """Base class for registry consistency failures."""


class DuplicateFeatureNameError(FeatureRegistryError):
    """Raised when a registry snapshot contains a duplicate name."""


class MissingFeatureDependencyError(FeatureRegistryError):
    """Raised when a dependency is absent from the same registry snapshot."""


class FeatureVersionConflictError(FeatureRegistryError):
    """Raised when feature versions are incompatible or regress."""


class FeatureDependencyCycleError(FeatureRegistryError):
    """Raised when feature dependencies do not form a DAG."""


class SemanticVersionRequiredError(FeatureRegistryError):
    """Raised when semantics change without a strict version increase."""


class FeatureRemovalError(FeatureRegistryError):
    """Raised when append-only registry evolution removes an active feature."""


class RegistryLineageConflictError(FeatureRegistryError):
    """Raised when an evolution is not based on the trusted registry head."""


def _unique_specs(specs: Iterable[object], snapshot_name: str) -> dict[str, FeatureSpec]:
    result: dict[str, FeatureSpec] = {}
    for spec in specs:
        if not isinstance(spec, FeatureSpec):
            raise TypeError(f"{snapshot_name} specs must contain FeatureSpec values")
        if spec.name in result:
            raise DuplicateFeatureNameError(
                f"duplicate feature name in {snapshot_name} registry: {spec.name}",
            )
        result[spec.name] = spec
    return result


def _validate_dependencies(specs: Mapping[str, FeatureSpec]) -> None:
    for spec in specs.values():
        for dependency in spec.dependencies:
            registered = specs.get(dependency.name)
            if registered is None:
                raise MissingFeatureDependencyError(
                    f"{spec.name} requires missing dependency "
                    f"{dependency.name}@{dependency.version}",
                )
            if registered.version != dependency.version:
                raise FeatureVersionConflictError(
                    f"{spec.name} dependency {dependency.name} expected {dependency.version} "
                    f"but registered {registered.version}",
                )


def _validate_evolution(
    current: Mapping[str, FeatureSpec],
    previous: Mapping[str, FeatureSpec],
) -> None:
    for name, current_spec in current.items():
        previous_spec = previous.get(name)
        if previous_spec is None:
            continue
        if current_spec.version_number < previous_spec.version_number:
            raise FeatureVersionConflictError(
                f"{name} version regressed from {previous_spec.version} to {current_spec.version}",
            )
        semantics_changed = current_spec.semantic_fingerprint != previous_spec.semantic_fingerprint
        if semantics_changed and current_spec.version_number <= previous_spec.version_number:
            raise SemanticVersionRequiredError(
                f"{name} semantic change requires a version greater than "
                f"{previous_spec.version}; got {current_spec.version}",
            )


def _dependency_order(graph: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    state: dict[str, int] = {}
    stack: list[str] = []
    ordered: list[str] = []

    def visit(name: str) -> None:
        current_state = state.get(name, 0)
        if current_state == 2:
            return
        if current_state == 1:
            cycle_start = stack.index(name)
            cycle = (*stack[cycle_start:], name)
            raise FeatureDependencyCycleError(
                f"feature dependency cycle: {' -> '.join(cycle)}",
            )

        state[name] = 1
        stack.append(name)
        for dependency in graph[name]:
            visit(dependency)
        stack.pop()
        state[name] = 2
        ordered.append(name)

    for name in sorted(graph):
        visit(name)
    return tuple(ordered)


def _head_fingerprint(
    namespace_id: str,
    parent_fingerprint: str | None,
    specs: Mapping[str, FeatureSpec],
) -> str:
    payload = {
        "namespaceId": namespace_id,
        "parentFingerprint": parent_fingerprint,
        "specs": [specs[name].to_contract() for name in sorted(specs)],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class FeatureRegistry:
    """A validated immutable snapshot with append-only version lineage."""

    _specs: Mapping[str, FeatureSpec]
    _history: Mapping[str, tuple[FeatureSpec, ...]]
    _dependency_graph: Mapping[str, tuple[str, ...]]
    _dependency_order: tuple[str, ...]
    _namespace_id: str
    _revision_heads: tuple[str, ...]

    def __init__(self) -> None:
        raise TypeError("use FeatureRegistry.empty() to create a namespace genesis")

    @classmethod
    def empty(cls, *, namespace_id: str) -> FeatureRegistry:
        if type(namespace_id) is not str or _NAMESPACE_ID.fullmatch(namespace_id) is None:
            raise FeatureRegistryError("namespace_id must be a lowercase dotted identifier")
        current: dict[str, FeatureSpec] = {}
        genesis_head = _head_fingerprint(namespace_id, None, current)
        return cls._from_validated(
            current,
            {},
            namespace_id=namespace_id,
            revision_heads=(genesis_head,),
        )

    @classmethod
    def _from_validated(
        cls,
        current: dict[str, FeatureSpec],
        history: dict[str, tuple[FeatureSpec, ...]],
        *,
        namespace_id: str,
        revision_heads: tuple[str, ...],
    ) -> FeatureRegistry:
        _validate_dependencies(current)
        graph = {
            name: tuple(sorted(dependency.name for dependency in spec.dependencies))
            for name, spec in sorted(current.items())
        }
        order = _dependency_order(graph)

        registry = object.__new__(cls)
        registry._specs = MappingProxyType(current)
        registry._history = MappingProxyType(history)
        registry._dependency_graph = MappingProxyType(graph)
        registry._dependency_order = order
        registry._namespace_id = namespace_id
        registry._revision_heads = revision_heads
        return registry

    def evolve(
        self,
        specs: Iterable[FeatureSpec],
        *,
        expected_parent_fingerprint: str,
    ) -> FeatureRegistry:
        if (
            type(expected_parent_fingerprint) is not str
            or _FINGERPRINT.fullmatch(expected_parent_fingerprint) is None
            or not hmac.compare_digest(expected_parent_fingerprint, self.head_fingerprint)
        ):
            raise RegistryLineageConflictError(
                "expected parent fingerprint does not match the trusted registry head",
            )
        current = _unique_specs(specs, "evolved")
        removed = sorted(set(self._specs) - set(current))
        if removed:
            raise FeatureRemovalError(
                f"append-only feature registry cannot remove: {', '.join(removed)}",
            )
        _validate_dependencies(current)
        _validate_evolution(current, self._specs)
        if current == self._specs:
            return self

        history = dict(self._history)
        for name, spec in current.items():
            lineage = history.get(name)
            if lineage is None:
                history[name] = (spec,)
            elif spec != lineage[-1]:
                history[name] = (*lineage, spec)
        head = _head_fingerprint(
            self._namespace_id,
            self.head_fingerprint,
            current,
        )
        return self._from_validated(
            current,
            history,
            namespace_id=self._namespace_id,
            revision_heads=(*self._revision_heads, head),
        )

    @property
    def dependency_graph(self) -> dict[str, tuple[str, ...]]:
        return dict(self._dependency_graph)

    def dependency_order(self) -> tuple[str, ...]:
        return self._dependency_order

    def get(self, name: str) -> FeatureSpec:
        return self._specs[name]

    def lineage(self, name: str) -> tuple[FeatureSpec, ...]:
        return self._history[name]

    @property
    def namespace_id(self) -> str:
        return self._namespace_id

    @property
    def head_fingerprint(self) -> str:
        return self._revision_heads[-1]

    @property
    def revision_heads(self) -> tuple[str, ...]:
        return self._revision_heads

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)
