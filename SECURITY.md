# Security policy

## Supported versions

Security fixes are provided for the latest published release candidate or stable
release. Development snapshots and older prereleases are not supported.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose selected text,
clipboard data, command execution, local files or credentials.

Use GitHub's private vulnerability reporting for this repository. Include:

- the affected TextPik version and Linux distribution;
- desktop environment and whether the session uses Wayland or X11;
- reproduction steps and expected impact;
- logs with selected text, paths, tokens and personal data removed.

Reports should receive an initial acknowledgement within seven days. A fix or a
status update will be provided before public disclosure whenever the report is
confirmed.

## Security boundaries

TextPik treats accessibility data, selected text and clipboard contents as
sensitive. Extensions and external commands are user-installed code and must be
reviewed before permission is granted. Terminal actions always require explicit
confirmation by default.
