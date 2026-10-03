"""Small local insights that never require network access or optional imports."""

from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class InlineInsight:
    kind: str
    title: str
    value: str
    detail: str = ""


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_UNITS = {
    ("km", "mi"): 0.6213711922,
    ("mi", "km"): 1.609344,
    ("m", "ft"): 3.280839895,
    ("ft", "m"): 0.3048,
    ("cm", "in"): 0.3937007874,
    ("in", "cm"): 2.54,
    ("kg", "lb"): 2.204622622,
    ("lb", "kg"): 0.45359237,
    ("l", "gal"): 0.2641720524,
    ("gal", "l"): 3.785411784,
}


def safe_calculate(expression: str) -> float | int:
    """Evaluate bounded arithmetic without names, calls or Python execution."""
    expression = expression.strip().replace("^", "**")
    if not expression or len(expression) > 160:
        raise ValueError("invalid expression")
    tree = ast.parse(expression, mode="eval")
    seen = 0

    def evaluate(node):
        nonlocal seen
        seen += 1
        if seen > 48:
            raise ValueError("expression too complex")
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("exponent too large")
            value = _BINARY[type(node.op)](left, right)
            if abs(value) > 1e100:
                raise ValueError("result too large")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](evaluate(node.operand))
        raise ValueError("unsupported expression")

    value = evaluate(tree)
    return int(value) if isinstance(value, float) and value.is_integer() else value


def convert_units(text: str) -> InlineInsight | None:
    match = re.fullmatch(
        r"\s*(-?\d+(?:[.,]\d+)?)\s*([A-Za-z°]+)\s+(?:a|to|en)\s+([A-Za-z°]+)\s*",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    source, target = match.group(2).casefold(), match.group(3).casefold()
    if source in {"c", "°c"} and target in {"f", "°f"}:
        result = amount * 9 / 5 + 32
    elif source in {"f", "°f"} and target in {"c", "°c"}:
        result = (amount - 32) * 5 / 9
    else:
        factor = _UNITS.get((source, target))
        if factor is None:
            return None
        result = amount * factor
    formatted = f"{result:.6f}".rstrip("0").rstrip(".")
    return InlineInsight("conversion", "Conversión", f"{formatted} {target}")


def timezone_insight(text: str, *, now: datetime | None = None) -> InlineInsight | None:
    match = re.fullmatch(r"\s*(?:hora\s+en|time\s+in)\s+([\w+\-/]+)\s*", text, re.I)
    if not match:
        return None
    zone_name = match.group(1)
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError:
        return None
    current = (now or datetime.now(tz=zone)).astimezone(zone)
    return InlineInsight("timezone", f"Hora en {zone_name}", current.strftime("%H:%M · %Y-%m-%d"))


def text_statistics(text: str) -> InlineInsight:
    word_pattern = re.compile(
        r"(?:\d+(?:[.,]\d+)*|[^\W\d_]+(?:[’'\-][^\W\d_]+)*)",
        re.UNICODE,
    )
    words = len(word_pattern.findall(text))
    characters = len(text)
    characters_without_spaces = sum(not char.isspace() for char in text)
    lines = len(text.splitlines()) if text else 0
    paragraphs = len(
        [value for value in re.split(r"(?:\r?\n\s*){2,}", text.strip()) if value]
    ) if text.strip() else 0
    sentence_marks = len(
        re.findall(r"[.!?…]+(?=(?:[\"'”’»\)\]]*)?(?:\s|$))", text)
    )
    sentences = max(1, sentence_marks) if words else 0
    reading_seconds = math.ceil((words / 200) * 60) if words else 0
    reading = (
        "menos de 1 min de lectura"
        if 0 < reading_seconds < 60
        else f"{max(1, math.ceil(reading_seconds / 60))} min de lectura"
        if reading_seconds
        else "0 min de lectura"
    )
    return InlineInsight(
        "statistics",
        "Estadísticas del texto",
        f"{words} palabras · {characters} caracteres",
        (
            f"{characters_without_spaces} sin espacios · {sentences} oraciones · "
            f"{paragraphs} párrafos · {lines} líneas · {reading}"
        ),
    )


def local_insight(text: str) -> InlineInsight | None:
    """Resolve a useful local result, preferring explicit conversions."""
    if converted := convert_units(text):
        return converted
    if timezone := timezone_insight(text):
        return timezone
    candidate = text.strip()
    if re.fullmatch(r"[\d\s,.+\-*/^()%]+", candidate) and any(c.isdigit() for c in candidate):
        try:
            result = safe_calculate(candidate.replace(",", "."))
        except (SyntaxError, ValueError, ArithmeticError):
            return None
        return InlineInsight("calculation", "Resultado", str(result))
    return None
