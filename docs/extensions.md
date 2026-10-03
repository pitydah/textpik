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

Discovery is bounded to 64 manifests of at most 64 KiB each. Symlinks escaping
the extension root, duplicate action IDs and unreadable manifests are rejected.
The diagnostics page reports the rejected count, and the action editor tooltip
shows the owning extension and requested permissions before execution.

Built-in transformations (`uppercase`, `lowercase`, `capitalize` and
`remove-breaks`) may request `replace-selection`. TextPik uses AT-SPI when the
target is editable and otherwise copies the result.

## WASI schema v2

Advanced extensions may ship one WebAssembly module executed by the optional
`wasmtime` runtime. TextPik verifies the module SHA-256 before exposing the
action, confines it to the extension directory, grants no preopened directory
or network socket and terminates it after the manifest timeout.

```json
{
  "schema_version": 2,
  "runtime": "wasi",
  "module": "transform.wasm",
  "sha256": "<sha256-of-transform.wasm>",
  "timeout_ms": 2000,
  "action": {
    "id": "safe-transform",
    "name": "Safe transform",
    "icon": "capitalize.svg",
    "permissions": []
  }
}
```

Selected text is passed through standard input and bounded output is read from
standard output. TextPik requests the `process` permission before first use.
