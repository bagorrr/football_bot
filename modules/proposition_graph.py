"""Typed source-proposition state and edge values for Application validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum


class PropositionState(StrEnum):
    """Application meaning of one source-bound proposition node."""

    CURRENT_POSITIVE = "current_positive"
    NEGATED = "negated"
    WITHDRAWN = "withdrawn"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


class PropositionEdgeKind(StrEnum):
    """A typed relationship from the source proposition graph."""

    SUPPORTS = "supports"
    NEGATES = "negates"
    REPLACES = "replaces"
    COMPETES_WITH = "competes_with"


class PropositionEdgeDirection(StrEnum):
    """Direction retained by the versioned wire contract."""

    INCOMING = "incoming"
    OUTGOING = "outgoing"


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """An exact source-revision span owned by one graph node or edge."""

    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class CanonicalPropositionNode:
    """One typed canonical proposition node after wire validation."""

    node_id: str
    state: PropositionState
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CanonicalPropositionEdge:
    """One typed edge in the source-bound proposition graph."""

    kind: PropositionEdgeKind
    direction: PropositionEdgeDirection
    target: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CanonicalPropositionGraph:
    """The complete typed graph used by Application authority checks.

    The wire contract remains ``source-proposition-evidence-v1``. This is an
    internal typed interpretation of that existing shape, so no v1/v2
    compatibility or replay lineage is changed by the semantic gate.
    """

    root: CanonicalPropositionNode
    facts: tuple[CanonicalPropositionNode, ...]
    routes: tuple[CanonicalPropositionNode, ...]
    edges: tuple[CanonicalPropositionEdge, ...]

    @property
    def nodes(self) -> tuple[CanonicalPropositionNode, ...]:
        return (self.root, *self.facts, *self.routes)

    @property
    def node_ids(self) -> frozenset[str]:
        return frozenset(node.node_id for node in self.nodes)

    @property
    def supported_targets(self) -> frozenset[str]:
        return frozenset(
            edge.target
            for edge in self.edges
            if edge.kind is PropositionEdgeKind.SUPPORTS
            and edge.direction is PropositionEdgeDirection.OUTGOING
        )

    def is_current_positive(self) -> bool:
        """Require every accepted node to be one current positive state."""

        return all(
            node.state is PropositionState.CURRENT_POSITIVE for node in self.nodes
        )

    def has_complete_support_topology(self) -> bool:
        """Require exactly one outgoing support edge for every graph node."""

        return (
            len(self.edges) == len(self.node_ids)
            and self.supported_targets == self.node_ids
            and all(
                edge.kind is PropositionEdgeKind.SUPPORTS
                and edge.direction is PropositionEdgeDirection.OUTGOING
                for edge in self.edges
            )
        )

    def has_exact_support_spans(self) -> bool:
        """Require each support edge to repeat its target node's exact span."""

        if not self.has_complete_support_topology():
            return False
        node_spans = {node.node_id: node.span for node in self.nodes}
        return all(edge.span == node_spans[edge.target] for edge in self.edges)


def canonical_proposition_graph_from_wire(
    value: object,
    *,
    body: str,
    candidate_key: str,
    evidence: Mapping[str, object],
    routes: Sequence[object],
    meaning: str = "open_match",
) -> CanonicalPropositionGraph | None:
    """Convert the already schema-checked v1 graph into typed values.

    This function is intentionally strict even though callers also run the
    classifier contract validator. Keeping the conversion fail-closed prevents
    a future caller from bypassing the source-span and node/edge shape checks.
    """

    if not isinstance(value, Mapping) or not body:
        return None
    if value.get("contract_version") != "source-proposition-evidence-v1":
        return None
    if value.get("coverage") != "complete_source_revision":
        return None

    def span_from(
        raw: object, *, expected_text: str | None = None
    ) -> SourceSpan | None:
        if not isinstance(raw, Mapping) or set(raw) != {"start", "end", "text"}:
            return None
        start = raw.get("start")
        end = raw.get("end")
        text = raw.get("text")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or not isinstance(text, str)
            or not text
            or start < 0
            or end <= start
            or end > len(body)
            or body[start:end] != text
            or (expected_text is not None and text != expected_text)
        ):
            return None
        return SourceSpan(start=start, end=end, text=text)

    def state_from(raw: Mapping[str, object]) -> PropositionState:
        polarity = raw.get("polarity")
        currentness = raw.get("currentness")
        if polarity == "positive" and currentness == "current":
            return PropositionState.CURRENT_POSITIVE
        if polarity == "negative":
            return PropositionState.NEGATED
        if currentness == "withdrawn":
            return PropositionState.WITHDRAWN
        if currentness == "superseded":
            return PropositionState.SUPERSEDED
        return PropositionState.UNKNOWN

    def node_from(
        node_id: str,
        raw: object,
        *,
        expected_text: str | None = None,
    ) -> CanonicalPropositionNode | None:
        if not isinstance(raw, Mapping):
            return None
        span = span_from(raw.get("span"), expected_text=expected_text)
        if span is None or raw.get("proposition_id") != candidate_key:
            return None
        return CanonicalPropositionNode(
            node_id=node_id,
            state=state_from(raw),
            span=span,
        )

    raw_root = value.get("root")
    if not isinstance(raw_root, Mapping):
        return None
    if (
        raw_root.get("proposition_id") != candidate_key
        or raw_root.get("domain") != "football_match"
        or raw_root.get("meaning") != meaning
    ):
        return None
    root = node_from("root", raw_root, expected_text=body)
    if root is None:
        return None

    raw_facts = value.get("facts")
    if not isinstance(raw_facts, Mapping) or set(raw_facts) != set(evidence):
        return None
    fact_nodes: list[CanonicalPropositionNode] = []
    for fact_name, raw_fact in raw_facts.items():
        expected_text = evidence.get(fact_name)
        if not isinstance(expected_text, str):
            return None
        node = node_from(fact_name, raw_fact, expected_text=expected_text)
        if node is None:
            return None
        fact_nodes.append(node)

    raw_routes = value.get("routes")
    if not isinstance(raw_routes, list) or len(raw_routes) != len(routes):
        return None
    expected_route_ids: set[str] = set()
    route_nodes: list[CanonicalPropositionNode] = []
    for raw_route, proposed_route in zip(raw_routes, routes, strict=True):
        if not isinstance(raw_route, Mapping) or not isinstance(
            proposed_route, Mapping
        ):
            return None
        kind = proposed_route.get("kind")
        route_value = proposed_route.get("value")
        route_evidence = proposed_route.get("evidence")
        if not all(
            isinstance(item, str) and item
            for item in (kind, route_value, route_evidence)
        ):
            return None
        assert isinstance(kind, str)
        assert isinstance(route_value, str)
        assert isinstance(route_evidence, str)
        node_id = f"route:{kind}:{route_value}"
        if node_id in expected_route_ids:
            return None
        expected_route_ids.add(node_id)
        if raw_route.get("kind") != kind or raw_route.get("value") != route_value:
            return None
        node = node_from(node_id, raw_route, expected_text=route_evidence)
        if node is None:
            return None
        route_nodes.append(node)

    raw_edges = value.get("relations")
    if not isinstance(raw_edges, list):
        return None
    node_ids = {"root", *raw_facts, *expected_route_ids}
    edges: list[CanonicalPropositionEdge] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, Mapping) or set(raw_edge) != {
            "kind",
            "direction",
            "target",
            "span",
        }:
            return None
        kind_value = raw_edge.get("kind")
        direction_value = raw_edge.get("direction")
        target = raw_edge.get("target")
        if (
            not isinstance(kind_value, str)
            or not isinstance(direction_value, str)
            or not isinstance(target, str)
            or target not in node_ids
        ):
            return None
        try:
            kind = PropositionEdgeKind(kind_value)
            direction = PropositionEdgeDirection(direction_value)
        except ValueError:
            return None
        span = span_from(raw_edge.get("span"))
        if span is None:
            return None
        edges.append(
            CanonicalPropositionEdge(
                kind=kind,
                direction=direction,
                target=target,
                span=span,
            )
        )

    graph = CanonicalPropositionGraph(
        root=root,
        facts=tuple(fact_nodes),
        routes=tuple(route_nodes),
        edges=tuple(edges),
    )
    return graph if graph.node_ids == node_ids else None
