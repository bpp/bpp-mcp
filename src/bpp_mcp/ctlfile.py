"""Line-level access to `keyword = value` lines in a BPP control file.

Generic text handling only: finding, reading and replacing a keyword's line.
Which keywords exist and which values are valid is bpp-lint's and bpp-docs'
business, not this module's.
"""
from __future__ import annotations

import re

_COMMENT_TAIL = re.compile(r"\s*[*#].*$")
# A comment line, or the start of another `keyword = value` line.
_OTHER_LINE = re.compile(r"[ \t]*(?:[*#]|[A-Za-z][\w&-]*[ \t]*=)")


def _line_re(key: str) -> re.Pattern:
    return re.compile(rf"^(?P<indent>[ \t]*)(?P<key>{re.escape(key)})(?P<eq>[ \t]*=[ \t]*)(?P<val>.*)$",
                      re.I | re.M)


def _placeholder_re(key: str) -> re.Pattern:
    return re.compile(rf"^[ \t]*[#*][ \t]*{re.escape(key)}[ \t]*=.*$", re.I | re.M)


def get(text: str, key: str) -> str | None:
    """Value of the first `key = value` line (comments stripped), or None."""
    m = _line_re(key).search(text)
    return _COMMENT_TAIL.sub("", m.group("val")).strip() if m else None


def continuation_lines(text: str, key: str) -> int:
    """Number of lines the value of ``key`` continues over after its own line.

    A continuation is a line that is not blank, not a comment and not a
    `keyword = value` line (e.g. the 2nd and 3rd lines of `species&tree`).
    """
    m = _line_re(key).search(text)
    if not m:
        return 0
    n = 0
    for line in text[m.end():].split("\n")[1:]:
        if not line.strip() or _OTHER_LINE.match(line):
            break
        n += 1
    return n


def set_value(text: str, key: str, value: str) -> str:
    """Set ``key`` to ``value`` on a single line.

    Replaces the first active `key = ...` line, keeping its indentation and
    any trailing comment; else replaces a commented-out placeholder such as
    `# key = ???`; else appends.
    """
    if "\n" in value:
        raise ValueError("multi-line values are not supported")
    m = _line_re(key).search(text)
    if m:
        tail = _COMMENT_TAIL.search(m.group("val"))
        end = m.start("val") + tail.start() if tail else m.end("val")
        gap = " " if tail and not tail.group()[0].isspace() else ""
        return text[:m.start("val")] + value + gap + text[end:]
    m = _placeholder_re(key).search(text)
    if m:
        return text[:m.start()] + f"{key} = {value}" + text[m.end():]
    if text and not text.endswith("\n"):
        text += "\n"
    return text + f"{key} = {value}\n"


def species(text: str) -> list[str] | None:
    """Species names from the first line of the `species&tree` block."""
    v = get(text, "species&tree")
    if not v:
        return None
    toks = v.split()
    if not toks or not toks[0].isdigit():
        return None
    return toks[1:1 + int(toks[0])]
