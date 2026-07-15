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

    __slots__ = (
        "_dictionaries",
        "_factory",
        "_ignored",
        "_personal",
        "max_suggestions",
    )

    def __init__(
        self,
        dictionary_factory: Callable[[str], Any] | None = None,
        *,
        max_suggestions: int = 3,
        ignored: Iterable[str] = (),
        personal: Iterable[str] = (),
    ):
        self._factory = dictionary_factory or self._default_factory
        self._dictionaries: dict[str, Any | None] = {}
        self._ignored = {str(word).casefold() for word in ignored}
        self._personal = {str(word).casefold() for word in personal}
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
        if not word or word.casefold() in self._ignored:
            return None
        if word.casefold() in self._personal:
            return SpellingResult(word, "personal", False)
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

    def ignore(self, word: str) -> None:
        if eligible := self.eligible_word(word):
            self._ignored.add(eligible.casefold())

    def add(self, word: str, language: str) -> bool:
        eligible = self.eligible_word(word)
        if not eligible:
            return False
        self._personal.add(eligible.casefold())
        if language not in self._dictionaries:
            try:
                self._dictionaries[language] = self._factory(language)
            except (ImportError, OSError, RuntimeError):
                return True
        dictionary = self._dictionaries.get(language)
        try:
            dictionary.add(eligible)
            return True
        except (AttributeError, OSError, RuntimeError):
            return True

    @staticmethod
    def language_candidates(text: str, locale: str = "") -> tuple[str, ...]:
        """Return a cheap deterministic dictionary order without loading NLP."""
        candidates = []
        normalized = locale.replace("-", "_")
        if normalized:
            candidates.append(normalized)
        lowered = f" {text.casefold()} "
        spanish_markers = (" el ", " la ", " de ", " que ", "ción", "ñ")
        english_markers = (" the ", " and ", " of ", "ing", "tion")
        candidates.extend(("es_CL", "es_ES") if any(value in lowered for value in spanish_markers) else ())
        candidates.extend(("en_US", "en_GB") if any(value in lowered for value in english_markers) else ())
        candidates.extend(("es_CL", "es_ES", "en_US"))
        return tuple(dict.fromkeys(value for value in candidates if value))
