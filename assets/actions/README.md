# TextPik action icon system

All action masters use a square SVG canvas and are rendered as a single
monochrome layer. TextPik recolors that layer at runtime to maintain contrast.

## Optical rules

- Canvas: `24 × 24` viewBox (brand masters may retain an equivalent square
  source viewBox).
- Utility strokes: rounded caps and joins, normally `1.8–2.2` units.
- Safe area: approximately 2 units on each edge.
- Filled brand marks are optically reduced by the popup renderer at 18 px.
- No embedded background, shadow, CSS dependency, font or external resource.

Utility pictograms are original TextPik artwork. Google, Google Maps, YouTube,
ChatGPT/OpenAI, DeepSeek, DuckDuckGo and Ollama marks identify the destination
of their respective actions and remain trademarks of their owners. Their use
does not imply affiliation or endorsement.

The `-black` and `-white` files are retained for compatibility with older
TextPik installations. Current versions use the unsuffixed master and apply
the foreground color dynamically.
