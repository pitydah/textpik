"""Tests for explicit placement-backend selection and revision leases.

The selection must never be optimistic: if a compositor authority is missing we
degrade loudly instead of reporting a position Qt invented.
"""

from src.textpik_core.placement import (
    PresentationLease,
    select_placement_backend,
)


class TestBackendSelection:
    def test_x11_uses_native_backend(self):
        choice = select_placement_backend(platform_name="xcb", desktop="kde")
        assert choice.backend.value == "x11"
        assert choice.authoritative is True
        assert choice.reason == "x11-session"

    def test_plasma_wayland_requires_the_effect(self):
        choice = select_placement_backend(
            platform_name="wayland", desktop="KDE", effect_available=True
        )
        assert choice.backend.value == "kwin-effect"
        assert choice.authoritative is True

    def test_plasma_wayland_without_effect_is_explicitly_unverified(self):
        choice = select_placement_backend(
            platform_name="wayland", desktop="KDE", effect_available=False
        )
        assert choice.backend.value == "qt-xdg-toplevel-unverified"
        assert choice.authoritative is False
        assert "kwin-effect" in choice.reason

    def test_generic_wayland_is_never_authoritative(self):
        for desktop in ("gnome", "sway", "hyprland", "weston", ""):
            choice = select_placement_backend(
                platform_name="wayland-egl", desktop=desktop, effect_available=False
            )
            assert choice.authoritative is False, desktop

    def test_unknown_desktop_does_not_inherit_kwin_authority(self):
        choice = select_placement_backend(
            platform_name="wayland", desktop="weird", effect_available=True
        )
        assert choice.backend.value != "kwin-effect"

    def test_offscreen_never_claims_authority(self):
        choice = select_placement_backend(platform_name="offscreen", desktop="kde")
        assert choice.authoritative is False


class TestPresentationLease:
    def test_first_request_becomes_active_revision(self):
        lease = PresentationLease()
        assert lease.begin() == 1
        assert lease.active_revision == 1

    def test_second_request_supersedes_the_first(self):
        lease = PresentationLease()
        lease.begin()
        assert lease.begin() == 2
        assert lease.active_revision == 2

    def test_confirmation_for_superseded_revision_is_dropped(self):
        lease = PresentationLease()
        first = lease.begin()
        lease.begin()  # user selected again
        assert lease.accept(first) is False

    def test_confirmation_for_active_revision_is_accepted(self):
        lease = PresentationLease()
        revision = lease.begin()
        assert lease.accept(revision) is True

    def test_out_of_order_confirmations_only_apply_the_newest(self):
        lease = PresentationLease()
        r1 = lease.begin()
        r2 = lease.begin()
        assert lease.accept(r2) is True
        assert lease.accept(r1) is False
        assert lease.applied_revision == r2

    def test_release_drops_pending_confirmations(self):
        lease = PresentationLease()
        revision = lease.begin()
        lease.release()
        assert lease.accept(revision) is False
        assert lease.active_revision == 0

    def test_revision_never_repeats_after_release(self):
        lease = PresentationLease()
        first = lease.begin()
        lease.release()
        assert lease.begin() > first
