"""Lazy, optional local spelling provider with no resident dependency."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SpellingResult:
    word: str
    language: str
    misspelled: bool
    suggestions: tuple[str, ...] = ()


class SpellingService:
    """Load system dictionaries only when a spelling action requests them."""

    __slots__ = ("_dictionaries", "_factory", "max_suggestions")

    def __init__(
        self,
        dictionary_factory: Callable[[str], Any] | None = None,
        *,
        max_suggestions: int = 3,
    ):
        self._factory = dictionary_factory or self._default_factory
        self._dictionaries: dict[str, Any | None] = {}
        self.max_suggestions = max(1, min(8, int(max_suggestions)))

    @staticmethod
    def eligible_word(text: str) -> str:
        word = str(text or "").strip()
        if not 1 < len(word) <= 64:
            return ""
        if not all(char.isalpha() or char in "-'’" for char in word):
            return ""
        return word

    @staticmethod
    def _default_factory(language: str):
        import enchant

        return enchant.Dict(language)

    def suggest(
        self,
        text: str,
        languages: Iterable[str],
    ) -> SpellingResult | None:
        word = self.eligible_word(text)
        if not word:
            return None
        for language in languages:
            language = str(language).strip()
            if not language:
                continue
            if language not in self._dictionaries:
                try:
                    self._dictionaries[language] = self._factory(language)
                except (ImportError, OSError, RuntimeError):
                    self._dictionaries[language] = None
            dictionary = self._dictionaries[language]
            if dictionary is None:
                continue
            try:
                if dictionary.check(word):
                    return SpellingResult(word, language, False)
                suggestions = tuple(
                    dict.fromkeys(
                        value.strip()
                        for value in dictionary.suggest(word)
                        if isinstance(value, str) and value.strip()
                    )
                )[: self.max_suggestions]
            except (OSError, RuntimeError):
                self._dictionaries[language] = None
                continue
            if suggestions:
                return SpellingResult(word, language, True, suggestions)
        return None
