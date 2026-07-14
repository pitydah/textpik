"""Optional AT-SPI selection backend for Wayland and X11 desktops."""

from __future__ import annotations

from .models import AnchorSource, PopupAnchor, SelectionContext


class AtspiSelectionBackend:
    """Defensive adapter: importing TextPik never requires GI/AT-SPI."""

    def __init__(self, atspi=None):
        self.atspi = atspi or self._load()
        self._focused_node = None
        self._focus_listener = None
        self._selection_listener = None
        self._selection_callback = None
        self._install_focus_listener()

    @staticmethod
    def _load():
        try:
            import gi

            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi

            return Atspi
        except (ImportError, ValueError):
            return None

    @property
    def available(self) -> bool:
        return self.atspi is not None

    def _install_focus_listener(self):
        if not self.available:
            return
        try:
            self._focus_listener = self.atspi.EventListener.new(
                self._on_focus_event, None
            )
            self._focus_listener.register("object:state-changed:focused")
        except Exception:
            self._focus_listener = None

    def _on_focus_event(self, event):
        if getattr(event, "detail1", False):
            self._focused_node = getattr(event, "source", None)

    def subscribe_selection_changes(self, callback) -> bool:
        """Prefer accessibility events; callers may keep polling as fallback."""
        if not self.available or self._selection_listener is not None:
            return self._selection_listener is not None
        try:
            self._selection_callback = callback
            self._selection_listener = self.atspi.EventListener.new(
                self._on_selection_event, None
            )
            self._selection_listener.register("object:text-selection-changed")
            return True
        except Exception:
            self._selection_listener = None
            self._selection_callback = None
            return False

    def _on_selection_event(self, event):
        callback = self._selection_callback
        if callback is not None:
            callback(getattr(event, "source", None))

    def _focused(self, node=None, depth=0, budget=None):
        if not self.available or depth > 8:
            return None
        if node is None and self._focused_node is not None:
            return self._focused_node
        if budget is None:
            budget = [400]
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        if node is None:
            node = self.atspi.get_desktop(0)
        try:
            states = node.get_state_set()
            if states.contains(self.atspi.StateType.FOCUSED):
                return node
            for index in range(min(node.get_child_count(), 80)):
                found = self._focused(
                    node.get_child_at_index(index), depth + 1, budget
                )
                if found is not None:
                    return found
        except Exception:
            return None
        return None

    def read_selection(self, node=None) -> SelectionContext | None:
        node = self._focused(node)
        if node is None:
            return None
        try:
            text_iface = node.get_text_iface()
            start, end = text_iface.get_selection(0)
            if end <= start:
                return None
            role = self._role_name(node)
            name = self._application_name(node)
            sensitive = self._is_protected(node, role)
            coord = getattr(self.atspi.CoordType, "SCREEN", self.atspi.CoordType.SCREEN)
            rect = text_iface.get_range_extents(start, end, coord)
            # Never request contents from a password/secret accessible object.
            text = "" if sensitive else text_iface.get_text(start, end)
            anchor = PopupAnchor(
                int(rect.x + rect.width),
                int(rect.y + rect.height),
                AnchorSource.ATSPI_SELECTION,
                1.0,
            )
            return SelectionContext(
                text=text,
                anchor=anchor,
                application=name,
                role=role,
                sensitive=sensitive,
                editable=self._editable(node) is not None,
                selection_start=start,
                selection_end=end,
                backend="atspi",
                selection_rect=(int(rect.x), int(rect.y), int(rect.width), int(rect.height)),
                native_handle=node,
            )
        except Exception:
            return None

    def _is_protected(self, node, role: str) -> bool:
        if any(token in role.casefold() for token in ("password", "secret", "protected")):
            return True
        try:
            protected = getattr(self.atspi.StateType, "PROTECTED", None)
            return protected is not None and node.get_state_set().contains(protected)
        except Exception:
            # If a toolkit exposes an explicit password role but a broken state
            # set, the role check above has already kept us from reading it.
            return False

    def close(self) -> None:
        for listener, event_name in (
            (self._selection_listener, "object:text-selection-changed"),
            (self._focus_listener, "object:state-changed:focused"),
        ):
            if listener is None:
                continue
            try:
                listener.deregister(event_name)
            except Exception:
                pass
        self._selection_listener = None
        self._focus_listener = None
        self._selection_callback = None

    @staticmethod
    def _editable(node):
        try:
            return node.get_editable_text_iface()
        except Exception:
            return None

    def _application_name(self, node):
        fallback = ""
        current = node
        for _ in range(12):
            try:
                fallback = fallback or str(current.get_name() or "")
                raw_role = current.get_role()
                if raw_role == self.atspi.Role.APPLICATION or (
                    str(current.get_role_name() or "").casefold() == "application"
                ):
                    return str(current.get_name() or fallback)
                current = current.get_parent()
                if current is None:
                    break
            except Exception:
                break
        return fallback

    @staticmethod
    def _role_name(node):
        try:
            role = node.get_role()
            stable = str(getattr(role, "value_nick", "")).replace("-", " ")
            localized = str(node.get_role_name() or "")
            return " ".join(dict.fromkeys(filter(None, (stable, localized))))
        except Exception:
            return ""

    def replace_selection(self, context: SelectionContext, replacement: str) -> bool:
        if context.backend != "atspi" or context.native_handle is None:
            return False
        if context.selection_start is None or context.selection_end is None:
            return False
        editable = self._editable(context.native_handle)
        if editable is None:
            return False
        try:
            editable.delete_text(context.selection_start, context.selection_end)
            editable.insert_text(context.selection_start, replacement, len(replacement))
            return True
        except Exception:
            return False
