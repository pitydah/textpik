"""Tests for explicit placement-backend selection and revision leases.

The selection must never be optimistic: if a compositor authority is missing we
degrade loudly instead of reporting a position Qt invented.
"""

import unittest

from src.textpik_core.placement import (
    PresentationLease,
    select_placement_backend,
)


class BackendSelectionTest(unittest.TestCase):
    def test_x11_uses_native_backend(self):
        choice = select_placement_backend(platform_name="xcb", desktop="kde")
        self.assertEqual(choice.backend.value, "x11")
        self.assertTrue(choice.authoritative)
        self.assertEqual(choice.reason, "x11-session")

    def test_plasma_wayland_requires_the_effect(self):
        choice = select_placement_backend(
            platform_name="wayland", desktop="KDE", effect_available=True
        )
        self.assertEqual(choice.backend.value, "kwin-effect")
        self.assertTrue(choice.authoritative)

    def test_plasma_wayland_without_effect_is_explicitly_unverified(self):
        choice = select_placement_backend(
            platform_name="wayland", desktop="KDE", effect_available=False
        )
        self.assertEqual(choice.backend.value, "qt-xdg-toplevel-unverified")
        self.assertFalse(choice.authoritative)
        self.assertIn("kwin-effect", choice.reason)

    def test_generic_wayland_is_never_authoritative(self):
        for desktop in ("gnome", "sway", "hyprland", "weston", ""):
            choice = select_placement_backend(
                platform_name="wayland-egl", desktop=desktop, effect_available=False
            )
            self.assertFalse(choice.authoritative, desktop)

    def test_unknown_desktop_does_not_inherit_kwin_authority(self):
        choice = select_placement_backend(
            platform_name="wayland", desktop="weird", effect_available=True
        )
        self.assertNotEqual(choice.backend.value, "kwin-effect")

    def test_offscreen_never_claims_authority(self):
        choice = select_placement_backend(platform_name="offscreen", desktop="kde")
        self.assertFalse(choice.authoritative)


class PresentationLeaseTest(unittest.TestCase):
    def test_first_request_becomes_active_revision(self):
        lease = PresentationLease()
        self.assertEqual(lease.begin(), 1)
        self.assertEqual(lease.active_revision, 1)

    def test_second_request_supersedes_the_first(self):
        lease = PresentationLease()
        lease.begin()
        self.assertEqual(lease.begin(), 2)
        self.assertEqual(lease.active_revision, 2)

    def test_confirmation_for_superseded_revision_is_dropped(self):
        lease = PresentationLease()
        first = lease.begin()
        lease.begin()  # user selected again
        self.assertFalse(lease.accept(first))

    def test_confirmation_for_active_revision_is_accepted(self):
        lease = PresentationLease()
        revision = lease.begin()
        self.assertTrue(lease.accept(revision))

    def test_out_of_order_confirmations_only_apply_the_newest(self):
        lease = PresentationLease()
        r1 = lease.begin()
        r2 = lease.begin()
        self.assertTrue(lease.accept(r2))
        self.assertFalse(lease.accept(r1))
        self.assertEqual(lease.applied_revision, r2)

    def test_release_drops_pending_confirmations(self):
        lease = PresentationLease()
        revision = lease.begin()
        lease.release()
        self.assertFalse(lease.accept(revision))
        self.assertEqual(lease.active_revision, 0)

    def test_revision_never_repeats_after_release(self):
        lease = PresentationLease()
        first = lease.begin()
        lease.release()
        self.assertGreater(lease.begin(), first)


if __name__ == "__main__":
    unittest.main()
