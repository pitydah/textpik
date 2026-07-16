"""Declarative, shell-free text automations with transactional previews."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .actions import TRANSFORMS, transform_text
from .models import SelectionContext

MAX_STEPS = 16
MAX_OUTPUT = 1_000_000


@dataclass(frozen=True, slots=True)
class AutomationPreview:
    before: str
    after: str
    steps: tuple[str, ...]


def automation_matches(flow: dict, context: SelectionContext, text_types) -> bool:
    conditions = flow.get("conditions", {})
    application = str(conditions.get("application", "")).casefold()
    if application and application not in context.application.casefold():
        return False
    if conditions.get("editable") is not None and bool(conditions["editable"]) != context.editable:
        return False
    minimum = max(0, int(conditions.get("min_length", 0)))
    maximum = min(100_000, int(conditions.get("max_length", 100_000)))
    if not minimum <= len(context.text) <= maximum:
        return False
    required_types = set(conditions.get("text_types", []))
    if required_types and not required_types.intersection(text_types):
        return False
    pattern = str(conditions.get("regex", ""))
    if pattern:
        if len(pattern) > 256:
            return False
        if re.search(r"\\[1-9]|\(\?[=!<]|\([^)]*[*+][^)]*\)[*+]", pattern):
            return False
        try:
            if re.search(pattern, context.text[:20_000]) is None:
                return False
        except re.error:
            return False
    return True


def preview_automation(flow: dict, text: str) -> AutomationPreview:
    current = text
    executed = []
    steps = flow.get("steps", [])
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise ValueError("invalid automation steps")
    for raw in steps:
        if not isinstance(raw, dict):
            raise ValueError("invalid automation step")
        operation = str(raw.get("operation", ""))
        if operation in TRANSFORMS:
            current = transform_text(operation, current)
        elif operation == "replace":
            source, target = str(raw.get("source", "")), str(raw.get("target", ""))
            if not source or len(source) > 256 or len(target) > 1000:
                raise ValueError("invalid replacement")
            current = current.replace(source, target)
        elif operation == "prefix":
            current = str(raw.get("value", ""))[:1000] + current
        elif operation == "suffix":
            current += str(raw.get("value", ""))[:1000]
        else:
            raise ValueError(f"unsupported automation operation: {operation}")
        if len(current) > MAX_OUTPUT:
            raise ValueError("automation output is too large")
        executed.append(operation)
    return AutomationPreview(text, current, tuple(executed))
