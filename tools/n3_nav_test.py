#!/usr/bin/env python3
"""Synthetic tests for the bounded N3 NAV parser and route analyzers."""

from __future__ import annotations

import json
import struct
import unittest

from tools.n3_nav import (
    DynamicRange,
    NavFormatError,
    NavResource,
    NavTopologyError,
    Portal,
    RouteNotFound,
    analyze_resources,
    corridor_portals,
    funnel_path,
    funnel_route,
    legacy_route,
    parse_nav,
    polyline_length,
    portal_state_route,
    transition_distance,
)


def _nav_bytes(
    triangles: list[
        tuple[
            tuple[
                tuple[float, float, float],
                tuple[float, float, float],
                tuple[float, float, float],
            ],
            int,
            tuple[int, int, int],
        ]
    ],
    dynamic_ranges: list[tuple[int, int]] | None = None,
) -> bytes:
    output = bytearray(16)
    output.extend(struct.pack(">I", len(triangles)))
    for vertices, attribute, _ in triangles:
        for vertex in vertices:
            output.extend(struct.pack(">fff", *vertex))
        output.extend(struct.pack(">I", attribute))
    for _, _, neighbors in triangles:
        output.extend(struct.pack(">iii", *neighbors))
    ranges = dynamic_ranges or []
    output.extend(struct.pack(">I", len(ranges)))
    for start, count in ranges:
        output.extend(struct.pack(">II", start, count))
    return bytes(output)


def _two_triangle_nav(*, dynamic_second: bool = False) -> bytes:
    return _nav_bytes(
        [
            (
                ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 0.0, 2.0)),
                0,
                (-1, 1, -1),
            ),
            (
                ((2.0, 0.0, 0.0), (2.0, 0.0, 2.0), (0.0, 0.0, 2.0)),
                1 if dynamic_second else 0,
                (-1, -1, 0),
            ),
        ],
        [(1, 1)] if dynamic_second else [],
    )


def _three_triangle_nav() -> bytes:
    return _nav_bytes(
        [
            (
                ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 0.0, 2.0)),
                0,
                (-1, 1, -1),
            ),
            (
                ((2.0, 0.0, 0.0), (2.0, 0.0, 2.0), (0.0, 0.0, 2.0)),
                0,
                (-1, 2, 0),
            ),
            (
                ((2.0, 0.0, 2.0), (4.0, 0.0, 2.0), (0.0, 0.0, 2.0)),
                0,
                (-1, -1, 1),
            ),
        ]
    )


class NavParserTests(unittest.TestCase):
    def test_parses_big_endian_geometry_and_reciprocal_edges(self) -> None:
        mesh = parse_nav(_two_triangle_nav(), name="synthetic.nav")

        self.assertEqual(len(mesh.triangles), 2)
        self.assertEqual(mesh.triangles[0].neighbors, (-1, 1, -1))
        self.assertEqual(mesh.reciprocal_edges[0], (-1, 2, -1))
        self.assertEqual(mesh.issues, ())

    def test_rejects_nonzero_prefix_truncation_and_trailing_data(self) -> None:
        valid = _two_triangle_nav()
        with self.assertRaisesRegex(NavFormatError, "reserved"):
            parse_nav(b"\x01" + valid[1:])
        with self.assertRaisesRegex(NavFormatError, "truncated"):
            parse_nav(valid[:-1])
        with self.assertRaisesRegex(NavFormatError, "trailing"):
            parse_nav(valid + b"\x00")

    def test_rejects_out_of_range_neighbor(self) -> None:
        data = _nav_bytes(
            [
                (
                    ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
                    0,
                    (4, -1, -1),
                )
            ]
        )
        with self.assertRaisesRegex(NavFormatError, "out-of-range neighbor"):
            parse_nav(data)

    def test_reports_nonreciprocal_adjacency(self) -> None:
        data = _nav_bytes(
            [
                (
                    ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 0.0, 2.0)),
                    0,
                    (-1, 1, -1),
                ),
                (
                    ((2.0, 0.0, 0.0), (2.0, 0.0, 2.0), (0.0, 0.0, 2.0)),
                    0,
                    (-1, -1, -1),
                ),
            ]
        )
        mesh = parse_nav(data)

        self.assertIn("adjacency.nonreciprocal", {issue.code for issue in mesh.issues})
        with self.assertRaisesRegex(NavTopologyError, "not routable"):
            mesh.topology()

    def test_preserves_but_reports_invalid_dynamic_range(self) -> None:
        mesh = parse_nav(
            _nav_bytes(
                [
                    (
                        (
                            (0.0, 0.0, 0.0),
                            (1.0, 0.0, 0.0),
                            (0.0, 0.0, 1.0),
                        ),
                        1,
                        (-1, -1, -1),
                    )
                ],
                [(4, 2)],
            )
        )

        self.assertEqual(mesh.dynamic_ranges, (DynamicRange(4, 2),))
        codes = {issue.code for issue in mesh.issues}
        self.assertIn("dynamic.invalid-range", codes)
        self.assertIn("dynamic.uncovered", codes)
        with self.assertRaisesRegex(NavTopologyError, "outside 1 triangles"):
            mesh.topology().set_dynamic_group(0, active=True)


class TopologyAndRouteTests(unittest.TestCase):
    def test_dynamic_group_changes_connectivity_and_generation(self) -> None:
        mesh = parse_nav(_two_triangle_nav(dynamic_second=True))
        topology = mesh.topology()

        self.assertIsNone(topology.neighbor(0, 1))
        with self.assertRaises(RouteNotFound):
            legacy_route(topology, 0, 1)
        topology.set_dynamic_group(0, active=True)
        self.assertEqual(topology.generation, 1)
        self.assertEqual(topology.neighbor(0, 1), 1)
        self.assertEqual(legacy_route(topology, 0, 1).corridor, (0, 1))
        topology.set_dynamic_group(0, active=False)
        self.assertEqual(topology.generation, 2)
        self.assertIsNone(topology.neighbor(0, 1))

    def test_legacy_route_emits_source_portal_and_destination(self) -> None:
        mesh = parse_nav(_two_triangle_nav())
        route = legacy_route(mesh.topology(), 0, 1)

        self.assertEqual(route.corridor, (0, 1))
        self.assertEqual(route.exit_edges, (1,))
        self.assertEqual(len(route.points), 3)
        self.assertEqual(route.points[1], (1.0, 0.0, 1.0))
        self.assertEqual(len(corridor_portals(mesh, route)), 1)

    def test_observed_transition_index_differs_from_correct_pair(self) -> None:
        mesh = parse_nav(
            _nav_bytes(
                [
                    (
                        (
                            (0.0, 0.0, 0.0),
                            (8.0, 0.0, 0.0),
                            (0.0, 0.0, 2.0),
                        ),
                        0,
                        (-1, -1, -1),
                    )
                ]
            )
        )

        observed = transition_distance(mesh, 0, 0, 1, corrected=False)
        corrected = transition_distance(mesh, 0, 0, 1, corrected=True)
        self.assertEqual(observed, mesh.portal_distances[0][1])
        self.assertEqual(corrected, mesh.portal_distances[0][0])
        self.assertNotEqual(observed, corrected)

    def test_portal_state_dijkstra_accounts_for_both_endpoints(self) -> None:
        mesh = parse_nav(_two_triangle_nav())
        source = (0.1, 0.0, 0.1)
        destination = (1.9, 0.0, 1.9)
        route = portal_state_route(
            mesh.topology(),
            0,
            1,
            source_point=source,
            destination_point=destination,
        )

        self.assertEqual(route.points, (source, (1.0, 0.0, 1.0), destination))
        self.assertAlmostEqual(route.search_cost, route.length)


class FunnelTests(unittest.TestCase):
    def test_route_derived_portal_orientation_preserves_length_invariant(
        self,
    ) -> None:
        mesh = parse_nav(_three_triangle_nav())
        route = legacy_route(mesh.topology(), 0, 2)

        pulled = funnel_route(mesh, route)

        self.assertLessEqual(
            polyline_length(pulled, planar=True),
            route.planar_length,
        )

    def test_funnel_shortens_a_bent_midpoint_path(self) -> None:
        start = (0.0, 0.0, 0.0)
        destination = (6.0, 0.0, 4.0)
        portals = (
            Portal((1.0, 0.0, 3.0), (1.0, 0.0, -1.0)),
            Portal((4.0, 0.0, 5.0), (4.0, 0.0, 1.0)),
        )
        midpoint_path = (
            start,
            (1.0, 0.0, 1.0),
            (4.0, 0.0, 3.0),
            destination,
        )

        pulled = funnel_path(start, portals, destination)

        self.assertEqual(pulled, (start, destination))
        self.assertLess(
            polyline_length(pulled, planar=True),
            polyline_length(midpoint_path, planar=True),
        )

    def test_radius_shrinks_portals_and_rejects_insufficient_width(self) -> None:
        start = (0.0, 0.0, 0.0)
        destination = (2.0, 0.0, 0.0)
        portal = Portal((1.0, 0.0, 0.5), (1.0, 0.0, -0.5))

        self.assertEqual(
            funnel_path(start, (portal,), destination, radius=0.4),
            (start, destination),
        )
        with self.assertRaisesRegex(RouteNotFound, "cannot provide radius"):
            funnel_path(start, (portal,), destination, radius=0.5)


class ReportingTests(unittest.TestCase):
    def test_analysis_report_is_deterministic_and_strict_json(self) -> None:
        resource = NavResource("SYNTHETIC.NAV", "synthetic", _two_triangle_nav())

        first = analyze_resources((resource,), samples_per_mesh=4, seed=123)
        second = analyze_resources((resource,), samples_per_mesh=4, seed=123)

        self.assertEqual(first, second)
        json.dumps(first, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
