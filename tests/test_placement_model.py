"""Contract tests for the placement authority model.

These tests encode the rule that broke the popup on Plasma Wayland: a requested
position is never evidence of an applied position, and only a compositor
authority can set ``observed_position``.
"""

import pytest

from src.textpik_core.models import (
    PlacementBackend,
    PlacementOutcome,
    PopupPlacementResult,
    Point,
    Rect,
)


def test_unverified_result_never_claims_observed_position():
    result = PopupPlacementResult(
        backend=PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED,
        desired=Point(760, 430),
        requested=Point(760, 430),
    )
    assert result.verified is False
    assert result.observed is None
    assert result.outcome is PlacementOutcome.UNVERIFIED
    assert result.observed is not result.requested


def test_only_compositor_backends_may_report_observed():
    result = PopupPlacementResult(
        backend=PlacementBackend.KWIN_EFFECT,
        desired=Point(10, 20),
        requested=Point(10, 20),
        observed=Point(10, 20),
    )
    assert result.verified is True
    assert result.outcome is PlacementOutcome.VERIFIED


def test_qt_backend_cannot_be_forced_to_verified_by_observed():
    """A caller supplying ``observed`` on an untrusted backend must not win."""
    result = PopupPlacementResult(
        backend=PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED,
        desired=Point(760, 430),
        requested=Point(760, 430),
        observed=Point(760, 430),
    )
    assert result.verified is False
    assert result.observed is None


def test_observed_outside_tolerance_is_not_verified():
    result = PopupPlacementResult(
        backend=PlacementBackend.KWIN_EFFECT,
        desired=Point(700, 460),
        requested=Point(700, 460),
        observed=Point(960, 540),
        tolerance=2,
    )
    assert result.verified is False
    assert result.outcome is PlacementOutcome.MISMATCH
    assert result.error == "position-mismatch"


def test_observed_within_tolerance_is_verified():
    result = PopupPlacementResult(
        backend=PlacementBackend.KWIN_EFFECT,
        desired=Point(700, 460),
        requested=Point(700, 460),
        observed=Point(701, 461),
        tolerance=2,
    )
    assert result.verified is True


def test_size_mismatch_blocks_verification_even_if_origin_matches():
    result = PopupPlacementResult(
        backend=PlacementBackend.KWIN_EFFECT,
        desired=Point(700, 460),
        requested=Point(700, 460),
        observed=Point(700, 460),
        requested_size=(320, 90),
        observed_size=(1, 1),
        tolerance=2,
    )
    assert result.verified is False
    assert result.error == "size-mismatch"


def test_no_observed_means_unverified_not_error():
    result = PopupPlacementResult(
        backend=PlacementBackend.KWIN_EFFECT,
        desired=Point(700, 460),
        requested=Point(700, 460),
    )
    assert result.verified is False
    assert result.outcome is PlacementOutcome.UNVERIFIED
    assert result.error is None


def test_backend_unavailable_reports_backend_unavailable():
    result = PopupPlacementResult(
        backend=PlacementBackend.UNAVAILABLE,
        desired=Point(1, 2),
        requested=Point(1, 2),
    )
    assert result.verified is False
    assert result.outcome is PlacementOutcome.BACKEND_UNAVAILABLE
    assert result.error == "placement-backend-unavailable"


def test_stale_revision_is_rejected():
    result = PopupPlacementResult(
        backend=PlacementBackend.KWIN_EFFECT,
        desired=Point(10, 20),
        requested=Point(10, 20),
        observed=Point(10, 20),
        revision=41,
        active_revision=42,
    )
    assert result.verified is False
    assert result.outcome is PlacementOutcome.STALE
    assert result.error == "stale-revision"


def test_matching_revision_is_accepted():
    result = PopupPlacementResult(
        backend=PlacementBackend.KWIN_EFFECT,
        desired=Point(10, 20),
        requested=Point(10, 20),
        observed=Point(10, 20),
        revision=42,
        active_revision=42,
    )
    assert result.verified is True


def test_x11_backend_is_a_compositor_authority():
    result = PopupPlacementResult(
        backend=PlacementBackend.X11,
        desired=Point(5, 5),
        requested=Point(5, 5),
        observed=Point(5, 5),
    )
    assert result.verified is True
    assert result.outcome is PlacementOutcome.VERIFIED


@pytest.mark.parametrize(
    "backend",
    [
        PlacementBackend.KWIN_EFFECT,
        PlacementBackend.X11,
    ],
)
def test_authoritative_backends_ignore_tolerance_when_unobserved(backend):
    result = PopupPlacementResult(
        backend=backend, desired=Point(0, 0), requested=Point(0, 0)
    )
    assert result.verified is False


def test_result_serializes_for_logging_without_claimed_geometry():
    result = PopupPlacementResult(
        backend=PlacementBackend.QT_XDG_TOPLEVEL_UNVERIFIED,
        desired=Point(760, 430),
        requested=Point(760, 430),
        requested_size=(320, 90),
    )
    payload = result.as_dict()
    assert payload["verified"] is False
    assert payload["observed"] is None
    assert payload["requested"] == (760, 430)
    assert payload["desired"] == (760, 430)


def test_constrained_position_is_preserved_separately_from_desired():
    result = PopupPlacementResult(
        backend=PlacementBackend.KWIN_EFFECT,
        desired=Point(1900, 1000),
        requested=Point(1580, 900),
        constrained=Point(1580, 900),
        observed=Point(1580, 900),
        requested_size=(320, 90),
        observed_size=(320, 90),
    )
    assert result.verified is True
    assert result.desired == Point(1900, 1000)
    assert result.constrained == Point(1580, 900)


def test_rect_repr_is_available_for_area_math():
    rect = Rect(10, 20, 100, 50)
    assert rect.width == 100
    assert rect.height == 50
    assert rect.right() == 110
    assert rect.bottom() == 70
