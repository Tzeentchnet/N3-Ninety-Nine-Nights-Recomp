#!/usr/bin/env python3
"""Bounded parser and offline route analysis for Ninety-Nine Nights NAV data."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import random
import statistics
import struct
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.n3_gameplay_data import GameplayDataError, read_pak


NAV_RESERVED_SIZE = 16
NAV_TRIANGLE_SIZE = 40
NAV_ADJACENCY_SIZE = 12
MAX_NAV_SIZE = 64 * 1024 * 1024
MAX_TRIANGLES = 1_000_000
MAX_DYNAMIC_RANGES = 100_000
DEFAULT_SEED = 0x4E335241

Vec3 = tuple[float, float, float]


class NavError(ValueError):
    """Base error for malformed NAV input or invalid offline operations."""


class NavFormatError(NavError):
    """Raised when serialized NAV input is malformed or outside safe bounds."""


class NavTopologyError(NavError):
    """Raised when a topology mutation or graph operation is invalid."""


class RouteNotFound(NavError):
    """Raised when no route exists for a valid request."""


@dataclass(frozen=True)
class Triangle:
    vertices: tuple[Vec3, Vec3, Vec3]
    attribute: int
    neighbors: tuple[int, int, int]

    def edge(self, index: int) -> tuple[Vec3, Vec3]:
        if index not in (0, 1, 2):
            raise IndexError(f"edge index {index} is outside 0..2")
        return self.vertices[index], self.vertices[(index + 1) % 3]


@dataclass(frozen=True)
class DynamicRange:
    start: int
    count: int

    @property
    def stop(self) -> int:
        return self.start + self.count


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class NavMesh:
    name: str
    triangles: tuple[Triangle, ...]
    dynamic_ranges: tuple[DynamicRange, ...]
    centroids: tuple[Vec3, ...]
    portal_midpoints: tuple[tuple[Vec3, Vec3, Vec3], ...]
    portal_distances: tuple[tuple[float, float, float], ...]
    reciprocal_edges: tuple[tuple[int, int, int], ...]
    issues: tuple[ValidationIssue, ...] = ()

    def topology(self) -> "NavTopology":
        return NavTopology(self)


@dataclass(frozen=True)
class Route:
    algorithm: str
    source_triangle: int
    destination_triangle: int
    corridor: tuple[int, ...]
    exit_edges: tuple[int, ...]
    points: tuple[Vec3, ...]
    search_cost: float
    expanded_nodes: int

    @property
    def length(self) -> float:
        return polyline_length(self.points)

    @property
    def planar_length(self) -> float:
        return polyline_length(self.points, planar=True)


@dataclass(frozen=True)
class Portal:
    left: Vec3
    right: Vec3


@dataclass(frozen=True)
class NavResource:
    name: str
    origin: str
    data: bytes


class _Reader:
    def __init__(self, data: bytes, source: str):
        self.data = data
        self.source = source
        self.offset = 0

    def _take(self, size: int) -> bytes:
        end = self.offset + size
        if size < 0 or end > len(self.data):
            raise NavFormatError(
                f"{self.source}: truncated at offset 0x{self.offset:X}; "
                f"need {size} bytes"
            )
        result = self.data[self.offset : end]
        self.offset = end
        return result

    def u32(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def f32(self) -> float:
        return struct.unpack(">f", self._take(4))[0]


def _f32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", value))[0]


def _vec_midpoint(left: Vec3, right: Vec3) -> Vec3:
    return tuple(
        _f32(_f32(_f32(left[index] + right[index])) * _f32(0.5))
        for index in range(3)
    )


def _vec_centroid(vertices: tuple[Vec3, Vec3, Vec3]) -> Vec3:
    scale = _f32(1.0 / 3.0)
    return tuple(
        _f32(
            _f32(_f32(vertices[0][index] + vertices[1][index]) + vertices[2][index])
            * scale
        )
        for index in range(3)
    )


def _distance(left: Vec3, right: Vec3, *, planar: bool = False) -> float:
    dimensions = (0, 2) if planar else (0, 1, 2)
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in dimensions))


def _distance_f32(left: Vec3, right: Vec3) -> float:
    total = _f32(0.0)
    for index in range(3):
        difference = _f32(left[index] - right[index])
        total = _f32(total + _f32(difference * difference))
    return _f32(math.sqrt(total))


def _same_edge(
    left: tuple[Vec3, Vec3],
    right: tuple[Vec3, Vec3],
) -> bool:
    return (left[0] == right[0] and left[1] == right[1]) or (
        left[0] == right[1] and left[1] == right[0]
    )


def parse_nav(data: bytes, *, name: str = "<memory>") -> NavMesh:
    """Parse a serialized big-endian NAV file without accepting trailing data."""

    if len(data) > MAX_NAV_SIZE:
        raise NavFormatError(
            f"{name}: input size {len(data)} exceeds the {MAX_NAV_SIZE}-byte limit"
        )

    reader = _Reader(data, name)
    reserved = reader._take(NAV_RESERVED_SIZE)
    if any(reserved):
        raise NavFormatError(f"{name}: reserved 16-byte prefix is not zero")

    triangle_count = reader.u32()
    if triangle_count > MAX_TRIANGLES:
        raise NavFormatError(
            f"{name}: triangle count {triangle_count} exceeds {MAX_TRIANGLES}"
        )

    raw_triangles: list[tuple[tuple[Vec3, Vec3, Vec3], int]] = []
    for triangle_index in range(triangle_count):
        vertices: list[Vec3] = []
        for _ in range(3):
            vertex = (reader.f32(), reader.f32(), reader.f32())
            if not all(math.isfinite(value) for value in vertex):
                raise NavFormatError(
                    f"{name}: triangle {triangle_index} has a non-finite vertex"
                )
            vertices.append(vertex)
        raw_triangles.append(((vertices[0], vertices[1], vertices[2]), reader.u32()))

    neighbor_records: list[tuple[int, int, int]] = []
    for triangle_index in range(triangle_count):
        neighbors = (reader.i32(), reader.i32(), reader.i32())
        for neighbor in neighbors:
            if neighbor < -1 or neighbor >= triangle_count:
                raise NavFormatError(
                    f"{name}: triangle {triangle_index} has out-of-range "
                    f"neighbor {neighbor}"
                )
        neighbor_records.append(neighbors)

    dynamic_count = reader.u32()
    if dynamic_count > MAX_DYNAMIC_RANGES:
        raise NavFormatError(
            f"{name}: dynamic range count {dynamic_count} exceeds "
            f"{MAX_DYNAMIC_RANGES}"
        )
    dynamic_ranges = tuple(
        DynamicRange(reader.u32(), reader.u32()) for _ in range(dynamic_count)
    )

    if reader.offset != len(data):
        raise NavFormatError(
            f"{name}: {len(data) - reader.offset} trailing bytes follow the NAV data"
        )

    triangles = tuple(
        Triangle(vertices, attribute, neighbor_records[index])
        for index, (vertices, attribute) in enumerate(raw_triangles)
    )
    centroids = tuple(_vec_centroid(triangle.vertices) for triangle in triangles)
    portal_midpoints = tuple(
        tuple(_vec_midpoint(*triangle.edge(edge)) for edge in range(3))
        for triangle in triangles
    )
    portal_distances = tuple(
        (
            _distance_f32(midpoints[0], midpoints[1]),
            _distance_f32(midpoints[1], midpoints[2]),
            _distance_f32(midpoints[2], midpoints[0]),
        )
        for midpoints in portal_midpoints
    )
    reciprocal_edges = _build_reciprocal_edges(triangles)
    mesh = NavMesh(
        name=name,
        triangles=triangles,
        dynamic_ranges=dynamic_ranges,
        centroids=centroids,
        portal_midpoints=portal_midpoints,
        portal_distances=portal_distances,
        reciprocal_edges=reciprocal_edges,
    )
    return replace(mesh, issues=validate_nav(mesh))


def read_nav(path: Path) -> NavMesh:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise NavFormatError(f"cannot read {path}: {error}") from error
    return parse_nav(data, name=str(path))


def _build_reciprocal_edges(
    triangles: Sequence[Triangle],
) -> tuple[tuple[int, int, int], ...]:
    reciprocal: list[tuple[int, int, int]] = []
    for triangle_index, triangle in enumerate(triangles):
        triangle_reciprocal: list[int] = []
        for edge_index, neighbor_index in enumerate(triangle.neighbors):
            if neighbor_index < 0:
                triangle_reciprocal.append(-1)
                continue
            matches = [
                candidate_edge
                for candidate_edge, candidate_neighbor in enumerate(
                    triangles[neighbor_index].neighbors
                )
                if candidate_neighbor == triangle_index
                and _same_edge(
                    triangle.edge(edge_index),
                    triangles[neighbor_index].edge(candidate_edge),
                )
            ]
            triangle_reciprocal.append(matches[0] if len(matches) == 1 else -1)
        reciprocal.append(
            (
                triangle_reciprocal[0],
                triangle_reciprocal[1],
                triangle_reciprocal[2],
            )
        )
    return tuple(reciprocal)


def validate_nav(mesh: NavMesh) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    triangle_count = len(mesh.triangles)

    for triangle_index, triangle in enumerate(mesh.triangles):
        seen_neighbors: set[int] = set()
        for edge_index, neighbor_index in enumerate(triangle.neighbors):
            if neighbor_index < 0:
                continue
            if neighbor_index == triangle_index:
                issues.append(
                    ValidationIssue(
                        "adjacency.self",
                        f"triangle {triangle_index} edge {edge_index} references itself",
                    )
                )
            if neighbor_index in seen_neighbors:
                issues.append(
                    ValidationIssue(
                        "adjacency.duplicate",
                        f"triangle {triangle_index} references triangle "
                        f"{neighbor_index} more than once",
                    )
                )
            seen_neighbors.add(neighbor_index)
            if mesh.reciprocal_edges[triangle_index][edge_index] < 0:
                issues.append(
                    ValidationIssue(
                        "adjacency.nonreciprocal",
                        f"triangle {triangle_index} edge {edge_index} does not have "
                        f"one exact reciprocal edge in triangle {neighbor_index}",
                    )
                )

    coverage = [0] * triangle_count
    for range_index, dynamic_range in enumerate(mesh.dynamic_ranges):
        if (
            dynamic_range.count == 0
            or dynamic_range.start >= triangle_count
            or dynamic_range.stop > triangle_count
        ):
            issues.append(
                ValidationIssue(
                    "dynamic.invalid-range",
                    f"dynamic range {range_index} ({dynamic_range.start}, "
                    f"{dynamic_range.count}) is outside {triangle_count} triangles",
                )
            )
            continue
        for triangle_index in range(dynamic_range.start, dynamic_range.stop):
            coverage[triangle_index] += 1
            if mesh.triangles[triangle_index].attribute == 0:
                issues.append(
                    ValidationIssue(
                        "dynamic.static-member",
                        f"dynamic range {range_index} contains static triangle "
                        f"{triangle_index}",
                    )
                )

    for triangle_index, triangle in enumerate(mesh.triangles):
        if triangle.attribute != 0 and coverage[triangle_index] == 0:
            issues.append(
                ValidationIssue(
                    "dynamic.uncovered",
                    f"attribute-{triangle.attribute} triangle {triangle_index} is "
                    "not covered by a valid dynamic range",
                )
            )
        if coverage[triangle_index] > 1:
            issues.append(
                ValidationIssue(
                    "dynamic.overlap",
                    f"triangle {triangle_index} appears in "
                    f"{coverage[triangle_index]} dynamic ranges",
                )
            )
    return tuple(issues)


class NavTopology:
    """Mutable active/inactive view over immutable serialized NAV geometry."""

    def __init__(self, mesh: NavMesh):
        graph_issues = [
            issue for issue in mesh.issues if issue.code.startswith("adjacency.")
        ]
        if graph_issues:
            raise NavTopologyError(
                f"{mesh.name}: graph is not routable: {graph_issues[0].message}"
            )
        self.mesh = mesh
        self.active = [triangle.attribute == 0 for triangle in mesh.triangles]
        self.generation = 0

    def clone(self) -> "NavTopology":
        result = NavTopology(self.mesh)
        result.active = self.active.copy()
        result.generation = self.generation
        return result

    def set_dynamic_group(self, group_index: int, *, active: bool) -> None:
        if group_index < 0 or group_index >= len(self.mesh.dynamic_ranges):
            raise NavTopologyError(
                f"dynamic group {group_index} is outside "
                f"0..{len(self.mesh.dynamic_ranges) - 1}"
            )
        dynamic_range = self.mesh.dynamic_ranges[group_index]
        triangle_count = len(self.mesh.triangles)
        if (
            dynamic_range.count == 0
            or dynamic_range.start >= triangle_count
            or dynamic_range.stop > triangle_count
        ):
            raise NavTopologyError(
                f"dynamic group {group_index} range ({dynamic_range.start}, "
                f"{dynamic_range.count}) is outside {triangle_count} triangles"
            )
        changed = False
        for triangle_index in range(dynamic_range.start, dynamic_range.stop):
            if self.active[triangle_index] != active:
                self.active[triangle_index] = active
                changed = True
        if changed:
            self.generation += 1

    def neighbor(self, triangle_index: int, edge_index: int) -> int | None:
        neighbor_index = self.mesh.triangles[triangle_index].neighbors[edge_index]
        if (
            neighbor_index < 0
            or not self.active[triangle_index]
            or not self.active[neighbor_index]
        ):
            return None
        return neighbor_index


def _validate_route_request(
    topology: NavTopology,
    source_triangle: int,
    destination_triangle: int,
    source_point: Vec3 | None,
    destination_point: Vec3 | None,
) -> tuple[Vec3, Vec3]:
    triangle_count = len(topology.mesh.triangles)
    for label, triangle_index in (
        ("source", source_triangle),
        ("destination", destination_triangle),
    ):
        if triangle_index < 0 or triangle_index >= triangle_count:
            raise NavTopologyError(
                f"{label} triangle {triangle_index} is outside "
                f"0..{triangle_count - 1}"
            )
        if not topology.active[triangle_index]:
            raise RouteNotFound(f"{label} triangle {triangle_index} is inactive")

    source = (
        topology.mesh.centroids[source_triangle]
        if source_point is None
        else source_point
    )
    destination = (
        topology.mesh.centroids[destination_triangle]
        if destination_point is None
        else destination_point
    )
    if not all(math.isfinite(value) for point in (source, destination) for value in point):
        raise NavTopologyError("route endpoints must contain finite coordinates")
    return source, destination


def _legacy_heuristic(point: Vec3, centroid: Vec3) -> float:
    return max(
        abs(_f32(centroid[index] - point[index]))
        for index in range(3)
    )


def transition_distance(
    mesh: NavMesh,
    triangle_index: int,
    downstream_edge: int,
    candidate_edge: int,
    *,
    corrected: bool,
) -> float:
    """Return the observed or corrected in-triangle portal transition cost."""

    if downstream_edge not in (0, 1, 2) or candidate_edge not in (0, 1, 2):
        raise IndexError("portal edge indices must be in 0..2")
    distances = mesh.portal_distances[triangle_index]
    if not corrected:
        return distances[abs(downstream_edge - candidate_edge)]
    if downstream_edge == candidate_edge:
        return distances[0]
    pair = frozenset((downstream_edge, candidate_edge))
    if pair == frozenset((0, 1)):
        return distances[0]
    if pair == frozenset((1, 2)):
        return distances[1]
    return distances[2]


def legacy_route(
    topology: NavTopology,
    source_triangle: int,
    destination_triangle: int,
    *,
    source_point: Vec3 | None = None,
    destination_point: Vec3 | None = None,
    corrected_transition: bool = False,
) -> Route:
    """Emulate N3's backward, one-state-per-triangle route search."""

    source, destination = _validate_route_request(
        topology,
        source_triangle,
        destination_triangle,
        source_point,
        destination_point,
    )
    mesh = topology.mesh
    triangle_count = len(mesh.triangles)
    unseen, opened, closed = 0, 1, 2
    state = [unseen] * triangle_count
    costs = [math.inf] * triangle_count
    heuristics = [math.inf] * triangle_count
    parent_edges = [-1] * triangle_count
    versions = [0] * triangle_count
    insertion_order = [-1] * triangle_count
    next_order = 0
    heap: list[tuple[float, int, int, int]] = []

    costs[destination_triangle] = _f32(0.0)
    heuristics[destination_triangle] = _f32(0.0)
    parent_edges[destination_triangle] = 0
    state[destination_triangle] = opened
    insertion_order[destination_triangle] = next_order
    next_order += 1
    heapq.heappush(heap, (0.0, 0, destination_triangle, 0))

    expanded = 0
    found = False
    while heap:
        priority, _, triangle_index, version = heapq.heappop(heap)
        if state[triangle_index] != opened or versions[triangle_index] != version:
            continue
        expected_priority = _f32(costs[triangle_index] + heuristics[triangle_index])
        if priority != expected_priority:
            continue

        state[triangle_index] = closed
        expanded += 1
        if triangle_index == source_triangle:
            found = True
            break

        downstream_edge = parent_edges[triangle_index]
        for candidate_edge in range(3):
            neighbor_index = topology.neighbor(triangle_index, candidate_edge)
            if neighbor_index is None or state[neighbor_index] == closed:
                continue
            reciprocal_edge = mesh.reciprocal_edges[triangle_index][candidate_edge]
            if reciprocal_edge < 0:
                raise NavTopologyError(
                    f"triangle {triangle_index} edge {candidate_edge} lacks a "
                    "reciprocal edge"
                )
            candidate_cost = _f32(
                costs[triangle_index]
                + transition_distance(
                    mesh,
                    triangle_index,
                    downstream_edge,
                    candidate_edge,
                    corrected=corrected_transition,
                )
            )
            if state[neighbor_index] == unseen:
                heuristic = _f32(
                    _legacy_heuristic(source, mesh.centroids[neighbor_index])
                )
                costs[neighbor_index] = candidate_cost
                heuristics[neighbor_index] = heuristic
                parent_edges[neighbor_index] = reciprocal_edge
                state[neighbor_index] = opened
                insertion_order[neighbor_index] = next_order
                next_order += 1
            else:
                candidate_priority = _f32(
                    candidate_cost + heuristics[neighbor_index]
                )
                old_priority = _f32(
                    costs[neighbor_index] + heuristics[neighbor_index]
                )
                if candidate_priority >= old_priority:
                    continue
                costs[neighbor_index] = candidate_cost
                parent_edges[neighbor_index] = reciprocal_edge
                versions[neighbor_index] += 1

            heapq.heappush(
                heap,
                (
                    _f32(costs[neighbor_index] + heuristics[neighbor_index]),
                    insertion_order[neighbor_index],
                    neighbor_index,
                    versions[neighbor_index],
                ),
            )

    if not found:
        raise RouteNotFound(
            f"no active route from triangle {source_triangle} to "
            f"{destination_triangle}"
        )

    corridor = [source_triangle]
    exit_edges: list[int] = []
    points = [source]
    current = source_triangle
    for _ in range(triangle_count):
        if current == destination_triangle:
            break
        edge_index = parent_edges[current]
        if edge_index < 0:
            raise NavTopologyError(
                f"legacy reconstruction reached triangle {current} without a parent"
            )
        neighbor_index = topology.neighbor(current, edge_index)
        if neighbor_index is None:
            raise RouteNotFound(
                f"legacy corridor became inactive at triangle {current} edge "
                f"{edge_index}"
            )
        exit_edges.append(edge_index)
        points.append(mesh.portal_midpoints[current][edge_index])
        corridor.append(neighbor_index)
        current = neighbor_index
    else:
        raise NavTopologyError("legacy route reconstruction contains a cycle")

    points.append(destination)
    return Route(
        algorithm=(
            "legacy-corrected-transition"
            if corrected_transition
            else "legacy-observed"
        ),
        source_triangle=source_triangle,
        destination_triangle=destination_triangle,
        corridor=tuple(corridor),
        exit_edges=tuple(exit_edges),
        points=tuple(points),
        search_cost=costs[source_triangle],
        expanded_nodes=expanded,
    )


def portal_state_route(
    topology: NavTopology,
    source_triangle: int,
    destination_triangle: int,
    *,
    source_point: Vec3 | None = None,
    destination_point: Vec3 | None = None,
) -> Route:
    """Find the exact shortest route under the portal-midpoint objective."""

    source, destination = _validate_route_request(
        topology,
        source_triangle,
        destination_triangle,
        source_point,
        destination_point,
    )
    if source_triangle == destination_triangle:
        return Route(
            algorithm="portal-state-dijkstra",
            source_triangle=source_triangle,
            destination_triangle=destination_triangle,
            corridor=(source_triangle,),
            exit_edges=(),
            points=(source, destination),
            search_cost=_distance(source, destination),
            expanded_nodes=1,
        )

    mesh = topology.mesh
    start = (source_triangle, -1)
    distances: dict[tuple[int, int], float] = {start: 0.0}
    parents: dict[tuple[int, int], tuple[tuple[int, int], int]] = {}
    heap: list[tuple[float, int, tuple[int, int]]] = [(0.0, 0, start)]
    next_order = 1
    best_terminal = math.inf
    terminal_state: tuple[int, int] | None = None
    expanded = 0

    while heap:
        cost, _, state = heapq.heappop(heap)
        if cost != distances.get(state):
            continue
        if cost >= best_terminal:
            break
        expanded += 1
        triangle_index, ingress_edge = state
        if triangle_index == destination_triangle:
            total = cost + _distance(
                mesh.portal_midpoints[triangle_index][ingress_edge],
                destination,
            )
            if total < best_terminal:
                best_terminal = total
                terminal_state = state
            continue

        for exit_edge in range(3):
            if exit_edge == ingress_edge:
                continue
            neighbor_index = topology.neighbor(triangle_index, exit_edge)
            if neighbor_index is None:
                continue
            reciprocal_edge = mesh.reciprocal_edges[triangle_index][exit_edge]
            if reciprocal_edge < 0:
                raise NavTopologyError(
                    f"triangle {triangle_index} edge {exit_edge} lacks a "
                    "reciprocal edge"
                )
            exit_midpoint = mesh.portal_midpoints[triangle_index][exit_edge]
            step_cost = (
                _distance(source, exit_midpoint)
                if ingress_edge < 0
                else _distance(
                    mesh.portal_midpoints[triangle_index][ingress_edge],
                    exit_midpoint,
                )
            )
            next_state = (neighbor_index, reciprocal_edge)
            next_cost = cost + step_cost
            if next_cost >= distances.get(next_state, math.inf):
                continue
            distances[next_state] = next_cost
            parents[next_state] = (state, exit_edge)
            heapq.heappush(heap, (next_cost, next_order, next_state))
            next_order += 1

    if terminal_state is None:
        raise RouteNotFound(
            f"no active route from triangle {source_triangle} to "
            f"{destination_triangle}"
        )

    transitions: list[tuple[int, int, int]] = []
    state = terminal_state
    while state != start:
        previous, exit_edge = parents[state]
        transitions.append((previous[0], exit_edge, state[0]))
        state = previous
    transitions.reverse()

    corridor = [source_triangle]
    exit_edges: list[int] = []
    points = [source]
    for triangle_index, exit_edge, neighbor_index in transitions:
        if triangle_index != corridor[-1]:
            raise NavTopologyError("portal-state reconstruction is discontinuous")
        exit_edges.append(exit_edge)
        points.append(mesh.portal_midpoints[triangle_index][exit_edge])
        corridor.append(neighbor_index)
    points.append(destination)
    return Route(
        algorithm="portal-state-dijkstra",
        source_triangle=source_triangle,
        destination_triangle=destination_triangle,
        corridor=tuple(corridor),
        exit_edges=tuple(exit_edges),
        points=tuple(points),
        search_cost=best_terminal,
        expanded_nodes=expanded,
    )


def _triarea2(left: Vec3, middle: Vec3, right: Vec3) -> float:
    return (middle[0] - left[0]) * (right[2] - left[2]) - (
        middle[2] - left[2]
    ) * (right[0] - left[0])


def _vequal(left: Vec3, right: Vec3, epsilon: float = 1e-6) -> bool:
    return (
        (left[0] - right[0]) ** 2 + (left[2] - right[2]) ** 2
        <= epsilon * epsilon
    )


def _orient_portal(
    left_candidate: Vec3,
    right_candidate: Vec3,
    from_point: Vec3,
    to_point: Vec3,
) -> Portal:
    direction = (
        to_point[0] - from_point[0],
        0.0,
        to_point[2] - from_point[2],
    )
    left_side = direction[0] * (left_candidate[2] - from_point[2]) - direction[
        2
    ] * (left_candidate[0] - from_point[0])
    right_side = direction[0] * (right_candidate[2] - from_point[2]) - direction[
        2
    ] * (right_candidate[0] - from_point[0])
    if left_side <= right_side:
        return Portal(left_candidate, right_candidate)
    return Portal(right_candidate, left_candidate)


def corridor_portals(mesh: NavMesh, route: Route) -> tuple[Portal, ...]:
    if len(route.corridor) != len(route.exit_edges) + 1:
        raise NavTopologyError("route corridor and exit-edge counts are inconsistent")
    portals: list[Portal] = []
    for index, edge_index in enumerate(route.exit_edges):
        triangle_index = route.corridor[index]
        neighbor_index = route.corridor[index + 1]
        edge = mesh.triangles[triangle_index].edge(edge_index)
        portals.append(
            _orient_portal(
                edge[0],
                edge[1],
                mesh.centroids[triangle_index],
                mesh.centroids[neighbor_index],
            )
        )
    return tuple(portals)


def _shrink_portal(portal: Portal, radius: float) -> Portal:
    if radius < 0:
        raise NavTopologyError("agent radius cannot be negative")
    if radius == 0:
        return portal
    width = _distance(portal.left, portal.right, planar=True)
    if width <= 2.0 * radius:
        raise RouteNotFound(
            f"portal width {width:.6g} cannot provide radius {radius:.6g} clearance"
        )
    fraction = radius / width

    def interpolate(start: Vec3, end: Vec3) -> Vec3:
        return tuple(
            start[index] + (end[index] - start[index]) * fraction
            for index in range(3)
        )

    return Portal(
        interpolate(portal.left, portal.right),
        interpolate(portal.right, portal.left),
    )


def funnel_path(
    start: Vec3,
    portals: Sequence[Portal],
    destination: Vec3,
    *,
    radius: float = 0.0,
) -> tuple[Vec3, ...]:
    """String-pull an oriented X/Z portal corridor, optionally shrinking portals."""

    shrunk = tuple(_shrink_portal(portal, radius) for portal in portals)
    sequence = (Portal(start, start), *shrunk, Portal(destination, destination))
    apex = sequence[0].left
    left = sequence[0].left
    right = sequence[0].right
    apex_index = left_index = right_index = 0
    result = [start]
    index = 1

    while index < len(sequence):
        next_left = sequence[index].left
        next_right = sequence[index].right

        if _triarea2(apex, right, next_right) <= 0.0:
            if _vequal(apex, right) or _triarea2(apex, left, next_right) > 0.0:
                right = next_right
                right_index = index
            else:
                result.append(left)
                apex = left
                apex_index = left_index
                left = apex
                right = apex
                left_index = apex_index
                right_index = apex_index
                index = apex_index + 1
                continue

        if _triarea2(apex, left, next_left) >= 0.0:
            if _vequal(apex, left) or _triarea2(apex, right, next_left) < 0.0:
                left = next_left
                left_index = index
            else:
                result.append(right)
                apex = right
                apex_index = right_index
                left = apex
                right = apex
                left_index = apex_index
                right_index = apex_index
                index = apex_index + 1
                continue

        index += 1

    if not _vequal(result[-1], destination):
        result.append(destination)
    else:
        result[-1] = destination

    deduplicated = [result[0]]
    for point in result[1:]:
        if not _vequal(deduplicated[-1], point):
            deduplicated.append(point)
        else:
            deduplicated[-1] = point
    return tuple(deduplicated)


def funnel_route(
    mesh: NavMesh,
    route: Route,
    *,
    radius: float = 0.0,
) -> tuple[Vec3, ...]:
    return funnel_path(
        route.points[0],
        corridor_portals(mesh, route),
        route.points[-1],
        radius=radius,
    )


def polyline_length(points: Sequence[Vec3], *, planar: bool = False) -> float:
    return sum(
        _distance(points[index - 1], points[index], planar=planar)
        for index in range(1, len(points))
    )


def largest_active_component(topology: NavTopology) -> tuple[int, ...]:
    remaining = {
        index for index, active in enumerate(topology.active) if active
    }
    largest: list[int] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        component = [start]
        frontier = [start]
        while frontier:
            triangle_index = frontier.pop()
            for edge_index in range(3):
                neighbor_index = topology.neighbor(triangle_index, edge_index)
                if neighbor_index is not None and neighbor_index in remaining:
                    remaining.remove(neighbor_index)
                    component.append(neighbor_index)
                    frontier.append(neighbor_index)
        if len(component) > len(largest):
            largest = component
    return tuple(sorted(largest))


def load_nav_resources(path: Path) -> tuple[NavResource, ...]:
    """Load direct NAV files or NAV members from N3 stage resource archives."""

    if not path.exists():
        raise NavFormatError(f"input path does not exist: {path}")
    candidates: list[Path]
    if path.is_file():
        candidates = [path]
    else:
        direct = sorted(
            (
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file() and candidate.suffix.casefold() == ".nav"
            ),
            key=lambda candidate: str(candidate).casefold(),
        )
        stage_archives = sorted(
            path.rglob("*_res1_res.pak"),
            key=lambda candidate: str(candidate).casefold(),
        )
        candidates = [*direct, *stage_archives]

    resources: list[NavResource] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        suffix = candidate.suffix.casefold()
        if suffix == ".nav":
            try:
                data = candidate.read_bytes()
            except OSError as error:
                raise NavFormatError(f"cannot read {candidate}: {error}") from error
            key = (candidate.name.casefold(), hashlib.sha256(data).hexdigest())
            if key not in seen:
                seen.add(key)
                resources.append(NavResource(candidate.name, str(candidate), data))
            continue
        if suffix != ".pak":
            raise NavFormatError(
                f"unsupported input {candidate}; expected .NAV, .PAK, or a directory"
            )
        try:
            archive = read_pak(candidate)
        except GameplayDataError as error:
            raise NavFormatError(str(error)) from error
        for member in archive.members:
            if not member.name.casefold().endswith(".nav"):
                continue
            data = archive.read_member(member)
            name = Path(member.name.replace("\\", "/")).name
            key = (name.casefold(), hashlib.sha256(data).hexdigest())
            if key in seen:
                continue
            seen.add(key)
            resources.append(
                NavResource(name, f"{candidate}!{member.name}", data)
            )

    if not resources:
        raise NavFormatError(f"no NAV resources found under {path}")
    return tuple(sorted(resources, key=lambda resource: resource.name.casefold()))


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _ratio_summary(
    values: Sequence[float],
) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "minimum": None,
            "mean": None,
            "median": None,
            "p95": None,
            "maximum": None,
        }
    return {
        "count": len(values),
        "minimum": min(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": _percentile(values, 0.95),
        "maximum": max(values),
    }


def analyze_resources(
    resources: Sequence[NavResource],
    *,
    samples_per_mesh: int = 40,
    seed: int = DEFAULT_SEED,
    radius: float = 0.0,
) -> dict[str, object]:
    if samples_per_mesh <= 0:
        raise NavError("samples per mesh must be positive")
    if radius < 0:
        raise NavError("agent radius cannot be negative")

    rng = random.Random(seed)
    legacy_ratios: list[float] = []
    corrected_ratios: list[float] = []
    funnel_ratios: list[float] = []
    midpoint_point_counts: list[int] = []
    funnel_point_counts: list[int] = []
    mesh_reports: list[dict[str, object]] = []
    route_samples = 0
    legacy_suboptimal = 0
    corrected_suboptimal = 0
    funnel_over_one_percent = 0
    funnel_invariant_failures = 0
    route_failures: list[str] = []
    total_triangles = 0
    total_dynamic_triangles = 0
    total_dynamic_ranges = 0

    for resource in resources:
        mesh = parse_nav(resource.data, name=resource.name)
        topology = mesh.topology()
        component = largest_active_component(topology)
        total_triangles += len(mesh.triangles)
        total_dynamic_triangles += sum(
            triangle.attribute != 0 for triangle in mesh.triangles
        )
        total_dynamic_ranges += len(mesh.dynamic_ranges)
        mesh_report: dict[str, object] = {
            "name": resource.name,
            "origin": resource.origin,
            "triangles": len(mesh.triangles),
            "dynamicTriangles": sum(
                triangle.attribute != 0 for triangle in mesh.triangles
            ),
            "dynamicRanges": len(mesh.dynamic_ranges),
            "largestStaticComponent": len(component),
            "issues": [
                {"code": issue.code, "message": issue.message}
                for issue in mesh.issues
            ],
            "samples": 0,
        }
        mesh_reports.append(mesh_report)
        if len(component) < 2:
            continue

        for sample_index in range(samples_per_mesh):
            source_triangle, destination_triangle = rng.sample(component, 2)
            try:
                legacy = legacy_route(
                    topology, source_triangle, destination_triangle
                )
                corrected = legacy_route(
                    topology,
                    source_triangle,
                    destination_triangle,
                    corrected_transition=True,
                )
                optimal = portal_state_route(
                    topology, source_triangle, destination_triangle
                )
                pulled = funnel_route(mesh, legacy, radius=radius)
            except NavError as error:
                route_failures.append(
                    f"{resource.name} sample {sample_index}: {error}"
                )
                continue

            if optimal.length <= 0:
                continue
            legacy_ratio = legacy.length / optimal.length
            corrected_ratio = corrected.length / optimal.length
            legacy_ratios.append(legacy_ratio)
            corrected_ratios.append(corrected_ratio)
            if legacy_ratio > 1.000001:
                legacy_suboptimal += 1
            if corrected_ratio > 1.000001:
                corrected_suboptimal += 1

            midpoint_length = legacy.planar_length
            pulled_length = polyline_length(pulled, planar=True)
            if pulled_length > midpoint_length + 1e-5:
                funnel_invariant_failures += 1
            if pulled_length > 0:
                funnel_ratio = midpoint_length / pulled_length
                funnel_ratios.append(funnel_ratio)
                if funnel_ratio > 1.01:
                    funnel_over_one_percent += 1
            midpoint_point_counts.append(len(legacy.points))
            funnel_point_counts.append(len(pulled))
            route_samples += 1
            mesh_report["samples"] = int(mesh_report["samples"]) + 1

    funnel_summary = _ratio_summary(funnel_ratios)
    funnel_summary.update(
        {
            "moreThanOnePercentCount": funnel_over_one_percent,
            "invariantFailures": funnel_invariant_failures,
            "meanMidpointPoints": (
                statistics.fmean(midpoint_point_counts)
                if midpoint_point_counts
                else None
            ),
            "meanFunnelPoints": (
                statistics.fmean(funnel_point_counts)
                if funnel_point_counts
                else None
            ),
            "meanPointReduction": (
                1.0
                - statistics.fmean(funnel_point_counts)
                / statistics.fmean(midpoint_point_counts)
                if midpoint_point_counts
                else None
            ),
            "radius": radius,
        }
    )
    legacy_summary = _ratio_summary(legacy_ratios)
    legacy_summary["suboptimalCount"] = legacy_suboptimal
    corrected_summary = _ratio_summary(corrected_ratios)
    corrected_summary["suboptimalCount"] = corrected_suboptimal

    return {
        "seed": seed,
        "samplesPerMesh": samples_per_mesh,
        "meshCount": len(mesh_reports),
        "routeSamples": route_samples,
        "totals": {
            "triangles": total_triangles,
            "dynamicTriangles": total_dynamic_triangles,
            "dynamicRanges": total_dynamic_ranges,
        },
        "legacyToPortalState": legacy_summary,
        "correctedToPortalState": corrected_summary,
        "midpointToFunnel": funnel_summary,
        "routeFailures": route_failures,
        "meshes": mesh_reports,
    }


def _mesh_summary(resource: NavResource) -> dict[str, object]:
    mesh = parse_nav(resource.data, name=resource.name)
    topology = mesh.topology()
    return {
        "name": resource.name,
        "origin": resource.origin,
        "triangles": len(mesh.triangles),
        "activeTriangles": sum(topology.active),
        "dynamicTriangles": sum(
            triangle.attribute != 0 for triangle in mesh.triangles
        ),
        "dynamicRanges": [
            {"start": item.start, "count": item.count}
            for item in mesh.dynamic_ranges
        ],
        "largestStaticComponent": len(largest_active_component(topology)),
        "issues": [
            {"code": issue.code, "message": issue.message}
            for issue in mesh.issues
        ],
    }


def _parse_integer(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid integer: {value}") from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="parse and validate one NAV file or stage archive"
    )
    inspect_parser.add_argument("path", type=Path)

    analyze_parser = subparsers.add_parser(
        "analyze", help="sample routes across owned stage NAV resources"
    )
    analyze_parser.add_argument("path", type=Path)
    analyze_parser.add_argument("--samples", type=int, default=40)
    analyze_parser.add_argument("--seed", type=_parse_integer, default=DEFAULT_SEED)
    analyze_parser.add_argument("--radius", type=float, default=0.0)
    analyze_parser.add_argument(
        "--output",
        type=Path,
        help="write JSON to this path instead of standard output",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        resources = load_nav_resources(arguments.path)
        if arguments.command == "inspect":
            if len(resources) != 1:
                raise NavError(
                    f"inspect requires exactly one NAV resource; found "
                    f"{len(resources)}"
                )
            report: object = _mesh_summary(resources[0])
        else:
            report = analyze_resources(
                resources,
                samples_per_mesh=arguments.samples,
                seed=arguments.seed,
                radius=arguments.radius,
            )
        output = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if arguments.command == "analyze" and arguments.output is not None:
            arguments.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except (NavError, OSError) as error:
        parser.exit(1, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
