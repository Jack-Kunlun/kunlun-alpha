"""Deterministic text normalization pipeline with reversible edit tracking.

Stage order (fixed by policy ``normalize-v1``):

1. UTF-8 BOM prefix removal
2. mojibake recovery (whole-text latin-1/UTF-8 round-trip, only when safe)
3. CR/CRLF newline unification to LF
4. Unicode NFC composition (per combining/Hangul cluster)
5. HTML stripping (optional, ``strip_html=True``)
6. control character removal (Cc/Cf except ``\\t``, ``\\n`` and ZWJ)
7. whitespace collapse and trim
8. truncation to the policy limit (last)

Every stage operates on the shared working state (current characters plus,
per character, the original span it came from) and records a
:class:`~intelligence_engine.normalize.model.EditRecord` for every change.
The final :class:`~intelligence_engine.normalize.model.NormalizedText`
exposes the edit history and a run-based mapping from normalized positions
back to original offsets.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from intelligence_engine.normalize.html import strip_html_stage
from intelligence_engine.normalize.model import (
    NORMALIZATION_VERSION,
    EditRecord,
    NormalizationAuditError,
    NormalizedText,
    Operation,
    Reason,
    SpanRun,
    UnrecoverableTextError,
    audit_normalization,
)

_BOM = "\ufeff"
_ZWJ = "\u200d"


@dataclass
class _PendingEdit:
    """An edit recorded during a stage, before final coordinate resolution."""

    operation: Operation
    original_start: int
    original_end: int
    replacement: str
    reason: Reason


@dataclass
class Working:
    """Mutable pipeline state: current chars, their original spans and owners."""

    original: str
    chars: list[str] = field(default_factory=list)
    starts: list[int] = field(default_factory=list)
    ends: list[int] = field(default_factory=list)
    owner: list[int | None] = field(default_factory=list)
    edits: list[_PendingEdit] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.chars = list(self.original)
        self.starts = list(range(len(self.original)))
        self.ends = [i + 1 for i in range(len(self.original))]
        self.owner = [None] * len(self.original)

    def replace(
        self,
        start: int,
        end: int,
        replacement: str,
        operation: Operation,
        reason: Reason,
    ) -> None:
        """Replace the current characters ``[start, end)`` with ``replacement``.

        The replacement characters inherit the merged original span of the
        replaced characters and are marked as owned by this edit.
        """
        if start > end or end > len(self.chars):
            raise ValueError("invalid replacement range")
        original_start = self.starts[start]
        original_end = self.ends[end - 1] if end > start else original_start
        edit_id = len(self.edits)
        self.edits.append(
            _PendingEdit(operation, original_start, original_end, replacement, reason)
        )
        replacement_chars = list(replacement)
        self.chars[start:end] = replacement_chars
        self.starts[start:end] = [original_start] * len(replacement_chars)
        self.ends[start:end] = [original_end] * len(replacement_chars)
        self.owner[start:end] = [edit_id] * len(replacement_chars)

    def delete(self, start: int, end: int, operation: Operation, reason: Reason) -> None:
        self.replace(start, end, "", operation, reason)


def _remove_bom(state: Working) -> None:
    if state.chars and state.chars[0] == _BOM:
        state.delete(0, 1, Operation.REMOVE_BOM, Reason.UTF8_BOM_PREFIX)


def _recover_mojibake(state: Working) -> None:
    """Recover text that was UTF-8 bytes decoded as latin-1.

    The policy is deterministic and conservative: recovery applies only when
    the *entire current* text re-encodes losslessly to latin-1 and re-decodes
    as valid UTF-8 with a different result. Mixed or partially damaged text is
    left untouched (never silently rewritten); text containing U+FFFD is
    rejected before any stage runs.

    Crucially the recovery inherits the *current* per-character original spans
    (``state.starts``/``state.ends``) instead of assuming the text still starts
    at original offset 0. Latin-1 is one byte per current character, so
    recovered character ``c`` consumes a contiguous byte range that maps back
    to a contiguous run of current characters; ``c``'s original span is the
    merge of those current characters' original spans. This keeps offsets
    correct after BOM removal or any earlier transform.
    """
    text = "".join(state.chars)
    try:
        raw = text.encode("latin-1")
    except UnicodeEncodeError:
        return
    try:
        recovered = raw.decode("utf-8")
    except UnicodeDecodeError:
        return
    if recovered == text:
        return
    # Only recover when the result is *unambiguously* whole-field mojibake: the
    # recovered text must contain a character outside latin-1 (genuine multibyte
    # content mis-decoded as latin-1). Text whose recovery stays within latin-1
    # (e.g. ``prefix cafÃ©`` -> ``prefix café``) is ambiguous and must never be
    # silently rewritten; the service routes it to partial-mojibake review.
    if not any(ord(character) > 0xFF for character in recovered):
        return
    # byte offset i (0-based) corresponds to current character index i, because
    # every current character encodes to exactly one latin-1 byte.
    current_starts = state.starts
    current_ends = state.ends
    original_start = current_starts[0]
    original_end = current_ends[len(text) - 1]
    edit_id = len(state.edits)
    state.edits.append(
        _PendingEdit(
            Operation.MOJIBAKE_RECOVER,
            original_start,
            original_end,
            recovered,
            Reason.MOJIBAKE_LATIN1_UTF8_ROUNDTRIP,
        )
    )
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    byte_offset = 0
    for character in recovered:
        width = len(character.encode("utf-8"))
        first_index = byte_offset
        last_index = byte_offset + width - 1
        chars.append(character)
        starts.append(current_starts[first_index])
        ends.append(current_ends[last_index])
        byte_offset += width
    state.chars[:] = chars
    state.starts[:] = starts
    state.ends[:] = ends
    state.owner[:] = [edit_id] * len(chars)


def _normalize_newlines(state: Working) -> None:
    index = 0
    while index < len(state.chars):
        if state.chars[index] == "\r":
            if index + 1 < len(state.chars) and state.chars[index + 1] == "\n":
                state.replace(index, index + 2, "\n", Operation.NEWLINE_LF, Reason.CRLF_NEWLINE)
            else:
                state.replace(index, index + 1, "\n", Operation.NEWLINE_LF, Reason.CR_NEWLINE)
        index += 1


_L_MIN, _L_MAX = 0x1100, 0x115F
_V_MIN, _V_MAX = 0x1160, 0x11A7
_T_MIN, _T_MAX = 0x11A8, 0x11FF
_S_BASE, _S_LIMIT = 0xAC00, 0xAC00 + 11172


def _hangul_role(character: str) -> str | None:
    """Return the Hangul composition role of ``character`` (or ``None``)."""
    code = ord(character)
    if _L_MIN <= code <= _L_MAX:
        return "L"
    if _V_MIN <= code <= _V_MAX:
        return "V"
    if _T_MIN <= code <= _T_MAX:
        return "T"
    if _S_BASE <= code < _S_LIMIT and (code - _S_BASE) % 28 == 0:
        return "LV"
    return None


def _cluster_end(chars: list[str], start: int) -> int:
    """End of the combining/Hangul cluster beginning at ``start``.

    NFC composition only crosses character boundaries inside a base character
    plus its combining marks, or inside a Hangul jamo sequence, so per-cluster
    normalization equals whole-string NFC while keeping exact span mapping.
    """
    index = start + 1
    expects_v = _hangul_role(chars[start]) == "L"
    expects_t = _hangul_role(chars[start]) == "LV"
    while index < len(chars):
        character = chars[index]
        if unicodedata.combining(character) != 0:
            index += 1
            continue
        role = _hangul_role(character)
        if expects_v and role == "V":
            expects_v = False
            expects_t = True
            index += 1
            continue
        if expects_t and role == "T":
            index += 1
            continue
        break
    return index


def _normalize_nfc(state: Working) -> None:
    index = 0
    while index < len(state.chars):
        cluster_end = _cluster_end(state.chars, index)
        cluster = "".join(state.chars[index:cluster_end])
        composed = unicodedata.normalize("NFC", cluster)
        if composed != cluster:
            state.replace(
                index,
                cluster_end,
                composed,
                Operation.UNICODE_NFC,
                Reason.UNICODE_NFC_COMPOSITION,
            )
            index += len(composed)
        else:
            index = cluster_end


def _remove_control(state: Working) -> None:
    """Remove control/format characters, keeping tab, newline and ZWJ.

    ZWJ (U+200D) is kept so emoji ZWJ sequences survive normalization.
    """
    index = 0
    while index < len(state.chars):
        character = state.chars[index]
        if character in ("\t", "\n", _ZWJ):
            index += 1
            continue
        if unicodedata.category(character) in ("Cc", "Cf"):
            state.delete(
                index,
                index + 1,
                Operation.REMOVE_CONTROL,
                Reason.CONTROL_CHARACTER_REMOVED,
            )
        else:
            index += 1


def _collapse_whitespace(state: Working) -> None:
    """Collapse whitespace deterministically and idempotently.

    Rules: runs of spaces/tabs become one space, except they are removed at
    text boundaries, after a newline, or before a newline; runs of newlines
    become exactly one newline, or two (paragraph boundary) when longer;
    leading and trailing whitespace is removed. A final trailing trim pass
    handles cascades (e.g. removing the spaces after a newline can turn that
    newline into trailing whitespace).
    """
    _collapse_scan(state)
    _trim_trailing(state)


def _collapse_scan(state: Working) -> None:
    index = 0
    while index < len(state.chars):
        length = len(state.chars)
        character = state.chars[index]
        if character in (" ", "\t"):
            run_end = index
            while run_end < length and state.chars[run_end] in (" ", "\t"):
                run_end += 1
            previous = state.chars[index - 1] if index > 0 else None
            following = state.chars[run_end] if run_end < length else None
            if previous is None or previous == "\n" or following is None or following == "\n":
                state.delete(
                    index, run_end, Operation.WHITESPACE_COLLAPSE, Reason.WHITESPACE_TRIMMED
                )
                continue
            if run_end - index > 1:
                state.replace(
                    index,
                    run_end,
                    " ",
                    Operation.WHITESPACE_COLLAPSE,
                    Reason.WHITESPACE_COLLAPSED,
                )
            index += 1
        elif character == "\n":
            run_end = index
            while run_end < length and state.chars[run_end] == "\n":
                run_end += 1
            previous = state.chars[index - 1] if index > 0 else None
            if previous is None or run_end >= length:
                state.delete(
                    index, run_end, Operation.WHITESPACE_COLLAPSE, Reason.WHITESPACE_TRIMMED
                )
                continue
            if run_end - index >= 3:
                state.replace(
                    index,
                    run_end,
                    "\n\n",
                    Operation.WHITESPACE_COLLAPSE,
                    Reason.WHITESPACE_COLLAPSED,
                )
                index += 2
            else:
                index = run_end
        else:
            index += 1


def _trim_trailing(state: Working) -> None:
    while state.chars and state.chars[-1] in (" ", "\t", "\n"):
        end = len(state.chars)
        start = end
        while start > 0 and state.chars[start - 1] in (" ", "\t", "\n"):
            start -= 1
        state.delete(start, end, Operation.WHITESPACE_COLLAPSE, Reason.WHITESPACE_TRIMMED)


def _truncate(state: Working, limit: int) -> None:
    state.delete(limit, len(state.chars), Operation.TRUNCATE, Reason.CONTENT_TRUNCATED)


def _finalize(state: Working) -> NormalizedText:
    """Build the public result: runs, and edits with final normalized spans."""
    runs: list[list[int]] = []
    for position, (original_start, original_end) in enumerate(
        zip(state.starts, state.ends, strict=True)
    ):
        if runs and runs[-1][2] == original_start and runs[-1][3] == original_end:
            runs[-1][1] = position + 1
        else:
            runs.append([position, position + 1, original_start, original_end])
    span_runs = tuple(
        SpanRun(run[0], run[1], run[2], run[3], "".join(state.chars[run[0] : run[1]]))
        for run in runs
    )

    edits: list[EditRecord] = []
    total = len(state.chars)
    for edit_id, pending in enumerate(state.edits):
        positions = [position for position, owner in enumerate(state.owner) if owner == edit_id]
        if positions:
            # A later stage may split an edit's surviving characters (e.g. a
            # whole-text mojibake recovery whose newline is then CRLF-folded),
            # so the final span is the range enclosing the survivors.
            normalized_start = positions[0]
            normalized_end = positions[-1] + 1
        else:
            anchor = total
            for position in range(total):
                if state.ends[position] > pending.original_start:
                    anchor = position
                    break
            normalized_start = anchor
            normalized_end = anchor
        edits.append(
            EditRecord(
                operation=pending.operation,
                original_start=pending.original_start,
                original_end=pending.original_end,
                normalized_start=normalized_start,
                normalized_end=normalized_end,
                original_fragment=state.original[pending.original_start : pending.original_end],
                replacement_fragment=pending.replacement,
                reason=pending.reason,
                normalization_version=NORMALIZATION_VERSION,
            )
        )
    return NormalizedText(text="".join(state.chars), runs=span_runs, edits=tuple(edits))


def normalize_text(
    text: str,
    *,
    strip_html: bool = False,
    max_length: int | None = None,
    recover_mojibake: bool = True,
) -> NormalizedText:
    """Normalize ``text`` deterministically and reversibly.

    Raises :class:`UnrecoverableTextError` when the text contains U+FFFD
    (replacement character), which proves an earlier lossy decode destroyed
    information that cannot be safely recovered.
    """
    result = _normalize_pure(
        text,
        strip_html=strip_html,
        max_length=max_length,
        recover_mojibake=recover_mojibake,
    )
    # Fail closed: never return a result that cannot be proven faithful by an
    # INDEPENDENT replay from the trusted original and the trusted policy — not
    # from any field of the result object itself.
    audit_faithful_normalization(
        text,
        result,
        strip_html=strip_html,
        max_length=max_length,
        recover_mojibake=recover_mojibake,
    )
    return result


def _normalize_pure(
    text: str,
    *,
    strip_html: bool = False,
    max_length: int | None = None,
    recover_mojibake: bool = True,
) -> NormalizedText:
    """Pure, unaudited deterministic transform (the single source of truth).

    This is the only place the pipeline stages run. Both the public
    :func:`normalize_text` and the independent-replay auditor call it, so the
    auditor never re-enters the public audited entry point (no recursion).
    """
    if type(text) is not str:
        raise TypeError("text must be a str")
    if "\ufffd" in text:
        raise UnrecoverableTextError(
            "text contains U+FFFD (replacement character) and cannot be safely recovered"
        )
    state = Working(original=text)
    _remove_bom(state)
    if recover_mojibake:
        _recover_mojibake(state)
    _normalize_newlines(state)
    _normalize_nfc(state)
    if strip_html:
        strip_html_stage(state)
    _remove_control(state)
    _collapse_whitespace(state)
    if max_length is not None:
        if type(max_length) is not int or max_length <= 0:
            raise ValueError("max_length must be a positive int")
        if len(state.chars) > max_length:
            _truncate(state, max_length)
    return _finalize(state)


def audit_faithful_normalization(
    original: str,
    normalized: NormalizedText,
    *,
    strip_html: bool = False,
    max_length: int | None = None,
    recover_mojibake: bool = True,
) -> None:
    """Prove ``normalized`` is the faithful result of normalizing ``original``.

    The trust root is an **independent replay** from the trusted ``original``
    and the trusted policy parameters (supplied by the caller / service layer,
    never read from the untrusted result). The genuine result is recomputed via
    the pure transform and compared for full structural equality against
    ``normalized`` — text, runs (including every ``normalized_fragment``), edits
    and their spans. A self-consistent forgery that rewrites both
    ``NormalizedText.text`` and the matching ``SpanRun.normalized_fragment``
    (and any digest) is therefore caught, because none of those fields feed the
    expected result.

    The legacy structural + reconstruction audit (:func:`audit_normalization`)
    is also run as a cheap defense-in-depth layer. Raises
    :class:`NormalizationAuditError` on any mismatch. Never mutates input.
    """
    expected = _normalize_pure(
        original,
        strip_html=strip_html,
        max_length=max_length,
        recover_mojibake=recover_mojibake,
    )
    if expected.text != normalized.text:
        raise NormalizationAuditError(
            "normalized text does not match an independent replay of the original"
        )
    if expected.runs != normalized.runs:
        raise NormalizationAuditError(
            "normalized runs do not match an independent replay of the original"
        )
    if expected.edits != normalized.edits:
        raise NormalizationAuditError(
            "normalized edits do not match an independent replay of the original"
        )
    # Defense in depth: structural coverage/monotonicity + exact reconstruction.
    audit_normalization(original, normalized)


def is_fully_recoverable_mojibake(text: str) -> bool:
    """Whether the *whole* text cleanly recovers via latin-1/UTF-8 round-trip.

    True only when every character encodes losslessly to a single latin-1 byte
    and the resulting byte stream decodes as valid UTF-8 producing a different
    string. This is exactly the case :func:`_recover_mojibake` fully repairs, so
    a caller can distinguish safe recovery from mixed/partial mojibake.
    """
    try:
        raw = text.encode("latin-1")
    except UnicodeEncodeError:
        return False
    try:
        recovered = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return recovered != text


def is_confidently_recoverable_mojibake(text: str) -> bool:
    """Whether the whole text is *unambiguously* whole-field mojibake.

    Stronger than :func:`is_fully_recoverable_mojibake`: the whole text must
    round-trip *and* the recovered string must contain at least one character
    outside latin-1 (U+0100+). That proves the original bytes were genuine
    multibyte content (CJK, emoji, …) mis-decoded as latin-1, so automatic
    recovery is safe and unambiguous.

    It deliberately returns ``False`` for text whose recovery stays entirely
    within latin-1 — e.g. ``prefix cafÃ© suffix`` → ``prefix café suffix``.
    Such text is ambiguous (it could be genuine accented Latin, or a partial
    UTF-8-as-latin1 artifact), so it must not be silently rewritten; the
    service routes it to partial-mojibake quality review instead.
    """
    try:
        raw = text.encode("latin-1")
    except UnicodeEncodeError:
        return False
    try:
        recovered = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if recovered == text:
        return False
    return any(ord(character) > 0xFF for character in recovered)


def detect_suspected_mojibake(text: str) -> bool:
    """Detect residual mojibake evidence in ``text``.

    Deterministic, documentable and false-positive-averse. Every character that
    losslessly encodes to a single latin-1 byte is treated as a candidate byte;
    genuine multi-byte Unicode (CJK, emoji) breaks a run. Within each maximal
    latin-1 run, the byte stream is scanned for a valid UTF-8 multibyte
    sequence (2–4 bytes with correct continuation bytes) whose UTF-8 decoding
    *differs* from interpreting those same bytes as latin-1. That difference is
    the signature of UTF-8 bytes mis-decoded as latin-1 (e.g. ``Ã©`` = bytes
    ``C3 A9`` → ``é``, ``ä¸­`` → ``中``). Crucially the decoded character need
    not be outside latin-1: common partial mojibake such as ``cafÃ©`` (from
    ``café``) collapses to the BMP character ``é`` (U+00E9), and is now caught.

    False positives are avoided because a *genuine* accented character
    (``café``, ``résumé``, ``naïve``, ``Zoë``) is a single latin-1 byte that
    does not begin a valid multibyte UTF-8 sequence (its following byte is
    ordinary ASCII, not a ``0x80–0xBF`` continuation byte), so no such island
    forms. Plain ASCII, plain CJK/emoji and lone accents are likewise never
    flagged. Applied to the *raw* text (before control-character removal, which
    would erase the C1/format continuation bytes). Never mutates the text.
    """
    run: list[int] = []

    def _island_has_mojibake(byte_run: list[int]) -> bool:
        raw = bytes(byte_run)
        index = 0
        length = len(raw)
        while index < length:
            byte = raw[index]
            if byte < 0x80:
                index += 1
                continue
            if 0xC2 <= byte <= 0xDF:
                width = 2
            elif 0xE0 <= byte <= 0xEF:
                width = 3
            elif 0xF0 <= byte <= 0xF4:
                width = 4
            else:
                index += 1
                continue
            chunk = raw[index : index + width]
            if len(chunk) == width:
                try:
                    decoded = chunk.decode("utf-8")
                except UnicodeDecodeError:
                    index += 1
                    continue
                # A valid multibyte sequence whose UTF-8 decoding differs from
                # its latin-1 interpretation is mojibake evidence — regardless
                # of whether the decoded character is inside or outside latin-1.
                if decoded != chunk.decode("latin-1"):
                    return True
            index += 1
        return False

    for character in text:
        code = ord(character)
        if code <= 0xFF:
            run.append(code)
            continue
        if _island_has_mojibake(run):
            return True
        run = []
    return _island_has_mojibake(run)
