"""Contract tests for the placement authority model.

These tests encode the rule that broke the popup on Plasma Wayland: a requested
position is never evidence of an applied position, and only a compositor
authority can set ``observed_position``.
"""

import unittest

from src.textpik_core.models import (
    PlacementBackend,
    PlacementOutcome,
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
