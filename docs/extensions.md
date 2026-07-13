# Local action extensions

TextPik intentionally has no remote extension store and does not import Python
code from extensions. An extension is one declarative `manifest.json` placed at:

```text
~/.local/share/textpik/extensions/<extension-id>/manifest.json
```

Example:

```json
{
  "schema_version": 1,
  "action": {
    "id": "search-example",
    "name": "Search Example",
    "icon": "search-google.svg",
    "cmd": "xdg-open 'https://example.com/search?q={url}'",
    "operation": "open-url",
    "result": "open",
    "context": ["text"],
    "permissions": ["network", "process"],
    "category": "Search"
  }
}
```

The schema is in `docs/action-manifest.schema.json`. TextPik rejects unknown
permissions, unsupported schema versions and external commands that omit the
`process` permission. Each requested permission is confirmed on first use and
stored locally in `~/.config/textpik/permissions.json`. Commands are parsed into
an argument vector; they are never passed through a shell.

Built-in transformations (`uppercase`, `lowercase`, `capitalize` and
`remove-breaks`) may request `replace-selection`. TextPik uses AT-SPI when the
target is editable and otherwise copies the result.
