"""Normalization service: the single entry point for P3-N02.

:func:`normalize` takes an immutable :class:`RawContent` (plus optional
author and attachment metadata) and returns a *new*
:class:`NormalizedContent`. The input is never mutated, every text change is
recorded as a reversible edit with original/normalized offsets, and empty,
attachment-only, overlong and unrecoverable inputs produce typed outcomes
instead of silent success.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from event_core.content.raw_content import ContentSource, RawContent

from intelligence_engine.normalize.metadata import (
    AttachmentInput,
    AuthorInput,
    NormalizedAttachment,
    NormalizedAuthors,
    NormalizedTimes,
    has_usable_attachment,
    normalize_attachments,
    normalize_authors,
    normalize_times,
)
from intelligence_engine.normalize.model import (
    NORMALIZATION_VERSION,
    EmptyBodyReason,
    NormalizationPolicy,
    NormalizationStatus,
    NormalizedText,
    QualityReviewReason,
    RejectionReason,
    UnrecoverableTextError,
)
from intelligence_engine.normalize.text_pipeline import (
    audit_faithful_normalization,
    detect_suspected_mojibake,
    is_confidently_recoverable_mojibake,
    normalize_text,
)

_EMPTY_TEXT = NormalizedText(text="", runs=(), edits=())


@dataclass(frozen=True)
class NormalizedContent:
    """The full normalization result for one RawContent version.

    ``raw`` is an immutable reference to the source :class:`RawContent`, so the
    complete provenance — license/authorization, usage restriction, original
    source, deletion tombstone state, content type, url and fingerprint
    algorithm version — travels with the normalized result and cannot be
    bypassed by a downstream that only reads the normalized text. The
    convenience fields (``record_id`` … ``original_fingerprint``) mirror the
    most-used identifiers; ``normalization_policy_id`` uniquely identifies the
    policy that produced this result.
    """

    raw: RawContent
    record_id: str
    version_id: str
    source: ContentSource
    original_fingerprint: str
    normalization_version: str
    normalization_policy_id: str
    title: NormalizedText
    body: NormalizedText
    times: NormalizedTimes
    authors: NormalizedAuthors
    attachments: tuple[NormalizedAttachment, ...]
    status: NormalizationStatus
    empty_body_reason: EmptyBodyReason | None
    rejection_reason: RejectionReason | None
    quality_review_reason: QualityReviewReason | None

    def is_usable(self, decision_time: datetime) -> bool:
        """Whether this normalized content may be consumed as usable material.

        Fail-closed: a status that is not an ordinary, downstream-consumable
        success is never usable, regardless of authorization or availability.
        That covers ``TOMBSTONE`` (deleted), ``REJECTED`` (unrecoverable) and
        ``QUALITY_REVIEW_REQUIRED`` (a confirmed encoding-quality risk, e.g.
        detected partial mojibake) — the latter must not be silently released
        downstream while this node has no human review-and-approval workflow.
        Only genuinely consumable statuses (``OK``, ``EMPTY_BODY``,
        ``ATTACHMENT_ONLY``) defer to the immutable :class:`RawContent`
        (availability + authorization), so a downstream can never treat
        deleted, unauthorized, rejected or quality-flagged content as ordinary
        consumable text.
        """
        consumable = (
            NormalizationStatus.OK,
            NormalizationStatus.EMPTY_BODY,
            NormalizationStatus.ATTACHMENT_ONLY,
        )
        if self.status not in consumable:
            return False
        return self.raw.is_usable(decision_time)


def _classify_empty_body(
    raw_body: str, normalized_body: str, *, strip_html: bool
) -> EmptyBodyReason | None:
    """Classify why the normalized body is empty (``None`` when it is not)."""
    if normalized_body != "":
        return None
    if raw_body == "":
        return EmptyBodyReason.EMPTY
    has_control = False
    has_visible = False
    for character in raw_body:
        category = unicodedata.category(character)
        if category in ("Cc", "Cf") and character not in ("\t", "\n"):
            has_control = True
        elif not character.isspace() and category not in ("Cc", "Cf"):
            has_visible = True
    if not has_visible:
        if has_control:
            return EmptyBodyReason.CONTROL_CHARS_ONLY
        return EmptyBodyReason.WHITESPACE_ONLY
    if strip_html:
        return EmptyBodyReason.HTML_INVISIBLE_ONLY
    # Defensive: without HTML stripping, visible characters cannot disappear.
    return EmptyBodyReason.WHITESPACE_ONLY


def normalize(
    raw: RawContent,
    *,
    authors: Sequence[str | AuthorInput | None] = (),
    attachments: Sequence[AttachmentInput] = (),
    policy: NormalizationPolicy | None = None,
) -> NormalizedContent:
    """Normalize one immutable RawContent into a new, reversible result."""
    if type(raw) is not RawContent:
        raise TypeError("raw must be an event_core RawContent")
    active_policy = policy if policy is not None else NormalizationPolicy()
    policy_id = active_policy.fingerprint()
    times = normalize_times(raw.publish_time, raw.ingest_time, raw.available_time)
    normalized_authors = normalize_authors(authors, active_policy.author_separators)
    normalized_attachments = normalize_attachments(attachments)

    def _result(
        *,
        title: NormalizedText,
        body: NormalizedText,
        status: NormalizationStatus,
        empty_body_reason: EmptyBodyReason | None,
        rejection_reason: RejectionReason | None,
        quality_review_reason: QualityReviewReason | None,
    ) -> NormalizedContent:
        return NormalizedContent(
            raw=raw,
            record_id=raw.record_id,
            version_id=raw.version_id,
            source=raw.source,
            original_fingerprint=raw.fingerprint,
            normalization_version=NORMALIZATION_VERSION,
            normalization_policy_id=policy_id,
            title=title,
            body=body,
            times=times,
            authors=normalized_authors,
            attachments=normalized_attachments,
            status=status,
            empty_body_reason=empty_body_reason,
            rejection_reason=rejection_reason,
            quality_review_reason=quality_review_reason,
        )

    try:
        title = normalize_text(
            raw.title,
            max_length=active_policy.max_title_length,
            recover_mojibake=active_policy.recover_mojibake,
        )
        body = normalize_text(
            raw.body,
            strip_html=active_policy.strip_html,
            max_length=active_policy.max_body_length,
            recover_mojibake=active_policy.recover_mojibake,
        )
    except UnrecoverableTextError:
        return _result(
            title=_EMPTY_TEXT,
            body=_EMPTY_TEXT,
            status=NormalizationStatus.REJECTED,
            empty_body_reason=None,
            rejection_reason=RejectionReason.MOJIBAKE_UNRECOVERABLE,
            quality_review_reason=None,
        )

    # Fail closed at the production boundary: re-audit both fields by an
    # independent replay under the *actual active policy* (not any field of the
    # result), so a tampered result can never be returned as normalized content.
    audit_faithful_normalization(
        raw.title,
        title,
        max_length=active_policy.max_title_length,
        recover_mojibake=active_policy.recover_mojibake,
    )
    audit_faithful_normalization(
        raw.body,
        body,
        strip_html=active_policy.strip_html,
        max_length=active_policy.max_body_length,
        recover_mojibake=active_policy.recover_mojibake,
    )

    # A deleted record is a tombstone: normalization succeeded and evidence is
    # preserved (raw, times, cleaning audit, provenance), but the result must
    # never enter an ordinary usable branch (OK / EMPTY_BODY / ATTACHMENT_ONLY /
    # QUALITY_REVIEW_REQUIRED). Status precedence: text that could not be
    # normalized at all already returned REJECTED above (still keeping
    # deleted=True on raw); a successfully normalized deleted record is
    # TOMBSTONE. Nothing is physically erased.
    if raw.deleted:
        return _result(
            title=title,
            body=body,
            status=NormalizationStatus.TOMBSTONE,
            empty_body_reason=None,
            rejection_reason=None,
            quality_review_reason=None,
        )

    # Detected-but-unrecoverable mojibake must never be a silent OK. Evidence
    # is read from the *raw* text (control-character removal would otherwise
    # erase the UTF-8 continuation bytes that make up the signature). It is
    # suppressed only when the whole field is *confidently* recoverable —
    # recovery produces content outside latin-1, proving genuine multibyte data
    # — and recovery actually ran. A suspicious field that is not confidently
    # recoverable as a whole is *partial* mojibake (e.g. ``中文 cafÃ©`` or
    # ``prefix cafÃ© suffix``, whose recovery would stay within latin-1 and is
    # therefore ambiguous): it routes to partial-mojibake review and its text
    # is preserved verbatim, never silently rewritten. A confidently
    # recoverable field left unrecovered because recovery is disabled routes to
    # the generic suspected-mojibake review.
    def _review_reason(raw_text: str) -> QualityReviewReason | None:
        if not detect_suspected_mojibake(raw_text):
            return None
        confident = is_confidently_recoverable_mojibake(raw_text)
        if active_policy.recover_mojibake and confident:
            return None
        if not confident:
            return QualityReviewReason.PARTIAL_MOJIBAKE_SUSPECTED
        return QualityReviewReason.SUSPECTED_MOJIBAKE

    review_reason = _review_reason(raw.title) or _review_reason(raw.body)
    if review_reason is not None:
        return _result(
            title=title,
            body=body,
            status=NormalizationStatus.QUALITY_REVIEW_REQUIRED,
            empty_body_reason=None,
            rejection_reason=None,
            quality_review_reason=review_reason,
        )

    empty_body_reason = _classify_empty_body(
        raw.body, body.text, strip_html=active_policy.strip_html
    )
    if empty_body_reason is None:
        status = NormalizationStatus.OK
    elif has_usable_attachment(normalized_attachments):
        status = NormalizationStatus.ATTACHMENT_ONLY
    else:
        status = NormalizationStatus.EMPTY_BODY
    return _result(
        title=title,
        body=body,
        status=status,
        empty_body_reason=empty_body_reason,
        rejection_reason=None,
        quality_review_reason=None,
    )


def audit_faithful_content(
    trusted_raw: RawContent,
    trusted_policy: NormalizationPolicy,
    candidate: NormalizedContent,
    *,
    authors: Sequence[str | AuthorInput | None] = (),
    attachments: Sequence[AttachmentInput] = (),
) -> bool:
    """Content-level trust root: is ``candidate`` faithful to a trusted replay?

    Unlike :func:`audit_faithful_normalization`, which audits a single
    :class:`NormalizedText`, this audits a full :class:`NormalizedContent`
    *result*, including the outer ``normalization_policy_id`` that
    ``audit_faithful_normalization`` never sees. The only trusted inputs are
    the immutable ``trusted_raw``, the explicitly supplied ``trusted_policy``
    and the same author/attachment metadata; nothing on ``candidate`` is
    trusted.

    The check re-runs the *production* :func:`normalize` from those trusted
    inputs to obtain the deterministic ``expected`` result, then verifies:

    * ``candidate.normalization_policy_id == trusted_policy.fingerprint()`` —
      the claimed policy identity is exactly the trusted policy's fingerprint,
      so a result cannot claim a policy that did not produce it; and
    * ``expected == candidate`` — every field agrees. Because every dataclass
      in the result (``NormalizedContent`` and its ``RawContent``, title/body
      ``NormalizedText`` with runs/edits, times, authors, attachments, status,
      empty-body reason, rejection reason and quality-review reason) is a
      frozen dataclass, this structural equality covers text, runs, edits,
      status, quality issues and the full provenance in one comparison.

    A self-consistent forgery (candidate fields mutated to agree with each
    other, e.g. a rewritten body text with matching runs) cannot pass, because
    the audit compares against an independent replay rather than trusting the
    candidate. Reusing the pure normalization boundary (via :func:`normalize`,
    which only performs *text-level* faithful auditing internally) means there
    is no recursion and no risk of the two audit layers drifting apart.

    Returns ``True`` only when both checks pass; any mismatch, or any error
    while replaying the trusted inputs, is fail-closed and returns ``False``.
    """
    if type(candidate) is not NormalizedContent:
        return False
    try:
        expected = normalize(
            trusted_raw,
            authors=authors,
            attachments=attachments,
            policy=trusted_policy,
        )
    except Exception:
        # Any failure to reproduce from trusted inputs is treated as unfaithful.
        return False
    if candidate.normalization_policy_id != trusted_policy.fingerprint():
        return False
    return expected == candidate
