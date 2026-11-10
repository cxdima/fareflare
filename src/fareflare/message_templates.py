"""Logic-less message templates for account-authored text.

A template is data, never code. Rendering substitutes values from a fixed
vocabulary; it cannot evaluate expressions, read attributes or call functions,
so an account-authored template cannot become an injection vector.

Syntax::

    {name}      a placeholder from the template's vocabulary
    [ ... ]     an optional group, kept only when every placeholder inside has a value
    **bold**    emphasis; also __italic__ and `monospace`
    \\x          the literal character x, for example \\[ or \\{

A line whose placeholders and groups all render empty is removed and repeated
blank lines collapse, so one template serves itineraries with differing details.
Groups and emphasis must close on the line where they open.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from html import escape

MAX_TEMPLATE_LENGTH = 800
MAX_TEMPLATE_LINES = 20
MAX_PLACEHOLDERS = 40

_NAME = re.compile(r"[a-z][a-z_]{0,31}\Z")
# Direction overrides and isolates can visually reorder a message around a price.
_DIRECTIONAL = frozenset("‎‏‪‫‬‭‮⁦⁧⁨⁩")
_EMPHASIS = (("**", "bold"), ("__", "italic"), ("`", "code"))
_LABELS = {"bold": "**bold**", "italic": "__italic__", "code": "`monospace`"}


class TemplateError(ValueError):
    """A template is malformed or uses a placeholder outside its vocabulary."""


@dataclass(frozen=True)
class Run:
    """Text sharing one style: the unit both the plain and the HTML output are built from."""

    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    href: str | None = None


Value = str | tuple[Run, ...]


@dataclass(frozen=True)
class Rendered:
    text: str
    html: str
    # Placeholders that produced visible output, so callers can avoid repeating them.
    used: frozenset[str]


@dataclass(frozen=True)
class _Text:
    value: str


@dataclass(frozen=True)
class _Field:
    name: str


@dataclass(frozen=True)
class _Group:
    parts: tuple[_Node, ...]


@dataclass(frozen=True)
class _Styled:
    style: str
    parts: tuple[_Node, ...]


_Node = _Text | _Field | _Group | _Styled


class _LineParser:
    """Recursive descent over one line; nesting errors are reported, never repaired."""

    def __init__(self, line: str, vocabulary: frozenset[str]):
        self.line, self.vocabulary = line, vocabulary
        self.position = 0
        self.placeholders = 0

    def parse(self) -> tuple[_Node, ...]:
        return self._sequence(closing=None, styles=(), in_group=False)

    def _field(self) -> _Field:
        end = self.line.find("}", self.position)
        if end < 0:
            raise TemplateError("A placeholder is missing its closing }")
        name = self.line[self.position + 1 : end]
        if not _NAME.fullmatch(name) or name not in self.vocabulary:
            raise TemplateError(f"Unknown placeholder {{{name}}}")
        self.position = end + 1
        self.placeholders += 1
        return _Field(name)

    def _sequence(
        self, closing: str | None, styles: tuple[str, ...], in_group: bool
    ) -> tuple[_Node, ...]:
        nodes: list[_Node] = []
        literal: list[str] = []
        line = self.line

        def flush() -> None:
            if literal:
                nodes.append(_Text("".join(literal)))
                literal.clear()

        while self.position < len(line):
            if closing is not None and line.startswith(closing, self.position):
                self.position += len(closing)
                flush()
                return tuple(nodes)
            char = line[self.position]
            if char == "\\":
                if self.position + 1 >= len(line):
                    raise TemplateError("A backslash must be followed by the character it escapes")
                literal.append(line[self.position + 1])
                self.position += 2
            elif char == "{":
                flush()
                nodes.append(self._field())
            elif closing == "`":
                # Inside monospace only placeholders and escapes are special.
                literal.append(char)
                self.position += 1
            elif char == "}":
                raise TemplateError("Unmatched }. Write \\} for a literal brace")
            elif char == "[":
                if in_group:
                    raise TemplateError("Optional groups cannot be nested")
                self.position += 1
                flush()
                before = self.placeholders
                parts = self._sequence(closing="]", styles=styles, in_group=True)
                if self.placeholders == before:
                    raise TemplateError(
                        "An optional group needs a placeholder. Write \\[ for a literal bracket"
                    )
                nodes.append(_Group(parts))
            elif char == "]":
                if in_group:
                    raise TemplateError("Close emphasis before the end of its optional group")
                raise TemplateError("Unmatched ]. Write \\] for a literal bracket")
            else:
                marker = next((m for m in _EMPHASIS if line.startswith(m[0], self.position)), None)
                if marker is None:
                    literal.append(char)
                    self.position += 1
                    continue
                token, style = marker
                if style in styles:
                    raise TemplateError("Emphasis markers overlap; close the inner one first")
                self.position += len(token)
                flush()
                nodes.append(
                    _Styled(style, self._sequence(token, (*styles, style), in_group=in_group))
                )
        if closing == "]":
            raise TemplateError("An optional group is missing its closing ]")
        if closing is not None:
            raise TemplateError(f"Close {_LABELS[styles[-1]]} on the line where it starts")
        flush()
        return tuple(nodes)


@lru_cache(maxsize=512)
def parse_template(template: str, vocabulary: frozenset[str]) -> tuple[tuple[_Node, ...], ...]:
    """Validate and parse a template; the result is immutable and safely cached."""
    if not isinstance(template, str):
        raise TemplateError("A template must be text")
    if len(template) > MAX_TEMPLATE_LENGTH:
        raise TemplateError(f"A template can contain at most {MAX_TEMPLATE_LENGTH} characters")
    if any(
        (ord(char) < 32 and char != "\n") or ord(char) == 127 or char in _DIRECTIONAL
        for char in template
    ):
        raise TemplateError("Templates cannot contain control or text-direction characters")
    lines = template.split("\n")
    if len(lines) > MAX_TEMPLATE_LINES:
        raise TemplateError(f"A template can contain at most {MAX_TEMPLATE_LINES} lines")
    parsed, placeholders = [], 0
    for line in lines:
        parser = _LineParser(line, vocabulary)
        parsed.append(parser.parse())
        placeholders += parser.placeholders
    if placeholders > MAX_PLACEHOLDERS:
        raise TemplateError(f"A template can contain at most {MAX_PLACEHOLDERS} placeholders")
    return tuple(parsed)


def normalize_template(template: str) -> str:
    """Canonical stored form: Unix newlines, no trailing spaces or outer blank lines."""
    if not isinstance(template, str):
        raise TemplateError("A template must be text")
    lines = [line.rstrip(" ") for line in template.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _is_empty(value: Value | None) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return not any(run.text.strip() for run in value)


def _has_empty_field(nodes: tuple[_Node, ...], values: Mapping[str, Value]) -> bool:
    for node in nodes:
        if isinstance(node, _Field) and _is_empty(values.get(node.name)):
            return True
        if isinstance(node, _Group | _Styled) and _has_empty_field(node.parts, values):
            return True
    return False


def _is_dynamic(nodes: tuple[_Node, ...]) -> bool:
    return any(
        isinstance(node, _Field | _Group) or (isinstance(node, _Styled) and _is_dynamic(node.parts))
        for node in nodes
    )


def _expand(
    nodes: tuple[_Node, ...],
    values: Mapping[str, Value],
    used: set[str],
    *,
    bold: bool = False,
    italic: bool = False,
    code: bool = False,
) -> list[Run]:
    runs: list[Run] = []
    for node in nodes:
        if isinstance(node, _Text):
            runs.append(Run(node.value, bold, italic, code))
        elif isinstance(node, _Field):
            value = values.get(node.name)
            if _is_empty(value):
                continue
            used.add(node.name)
            if isinstance(value, str):
                runs.append(Run(value, bold, italic, code))
            else:
                assert value is not None
                runs.extend(
                    Run(
                        run.text, run.bold or bold, run.italic or italic, run.code or code, run.href
                    )
                    for run in value
                )
        elif isinstance(node, _Group):
            if not _has_empty_field(node.parts, values):
                runs.extend(_expand(node.parts, values, used, bold=bold, italic=italic, code=code))
        else:
            runs.extend(
                _expand(
                    node.parts,
                    values,
                    used,
                    bold=bold or node.style == "bold",
                    italic=italic or node.style == "italic",
                    code=code or node.style == "code",
                )
            )
    return runs


def _markup(run: Run) -> str:
    text = escape(run.text)
    if run.href:
        # Telegram links may carry bold or italic, but never monospace.
        text = f'<a href="{escape(run.href, quote=True)}">{text}</a>'
    elif run.code:
        # Monospace cannot contain, or be contained in, other emphasis.
        return f"<code>{text}</code>"
    if run.italic:
        text = f"<i>{text}</i>"
    if run.bold:
        text = f"<b>{text}</b>"
    return text


def _lines(runs: list[Run]) -> list[list[Run]]:
    """Split on newlines carried by multi-line values, merging equal adjacent styles."""
    lines: list[list[Run]] = [[]]
    for run in runs:
        for index, piece in enumerate(run.text.split("\n")):
            if index:
                lines.append([])
            if not piece:
                continue
            current = lines[-1]
            part = Run(piece, run.bold, run.italic, run.code, run.href)
            if (
                current
                and (current[-1].bold, current[-1].italic, current[-1].code)
                == (
                    part.bold,
                    part.italic,
                    part.code,
                )
                and current[-1].href is None
                and part.href is None
            ):
                current[-1] = Run(current[-1].text + piece, part.bold, part.italic, part.code)
            else:
                current.append(part)
    return lines


def _trim_trailing(line: list[Run]) -> list[Run]:
    trimmed = list(line)
    while trimmed:
        text = trimmed[-1].text.rstrip()
        if text:
            last = trimmed[-1]
            trimmed[-1] = Run(text, last.bold, last.italic, last.code, last.href)
            break
        trimmed.pop()
    return trimmed


def render(template: str, values: Mapping[str, Value], vocabulary: frozenset[str]) -> Rendered:
    """Render a template. Names in the vocabulary without a value render empty."""
    used: set[str] = set()
    output: list[list[Run]] = []
    for nodes in parse_template(template, vocabulary):
        runs = _expand(nodes, values, used)
        if _is_dynamic(nodes) and not "".join(run.text for run in runs).strip():
            continue  # Every placeholder on this line was empty.
        output.extend(_trim_trailing(line) for line in _lines(runs))
    collapsed: list[list[Run]] = []
    for line in output:
        if not line and (not collapsed or not collapsed[-1]):
            continue  # Leading blank line, or a repeat of the previous blank line.
        collapsed.append(line)
    while collapsed and not collapsed[-1]:
        collapsed.pop()
    return Rendered(
        "\n".join("".join(run.text for run in line) for line in collapsed),
        "\n".join("".join(_markup(run) for run in line) for line in collapsed),
        frozenset(used),
    )
