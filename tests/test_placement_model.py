"""Contract tests for the placement authority model.

These tests encode the rule that broke the popup on Plasma Wayland: a requested
position is never evidence of an applied position, and only a compositor
authority can set ``observed_position``.
"""

import unittest

from src.textpik_core.models import (
    PlacementBackend,
    PlacementOutcome,
    PlacementReason,
    Point,
    PopupPlacementResult,
    Rect,
)


class PlacementResultTest(unittest.TestCase):
    def test_unverified_result_never_claims_observed_position(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED,
            desired=Point(760, 430),
            requested=Point(760, 430),
        )
        self.assertFalse(result.verified)
        self.assertIsNone(result.observed)
        self.assertEqual(result.outcome, PlacementOutcome.UNVERIFIED)

    def test_only_compositor_backends_may_report_observed(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(10, 20),
            requested=Point(10, 20),
            observed=Point(10, 20),
        )
        self.assertTrue(result.verified)
        self.assertEqual(result.outcome, PlacementOutcome.VERIFIED)

    def test_qt_backend_cannot_be_forced_to_verified_by_observed(self):
        """A caller supplying ``observed`` on an untrusted backend must not win."""
        result = PopupPlacementResult(
            backend=PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED,
            desired=Point(760, 430),
            requested=Point(760, 430),
            observed=Point(760, 430),
        )
        self.assertFalse(result.verified)
        self.assertIsNone(result.observed)

    def test_observed_outside_tolerance_is_not_verified(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(700, 460),
            requested=Point(700, 460),
            observed=Point(960, 540),
            tolerance=2,
        )
        self.assertFalse(result.verified)
        self.assertEqual(result.outcome, PlacementOutcome.MISMATCH)
        self.assertEqual(result.error, "position-mismatch")

    def test_observed_within_tolerance_is_verified(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(700, 460),
            requested=Point(700, 460),
            observed=Point(701, 461),
            tolerance=2,
        )
        self.assertTrue(result.verified)

    def test_size_mismatch_blocks_verification_even_if_origin_matches(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(700, 460),
            requested=Point(700, 460),
            observed=Point(700, 460),
            requested_size=(320, 90),
            observed_size=(1, 1),
            tolerance=2,
        )
        self.assertFalse(result.verified)
        self.assertEqual(result.error, "size-mismatch")

    def test_no_observed_means_unverified_not_error(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(700, 460),
            requested=Point(700, 460),
        )
        self.assertFalse(result.verified)
        self.assertEqual(result.outcome, PlacementOutcome.UNVERIFIED)
        self.assertIsNone(result.error)

    def test_backend_unavailable_reports_backend_unavailable(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.UNAVAILABLE,
            desired=Point(1, 2),
            requested=Point(1, 2),
        )
        self.assertFalse(result.verified)
        self.assertEqual(result.outcome, PlacementOutcome.BACKEND_UNAVAILABLE)
        self.assertEqual(result.error, "placement-backend-unavailable")

    def test_stale_revision_is_rejected(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(10, 20),
            requested=Point(10, 20),
            observed=Point(10, 20),
            revision=41,
            active_revision=42,
        )
        self.assertFalse(result.verified)
        self.assertEqual(result.outcome, PlacementOutcome.STALE)
        self.assertEqual(result.error, "stale-revision")

    def test_matching_revision_is_accepted(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(10, 20),
            requested=Point(10, 20),
            observed=Point(10, 20),
            revision=42,
            active_revision=42,
        )
        self.assertTrue(result.verified)

    def test_x11_backend_is_a_compositor_authority(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.X11,
            desired=Point(5, 5),
            requested=Point(5, 5),
            observed=Point(5, 5),
        )
        self.assertTrue(result.verified)
        self.assertEqual(result.outcome, PlacementOutcome.VERIFIED)

    def test_authoritative_backends_ignore_tolerance_when_unobserved(self):
        for backend in (
            PlacementBackend.KWIN_EFFECT,
            PlacementBackend.X11,
        ):
            with self.subTest(backend=backend):
                result = PopupPlacementResult(
                    backend=backend, desired=Point(0, 0), requested=Point(0, 0)
                )
                self.assertFalse(result.verified)

    def test_result_serializes_for_logging_without_claimed_geometry(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED,
            desired=Point(760, 430),
            requested=Point(760, 430),
            requested_size=(320, 90),
        )
        payload = result.as_dict()
        self.assertFalse(payload["verified"])
        self.assertIsNone(payload["observed"])
        self.assertEqual(payload["requested"], (760, 430))
        self.assertEqual(payload["desired"], (760, 430))

    def test_constrained_position_is_preserved_separately_from_desired(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(1900, 1000),
            requested=Point(1580, 900),
            constrained=Point(1580, 900),
            observed=Point(1580, 900),
            requested_size=(320, 90),
            observed_size=(320, 90),
        )
        self.assertTrue(result.verified)
        self.assertEqual(result.desired.as_tuple(), (1900, 1000))
        self.assertEqual(result.constrained.as_tuple(), (1580, 900))


class CursorProximityTest(unittest.TestCase):
    """``verified`` proves the move, not that the move aimed at the cursor."""

    def _centred_at_960_540_with_cursor_at_1559_668(self):
        # The exact shape of the field failure: KWin moved the window where it
        # was asked, but it was asked for the centre of the screen.
        return PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(960, 540),
            requested=Point(960, 540),
            observed=Point(960, 540),
            requested_size=(413, 35),
            observed_size=(413, 35),
            cursor=Point(1559, 668),
        )

    def test_a_verified_placement_far_from_the_cursor_is_not_proximity_verified(
        self,
    ):
        result = self._centred_at_960_540_with_cursor_at_1559_668()
        self.assertTrue(result.verified, "el compositor si movio la ventana")
        self.assertFalse(
            result.cursor_proximity_verified,
            "un popup en el centro no esta junto al cursor",
        )
        self.assertGreater(result.cursor_edge_distance(), 32)

    def test_a_popup_beside_the_cursor_is_proximity_verified(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(1565, 674),
            requested=Point(1565, 674),
            observed=Point(1565, 674),
            requested_size=(116, 33),
            observed_size=(116, 33),
            cursor=Point(1559, 668),
        )
        self.assertTrue(result.verified)
        self.assertTrue(result.cursor_proximity_verified)

    def test_distance_is_measured_to_the_border_not_the_centre(self):
        # Cursor just left of a wide bar: touching its left edge is correct
        # placement even though the centre is 200px away.
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(1006, 460),
            requested=Point(1006, 460),
            observed=Point(1006, 460),
            requested_size=(400, 33),
            observed_size=(400, 33),
            cursor=Point(1000, 470),
        )
        self.assertEqual(result.cursor_edge_distance(), 6)
        self.assertTrue(result.cursor_proximity_verified)

    def test_cursor_inside_the_popup_projection_has_zero_distance(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(900, 460),
            requested=Point(900, 460),
            observed=Point(900, 460),
            requested_size=(400, 33),
            observed_size=(400, 33),
            cursor=Point(1000, 470),
        )
        self.assertEqual(result.cursor_edge_distance(), 0)

    def test_without_cursor_evidence_proximity_is_never_claimed(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(10, 10),
            requested=Point(10, 10),
            observed=Point(10, 10),
            requested_size=(116, 33),
            observed_size=(116, 33),
        )
        self.assertIsNone(result.cursor_edge_distance())
        self.assertFalse(result.cursor_proximity_verified)

    def test_a_non_authoritative_backend_never_claims_proximity(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED,
            desired=Point(10, 10),
            requested=Point(10, 10),
            cursor=Point(10, 10),
        )
        self.assertFalse(result.cursor_proximity_verified)

    def test_result_records_the_selection_generation_and_reason(self):
        result = PopupPlacementResult(
            backend=PlacementBackend.KWIN_EFFECT,
            desired=Point(1565, 674),
            requested=Point(1565, 674),
            observed=Point(1565, 674),
            requested_size=(116, 33),
            observed_size=(116, 33),
            cursor=Point(1559, 668),
            cursor_age_ms=8.0,
            anchor_source="kwin",
            selection_generation=142,
            reason=PlacementReason.CURSOR_LOCAL,
        )
        payload = result.as_dict()
        self.assertEqual(payload["selection_generation"], 142)
        self.assertEqual(payload["anchor_source"], "kwin")
        self.assertEqual(payload["cursor_age_ms"], 8.0)
        self.assertEqual(payload["reason"], "cursor-local")
        self.assertTrue(payload["cursor_proximity_verified"])


class GeometryTypeTest(unittest.TestCase):
    def test_rect_repr_is_available_for_area_math(self):
        rect = Rect(10, 20, 100, 50)
        self.assertEqual(rect.width, 100)
        self.assertEqual(rect.height, 50)
        self.assertEqual(rect.right(), 110)
        self.assertEqual(rect.bottom(), 70)

    def test_point_serializes_to_a_tuple(self):
        self.assertEqual(Point(3, 4).as_tuple(), (3, 4))


if __name__ == "__main__":
    unittest.main()
