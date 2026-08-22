"""HTML-to-text stage with full offset evidence.

A tolerant :class:`html.parser.HTMLParser` subclass walks the (already
newline- and NFC-normalized) text once and collects *operations* in snapshot
coordinates: tag strips (with paragraph/line boundaries), entity/charref
decoding, and removal of invisible content (``script``/``style``/``head``/
``title``/``noscript``/``template`` bodies) and comments/declarations.

Operations are applied to the pipeline state right-to-left so snapshot
positions stay valid; the edit records are then restored to document order.
No script is executed and no external resource is fetched — the parser only
ever sees the string it was fed.
"""

from __future__ import annotations

import html as html_module
import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING

from intelligence_engine.normalize.model import Operation, Reason

if TYPE_CHECKING:
    from intelligence_engine.normalize.text_pipeline import Working

_ENTITY_REF_RE = re.compile(r"&[a-zA-Z][-.a-zA-Z0-9]*;?")
_CHAR_REF_RE = re.compile(r"&#(?:[0-9]+|[xX][0-9a-fA-F]+);?")

_INVISIBLE_TAGS = frozenset({"script", "style", "noscript", "template", "title", "head"})
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "li",
        "tr",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "nav",
        "aside",
        "pre",
        "hr",
        "dl",
        "dt",
        "dd",
        "form",
        "fieldset",
        "address",
        "figure",
        "figcaption",
        "caption",
        "colgroup",
        "col",
    }
)


def _markup_end(snapshot: str, start: int) -> int:
    """End (exclusive) of the markup construct starting at ``start``.

    Scans for the closing ``>`` while skipping over quoted attribute values,
    so ``<a title="x>y">`` terminates at the real tag end. Comments and
    declarations terminate at their natural end when it comes first.
    """
    index = start
    quote: str | None = None
    length = len(snapshot)
    while index < length:
        character = snapshot[index]
        if quote is not None:
            if character == quote:
                quote = None
        elif character in ("'", '"'):
            quote = character
        elif character == ">":
            return index + 1
        index += 1
    return length


class _Extractor(HTMLParser):
    """Collects HTML strip/decode operations in snapshot coordinates."""

    def __init__(self, snapshot: str) -> None:
        super().__init__(convert_charrefs=False)
        self.snapshot = snapshot
        self.operations: list[tuple[int, int, str, Operation, Reason]] = []
        self._line_starts = [0]
        for position, character in enumerate(snapshot):
            if character == "\n":
                self._line_starts.append(position + 1)
        self._invisible: list[str] = []

    def _position(self) -> int:
        line, column = self.getpos()
        line_index = line - 1
        if line_index < 0 or line_index >= len(self._line_starts):
            return 0
        return self._line_starts[line_index] + column

    def _emit(
        self, start: int, end: int, replacement: str, operation: Operation, reason: Reason
    ) -> None:
        if end > start:
            self.operations.append((start, end, replacement, operation, reason))

    def _strip_tag(self, tag: str, start: int) -> None:
        end = _markup_end(self.snapshot, start)
        if tag == "br":
            replacement = "\n"
            reason = Reason.HTML_LINE_BREAK
        elif tag in _BLOCK_TAGS:
            replacement = "\n\n"
            reason = Reason.HTML_TAG_REMOVED
        else:
            replacement = ""
            reason = Reason.HTML_TAG_REMOVED
        self._emit(start, end, replacement, Operation.HTML_TAG_STRIP, reason)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        position = self._position()
        if tag in _INVISIBLE_TAGS:
            self._invisible.append(tag)
        self._strip_tag(tag, position)

    def handle_endtag(self, tag: str) -> None:
        position = self._position()
        if self._invisible and self._invisible[-1] == tag:
            self._invisible.pop()
        self._strip_tag(tag, position)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        position = self._position()
        self._strip_tag(tag, position)

    def handle_data(self, data: str) -> None:
        position = self._position()
        if self._invisible and data:
            self._emit(
                position,
                position + len(data),
                "",
                Operation.HTML_INVISIBLE_STRIP,
                Reason.HTML_INVISIBLE_CONTENT_REMOVED,
            )

    def _handle_ref(self, raw_pattern: re.Pattern[str]) -> None:
        position = self._position()
        if position >= len(self.snapshot) or self.snapshot[position] != "&":
            return
        match = raw_pattern.match(self.snapshot, position)
        if match is None:
            return
        raw = match.group(0)
        decoded = html_module.unescape(raw)
        if decoded == raw:
            return
        replacement = "" if self._invisible else decoded
        self._emit(
            position,
            position + len(raw),
            replacement,
            Operation.HTML_ENTITY,
            Reason.HTML_ENTITY_DECODED,
        )

    def handle_entityref(self, name: str) -> None:
        self._handle_ref(_ENTITY_REF_RE)

    def handle_charref(self, name: str) -> None:
        self._handle_ref(_CHAR_REF_RE)

    def handle_comment(self, data: str) -> None:
        position = self._position()
        end = self.snapshot.find("-->", position)
        end = end + 3 if end != -1 else _markup_end(self.snapshot, position)
        self._emit(position, end, "", Operation.HTML_TAG_STRIP, Reason.HTML_COMMENT_REMOVED)

    def handle_decl(self, decl: str) -> None:
        position = self._position()
        end = _markup_end(self.snapshot, position)
        self._emit(position, end, "", Operation.HTML_TAG_STRIP, Reason.HTML_COMMENT_REMOVED)

    def handle_pi(self, data: str) -> None:
        position = self._position()
        end = _markup_end(self.snapshot, position)
        self._emit(position, end, "", Operation.HTML_TAG_STRIP, Reason.HTML_COMMENT_REMOVED)

    def unknown_decl(self, data: str) -> None:
        position = self._position()
        end = self.snapshot.find("]]>", position)
        end = end + 3 if end != -1 else _markup_end(self.snapshot, position)
        self._emit(position, end, "", Operation.HTML_TAG_STRIP, Reason.HTML_COMMENT_REMOVED)


def strip_html_stage(state: Working) -> None:
    """Apply HTML stripping to the pipeline state, preserving offsets."""
    snapshot = "".join(state.chars)
    extractor = _Extractor(snapshot)
    extractor.feed(snapshot)
    extractor.close()
    # Apply right-to-left so snapshot coordinates stay valid for untouched
    # prefixes; afterwards restore document order for the stage's edits.
    edit_count_before = len(state.edits)
    for start, end, replacement, operation, reason in reversed(extractor.operations):
        state.replace(start, end, replacement, operation, reason)
    state.edits[edit_count_before:] = list(reversed(state.edits[edit_count_before:]))
