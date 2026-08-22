"""End-to-end service tests: statuses, empty body, overlong, determinism,
immutability, idempotency and rejection handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest
from event_core.content.raw_content import (
    ContentSource,
    LicenseMetadata,
    RawContent,
)
from intelligence_engine.normalize import (
    NORMALIZATION_VERSION,
    AttachmentInput,
    AttachmentStatus,
    EmptyBodyReason,
    NormalizationPolicy,
    NormalizationStatus,
    Operation,
    QualityReviewReason,
    RejectionReason,
    UnsupportedNormalizationVersionError,
    audit_normalization,
    normalize,
    restore_original,
)

_CST = timezone(timedelta(hours=8))

_SOURCE = ContentSource(source_id="src-1", source_version="v1", evidence_id="ev-1")
_LICENSE = LicenseMetadata(license_id="lic-1", usage_restriction="research", authorized=True)


def _raw(
    body: str,
    *,
    title: str = "标题",
    publish: datetime | None = None,
) -> RawContent:
    return RawContent(
        content_type="NEWS",
        source=_SOURCE,
        url="https://example.com/a",
        title=title,
        body=body,
        publish_time=publish or datetime(2026, 8, 1, tzinfo=UTC),
        ingest_time=datetime(2026, 8, 1, 1, tzinfo=UTC),
        available_time=datetime(2026, 8, 1, 2, tzinfo=UTC),
        license=_LICENSE,
        record_id="rec-1",
    )


class TestOkPath:
    def test_result_retains_provenance(self) -> None:
        raw = _raw("正文内容")
        result = normalize(raw)
        assert result.record_id == raw.record_id
        assert result.version_id == raw.version_id
        assert result.source == raw.source
        assert result.original_fingerprint == raw.fingerprint
        assert result.normalization_version == NORMALIZATION_VERSION

    def test_normal_text_passes_through(self) -> None:
        result = normalize(_raw("正文内容"))
        assert result.status == NormalizationStatus.OK
        assert result.body.text == "正文内容"
        assert result.body.edits == ()

    def test_body_is_cleaned_with_audit(self) -> None:
        raw = _raw("  正文\r\n内容 \x00 ")
        result = normalize(raw)
        assert result.body.text == "正文\n内容"
        audit_normalization(raw.body, result.body)
        assert restore_original(result.body, len(raw.body)) == raw.body

    def test_html_body_is_stripped(self) -> None:
        raw = _raw("<p>正文 &amp; 内容</p>")
        result = normalize(raw, policy=NormalizationPolicy(strip_html=True))
        assert result.status == NormalizationStatus.OK
        assert result.body.text == "正文 & 内容"

    def test_times_are_utc_normalized(self) -> None:
        raw = _raw(
            "正文",
            publish=datetime(2026, 8, 1, 8, 30, tzinfo=_CST),
        )
        result = normalize(raw)
        assert result.times.publish_time == datetime(2026, 8, 1, 0, 30, tzinfo=UTC)
        assert result.times.ingest_time.tzinfo is UTC

    def test_timezone_equivalent_inputs_give_equal_results(self) -> None:
        cst = _raw(
            "正文",
            publish=datetime(2026, 8, 1, 8, 30, tzinfo=_CST),
        )
        utc = _raw(
            "正文",
            publish=datetime(2026, 8, 1, 0, 30, tzinfo=UTC),
        )
        assert normalize(cst) == normalize(utc)


class TestEmptyBody:
    def test_empty_body(self) -> None:
        result = normalize(_raw(""))
        assert result.status == NormalizationStatus.EMPTY_BODY
        assert result.empty_body_reason == EmptyBodyReason.EMPTY

    def test_whitespace_only_body(self) -> None:
        result = normalize(_raw("   \n\t  "))
        assert result.status == NormalizationStatus.EMPTY_BODY
        assert result.empty_body_reason == EmptyBodyReason.WHITESPACE_ONLY

    def test_control_only_body(self) -> None:
        result = normalize(_raw("\x00\x01\x0c"))
        assert result.status == NormalizationStatus.EMPTY_BODY
        assert result.empty_body_reason == EmptyBodyReason.CONTROL_CHARS_ONLY

    def test_html_empty_body(self) -> None:
        result = normalize(_raw("<script>x</script>"), policy=NormalizationPolicy(strip_html=True))
        assert result.status == NormalizationStatus.EMPTY_BODY
        assert result.empty_body_reason == EmptyBodyReason.HTML_INVISIBLE_ONLY

    def test_attachment_only_body(self) -> None:
        raw = _raw("")
        result = normalize(
            raw,
            attachments=[
                AttachmentInput(
                    uri="https://example.com/a.pdf", filename="a.pdf", mime_type="application/pdf"
                ),
            ],
        )
        assert result.status == NormalizationStatus.ATTACHMENT_ONLY
        assert result.empty_body_reason == EmptyBodyReason.EMPTY
        assert result.attachments[0].status == AttachmentStatus.OK

    def test_attachment_only_body_is_not_silent_success(self) -> None:
        result = normalize(
            _raw("  "), attachments=[AttachmentInput(uri="https://example.com/a.pdf")]
        )
        assert result.status != NormalizationStatus.OK


class TestOverlong:
    def test_exact_limit_is_ok(self) -> None:
        policy = NormalizationPolicy(max_body_length=10)
        result = normalize(_raw("x" * 10), policy=policy)
        assert result.status == NormalizationStatus.OK
        assert result.body.text == "x" * 10
        assert all(e.operation != Operation.TRUNCATE for e in result.body.edits)

    def test_one_over_limit_truncates_with_evidence(self) -> None:
        policy = NormalizationPolicy(max_body_length=10)
        raw = _raw("x" * 11)
        result = normalize(raw, policy=policy)
        assert result.body.text == "x" * 10
        edit = next(e for e in result.body.edits if e.operation == Operation.TRUNCATE)
        assert edit.original_fragment == "x"
        assert raw.body == "x" * 11  # original untouched
        audit_normalization(raw.body, result.body)

    def test_far_over_limit_truncates_with_full_tail(self) -> None:
        policy = NormalizationPolicy(max_body_length=10)
        raw = _raw("x" * 5000)
        result = normalize(raw, policy=policy)
        assert result.body.text == "x" * 10
        edit = next(e for e in result.body.edits if e.operation == Operation.TRUNCATE)
        assert edit.original_fragment == "x" * 4990


class TestDeterminismAndImmutability:
    def test_same_input_same_result(self) -> None:
        raw = _raw("  正文\r\n内容 ")
        assert normalize(raw) == normalize(raw)

    def test_input_raw_content_is_not_modified(self) -> None:
        raw = _raw("  正文\r\n \x00 ")
        before = (raw.title, raw.body, raw.version_id, raw.fingerprint)
        normalize(raw)
        assert (raw.title, raw.body, raw.version_id, raw.fingerprint) == before

    def test_result_object_is_new_not_in_place(self) -> None:
        raw = _raw("  正文 ")
        result = normalize(raw)
        assert result is not raw
        assert raw.body == "  正文 "

    def test_normalization_is_idempotent(self) -> None:
        raw = _raw("  正文\r\n \x00 内容  ")
        first = normalize(raw)
        second_raw = _raw(first.body.text)
        second = normalize(second_raw)
        assert second.body.text == first.body.text
        assert second.body.edits == ()


class TestRejection:
    def test_unrecoverable_mojibake_is_rejected(self) -> None:
        raw = _raw("broken \ufffd body")
        result = normalize(raw)
        assert result.status == NormalizationStatus.REJECTED
        assert result.rejection_reason == RejectionReason.MOJIBAKE_UNRECOVERABLE

    def test_recoverable_mojibake_is_normalized(self) -> None:
        mojibake = "中文新闻".encode().decode("latin-1")
        result = normalize(_raw(mojibake))
        assert result.status == NormalizationStatus.OK
        assert result.body.text == "中文新闻"

    def test_rejected_result_still_carries_provenance(self) -> None:
        raw = _raw("broken \ufffd body")
        result = normalize(raw)
        assert result.record_id == raw.record_id
        assert result.version_id == raw.version_id
        assert result.rejection_reason is not None

    def test_unsupported_policy_version_is_rejected(self) -> None:
        with pytest.raises(UnsupportedNormalizationVersionError):
            normalize(_raw("x"), policy=NormalizationPolicy(version=NORMALIZATION_VERSION + "-x"))

    def test_non_raw_content_input_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            normalize(cast(RawContent, "not a raw content"))


class TestMetadataEndToEnd:
    def test_authors_are_normalized(self) -> None:
        result = normalize(_raw("正文"), authors=["张三, 李四", "张三"])
        assert [a.normalized_name for a in result.authors.normalized] == ["张三", "李四"]
        assert result.authors.original_authors == ("张三, 李四", "张三")

    def test_attachments_are_normalized(self) -> None:
        result = normalize(
            _raw("正文"),
            attachments=[
                AttachmentInput(
                    uri="https://example.com/a.pdf", filename="a.pdf", mime_type="application/pdf"
                ),
                AttachmentInput(uri=""),
            ],
        )
        assert result.attachments[0].status == AttachmentStatus.OK
        assert result.attachments[1].status == AttachmentStatus.INVALID_URI

    def test_author_normalization_is_stable_across_runs(self) -> None:
        a = normalize(_raw("正文"), authors=["张三 , 李四"])
        b = normalize(_raw("正文"), authors=["张三 , 李四"])
        assert a == b


# --- P3-N02 fix: policy identity carried on the result (Important #3) ---


class TestPolicyIdentity:
    def test_result_carries_policy_fingerprint(self) -> None:
        policy = NormalizationPolicy()
        result = normalize(_raw("正文"), policy=policy)
        assert result.normalization_policy_id == policy.fingerprint()

    def test_same_input_same_policy_same_identity(self) -> None:
        policy = NormalizationPolicy(strip_html=True, max_body_length=99)
        a = normalize(_raw("<p>正文</p>"), policy=policy)
        b = normalize(_raw("<p>正文</p>"), policy=policy)
        assert a.normalization_policy_id == b.normalization_policy_id

    def test_different_policies_differ_in_identity(self) -> None:
        a = normalize(_raw("正文"), policy=NormalizationPolicy())
        b = normalize(_raw("正文"), policy=NormalizationPolicy(recover_mojibake=False))
        assert a.normalization_policy_id != b.normalization_policy_id


# --- P3-N02 fix: mixed/partial mojibake must not be silent OK (Important #4) ---


class TestMixedMojibake:
    def test_known_mixed_mojibake_is_not_ok(self) -> None:
        # genuine text + mojibake cannot round-trip as a whole; it must not be
        # silently returned as OK content.
        mixed = "报道：" + "中文".encode().decode("latin-1")
        result = normalize(_raw(mixed))
        assert result.status != NormalizationStatus.OK

    def test_known_mixed_mojibake_has_typed_status(self) -> None:
        mixed = "报道：" + "中文".encode().decode("latin-1")
        result = normalize(_raw(mixed))
        assert result.status in (
            NormalizationStatus.REJECTED,
            NormalizationStatus.QUALITY_REVIEW_REQUIRED,
        )

    def test_recoverable_mojibake_still_ok(self) -> None:
        result = normalize(_raw("中文新闻".encode().decode("latin-1")))
        assert result.status == NormalizationStatus.OK
        assert result.body.text == "中文新闻"

    def test_plain_cjk_english_french_not_flagged(self) -> None:
        for text in ("正常中文内容", "plain english text", "café déjà vu résumé"):
            result = normalize(_raw(text))
            assert result.status == NormalizationStatus.OK

    def test_suspected_mojibake_not_silent_ok_when_recovery_disabled(self) -> None:
        mojibake = "中文".encode().decode("latin-1")
        result = normalize(_raw(mojibake), policy=NormalizationPolicy(recover_mojibake=False))
        assert result.status != NormalizationStatus.OK

    # --- P3-N02 round-2 fix: partial BMP mojibake like cafÃ© (Important #3) ---

    def test_chinese_plus_cafe_mojibake_is_not_ok(self) -> None:
        from intelligence_engine.normalize import QualityReviewReason

        result = normalize(_raw("中文 " + "café".encode().decode("latin-1")))
        assert result.status != NormalizationStatus.OK
        assert result.status == NormalizationStatus.QUALITY_REVIEW_REQUIRED
        assert result.quality_review_reason == QualityReviewReason.PARTIAL_MOJIBAKE_SUSPECTED

    def test_prefix_cafe_mojibake_suffix_is_not_ok(self) -> None:
        result = normalize(_raw("prefix " + "café".encode().decode("latin-1") + " suffix"))
        assert result.status == NormalizationStatus.QUALITY_REVIEW_REQUIRED

    def test_partial_mojibake_preserves_original_text(self) -> None:
        mojibake = "café".encode().decode("latin-1")  # "cafÃ©"
        raw = _raw("中文 " + mojibake)
        result = normalize(raw)
        # not silently rewritten: the suspicious body is preserved verbatim and
        # remains exactly reversible to the original.
        assert "cafÃ©" in result.body.text
        assert restore_original(result.body, len(raw.body)) == raw.body

    def test_partial_mojibake_not_ok_when_recovery_disabled(self) -> None:
        result = normalize(
            _raw("中文 " + "café".encode().decode("latin-1")),
            policy=NormalizationPolicy(recover_mojibake=False),
        )
        assert result.status != NormalizationStatus.OK

    def test_genuine_accents_stay_ok(self) -> None:
        for text in ("café", "résumé", "français", "中文 café", "naïve"):
            result = normalize(_raw(text))
            assert result.status == NormalizationStatus.OK, text


# --- P3-N02 fix: ATTACHMENT_ONLY requires a usable attachment (Important #5) ---


class TestAttachmentOnlyValidity:
    def _pdf(self, uri: str = "https://example.com/a.pdf") -> AttachmentInput:
        return AttachmentInput(uri=uri, filename="a.pdf", mime_type="application/pdf")

    def test_empty_body_with_ok_attachment(self) -> None:
        result = normalize(_raw(""), attachments=[self._pdf()])
        assert result.status == NormalizationStatus.ATTACHMENT_ONLY

    def test_empty_body_with_invalid_uri_is_not_attachment_only(self) -> None:
        result = normalize(_raw(""), attachments=[AttachmentInput(uri="   ")])
        assert result.status != NormalizationStatus.ATTACHMENT_ONLY
        assert result.status == NormalizationStatus.EMPTY_BODY

    def test_empty_body_with_unsupported_scheme_is_not_attachment_only(self) -> None:
        result = normalize(
            _raw(""),
            attachments=[
                AttachmentInput(uri="mailto:x@example.com", filename="x", mime_type="text/plain")
            ],
        )
        assert result.status != NormalizationStatus.ATTACHMENT_ONLY

    def test_empty_body_with_missing_metadata_is_not_attachment_only(self) -> None:
        result = normalize(_raw(""), attachments=[AttachmentInput(uri="https://example.com/a.pdf")])
        assert result.status != NormalizationStatus.ATTACHMENT_ONLY

    def test_empty_body_with_only_duplicates_is_not_attachment_only(self) -> None:
        # first is OK, but if the only *distinct* usable content is a duplicate
        # of an already-counted attachment, duplicates alone cannot make content.
        result = normalize(
            _raw(""),
            attachments=[
                AttachmentInput(uri="https://example.com/a.pdf"),  # missing metadata
                AttachmentInput(uri="https://example.com/a.pdf"),  # duplicate
            ],
        )
        assert result.status != NormalizationStatus.ATTACHMENT_ONLY

    def test_empty_body_with_invalid_and_one_ok_is_attachment_only(self) -> None:
        result = normalize(
            _raw(""),
            attachments=[AttachmentInput(uri="   "), self._pdf()],
        )
        assert result.status == NormalizationStatus.ATTACHMENT_ONLY

    def test_attachment_original_fields_preserved(self) -> None:
        result = normalize(_raw(""), attachments=[self._pdf()])
        assert result.attachments[0].original_uri == "https://example.com/a.pdf"
        assert result.attachments[0].original_filename == "a.pdf"


# --- P3-N02 fix: provenance / license / deletion state preserved (Important #6) ---


class TestProvenancePreservation:
    def _licensed(self, *, authorized: bool) -> RawContent:
        return RawContent(
            content_type="NEWS",
            source=_SOURCE,
            url="https://example.com/a",
            title="标题",
            body="正文",
            publish_time=datetime(2026, 8, 1, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 1, 1, tzinfo=UTC),
            available_time=datetime(2026, 8, 1, 2, tzinfo=UTC),
            license=LicenseMetadata(
                license_id="lic-2",
                usage_restriction="internal-only",
                authorized=authorized,
            ),
            record_id="rec-2",
            original_source=ContentSource(
                source_id="orig", source_version="v0", evidence_id="orig-ev"
            ),
        )

    def test_unauthorized_stays_unauthorized(self) -> None:
        raw = self._licensed(authorized=False)
        result = normalize(raw)
        assert result.raw.license.authorized is False

    def test_usage_restriction_preserved(self) -> None:
        raw = self._licensed(authorized=True)
        result = normalize(raw)
        assert result.raw.license.usage_restriction == "internal-only"

    def test_original_source_preserved(self) -> None:
        raw = self._licensed(authorized=True)
        result = normalize(raw)
        assert result.raw.original_source == raw.original_source

    def test_content_type_and_url_preserved(self) -> None:
        raw = self._licensed(authorized=True)
        result = normalize(raw)
        assert result.raw.content_type == "NEWS"
        assert result.raw.url == "https://example.com/a"
        assert result.raw.fingerprint_algorithm_version == raw.fingerprint_algorithm_version

    def test_tombstone_deletion_state_preserved(self) -> None:
        from event_core.content.raw_content import mark_deleted

        raw = self._licensed(authorized=True)
        tombstone = mark_deleted(raw, deleted_at=datetime(2026, 8, 2, tzinfo=UTC))
        result = normalize(tombstone)
        assert result.raw.deleted is True
        assert result.raw.deleted_at == tombstone.deleted_at
        # a tombstone must never be represented as ordinary usable content
        assert result.raw.is_usable(datetime(2026, 8, 3, tzinfo=UTC)) is False

    def test_input_raw_content_still_immutable(self) -> None:
        raw = self._licensed(authorized=False)
        before = (raw.version_id, raw.license.authorized, raw.deleted)
        normalize(raw)
        assert (raw.version_id, raw.license.authorized, raw.deleted) == before


# --- P3-N02 round-2 fix: a tombstone must never be plain OK content (Critical #2) ---


class TestTombstoneStatus:
    def _tombstone(
        self,
        *,
        body: str = "正文内容",
        title: str = "标题",
        authorized: bool = True,
    ) -> RawContent:
        from event_core.content.raw_content import mark_deleted

        live = RawContent(
            content_type="NEWS",
            source=_SOURCE,
            url="https://example.com/a",
            title=title,
            body=body,
            publish_time=datetime(2026, 8, 1, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 1, 1, tzinfo=UTC),
            available_time=datetime(2026, 8, 1, 2, tzinfo=UTC),
            license=LicenseMetadata(
                license_id="lic-3",
                usage_restriction="internal-only",
                authorized=authorized,
            ),
            record_id="rec-3",
            original_source=ContentSource(
                source_id="orig", source_version="v0", evidence_id="orig-ev"
            ),
        )
        return mark_deleted(live, deleted_at=datetime(2026, 8, 2, tzinfo=UTC))

    def test_nonempty_tombstone_is_not_ok(self) -> None:
        result = normalize(self._tombstone(body="正文内容"))
        assert result.status is not NormalizationStatus.OK
        assert result.status == NormalizationStatus.TOMBSTONE

    def test_empty_body_tombstone_is_tombstone(self) -> None:
        result = normalize(self._tombstone(body=""))
        assert result.status == NormalizationStatus.TOMBSTONE

    def test_tombstone_with_valid_attachment_is_not_attachment_only(self) -> None:
        result = normalize(
            self._tombstone(body=""),
            attachments=[AttachmentInput(uri="https://example.com/a.pdf", filename="a.pdf")],
        )
        assert result.status == NormalizationStatus.TOMBSTONE
        assert result.status != NormalizationStatus.ATTACHMENT_ONLY

    def test_unauthorized_tombstone_is_not_usable(self) -> None:
        result = normalize(self._tombstone(authorized=False))
        assert result.is_usable(datetime(2026, 8, 3, tzinfo=UTC)) is False

    def test_authorized_tombstone_is_still_not_usable(self) -> None:
        result = normalize(self._tombstone(authorized=True))
        assert result.is_usable(datetime(2026, 8, 3, tzinfo=UTC)) is False

    def test_tombstone_preserves_provenance_and_evidence(self) -> None:
        raw = self._tombstone(body="正文内容")
        result = normalize(raw)
        assert result.raw.deleted is True
        assert result.raw.deleted_at == raw.deleted_at
        assert result.raw.previous_version_id == raw.previous_version_id
        assert result.raw.original_source == raw.original_source
        assert result.raw.license.usage_restriction == "internal-only"
        assert result.original_fingerprint == raw.fingerprint
        assert result.version_id == raw.version_id
        # body/title text and reversible audit trail are not physically erased
        assert result.body.text == "正文内容"
        assert restore_original(result.body, len("正文内容")) == "正文内容"

    def test_live_content_still_classified_normally(self) -> None:
        live = _raw("正文内容")
        assert live.deleted is False
        result = normalize(live)
        assert result.status == NormalizationStatus.OK
        assert result.is_usable(datetime(2026, 8, 2, tzinfo=UTC)) is True


# --- P3-N02 round-3 fix: QUALITY_REVIEW_REQUIRED must fail closed (Important 1) ---


class TestQualityReviewNotUsable:
    def _cafe_mojibake_body(self) -> str:
        return "中文 " + "café".encode().decode("latin-1")  # "中文 cafÃ©"

    def test_partial_mojibake_is_quality_review_with_reason(self) -> None:
        result = normalize(_raw(self._cafe_mojibake_body()))
        assert result.status == NormalizationStatus.QUALITY_REVIEW_REQUIRED
        assert result.quality_review_reason == QualityReviewReason.PARTIAL_MOJIBAKE_SUSPECTED

    def test_quality_review_not_usable_even_when_raw_usable(self) -> None:
        # authorized, not deleted, available_time already reached -> raw.is_usable
        # would be True, but the encoding-quality risk must fail closed.
        raw = _raw(self._cafe_mojibake_body())
        assert raw.is_usable(datetime(2026, 8, 2, tzinfo=UTC)) is True
        result = normalize(raw)
        assert result.status == NormalizationStatus.QUALITY_REVIEW_REQUIRED
        assert result.is_usable(datetime(2026, 8, 2, tzinfo=UTC)) is False

    def test_normal_text_still_usable(self) -> None:
        for text in ("正文内容", "café", "résumé", "中文 café"):
            raw = _raw(text)
            result = normalize(raw)
            assert result.status == NormalizationStatus.OK, text
            assert result.is_usable(datetime(2026, 8, 2, tzinfo=UTC)) is True, text

    def test_rejected_still_not_usable(self) -> None:
        raw = _raw("bad \ufffd text")
        result = normalize(raw)
        assert result.status == NormalizationStatus.REJECTED
        assert result.is_usable(datetime(2026, 8, 2, tzinfo=UTC)) is False

    def test_tombstone_still_not_usable(self) -> None:
        from event_core.content.raw_content import mark_deleted

        live = _raw("正文内容")
        tombstone = mark_deleted(live, deleted_at=datetime(2026, 8, 2, tzinfo=UTC))
        result = normalize(tombstone)
        assert result.status == NormalizationStatus.TOMBSTONE
        assert result.is_usable(datetime(2026, 8, 3, tzinfo=UTC)) is False


# --- P3-N02 round-3 fix: content-level faithful audit incl. policy id (Important 2) ---


class TestFaithfulContentAudit:
    """A result-level trust root: re-run deterministic normalization from a
    *trusted* RawContent + *trusted* NormalizationPolicy and verify the
    candidate NormalizedContent is exactly what that trusted pair produces —
    including ``normalization_policy_id``, title/body (text/runs/edits),
    status, quality issues and provenance. A self-consistent forgery (candidate
    fields mutated to agree with each other) cannot pass, because the audit
    never trusts any field of the candidate.
    """

    def _trusted_policy(self) -> NormalizationPolicy:
        return NormalizationPolicy(strip_html=True, max_body_length=500)

    def test_untampered_result_passes(self) -> None:
        from intelligence_engine.normalize import audit_faithful_content

        raw = _raw("<p>正文 &amp; 内容</p>")
        policy = self._trusted_policy()
        candidate = normalize(raw, policy=policy)
        assert audit_faithful_content(raw, policy, candidate) is True

    def test_untampered_result_with_metadata_passes(self) -> None:
        from intelligence_engine.normalize import audit_faithful_content

        raw = _raw("")
        policy = NormalizationPolicy()
        authors = ["张三, 李四"]
        attachments = [
            AttachmentInput(
                uri="https://example.com/a.pdf", filename="a.pdf", mime_type="application/pdf"
            )
        ]
        candidate = normalize(raw, authors=authors, attachments=attachments, policy=policy)
        assert (
            audit_faithful_content(raw, policy, candidate, authors=authors, attachments=attachments)
            is True
        )

    def test_only_policy_id_tampered_fails(self) -> None:
        # everything else agrees, only the policy id claims a different policy.
        from dataclasses import replace

        from intelligence_engine.normalize import audit_faithful_content

        raw = _raw("正文内容")
        policy = self._trusted_policy()
        candidate = normalize(raw, policy=policy)
        forged = replace(candidate, normalization_policy_id="0" * 64)
        assert audit_faithful_content(raw, policy, forged) is False

    def test_wrong_but_real_policy_impersonation_fails(self) -> None:
        # candidate was produced under `other`, but its id + fields are the ones
        # `other` yields; auditing against the *trusted* policy must fail because
        # the trusted policy would produce a different result.
        from intelligence_engine.normalize import audit_faithful_content

        trusted = self._trusted_policy()
        other = NormalizationPolicy(strip_html=False, max_body_length=500)
        raw = _raw("<p>正文 &amp; 内容</p>")
        candidate = normalize(raw, policy=other)
        assert candidate.normalization_policy_id == other.fingerprint()
        assert audit_faithful_content(raw, trusted, candidate) is False

    def test_policy_id_and_internal_fields_jointly_tampered_fails(self) -> None:
        # forge policy id to a fake AND rewrite the body text to agree with a
        # different (silent) transformation; still must fail.
        from dataclasses import replace

        from intelligence_engine.normalize import NormalizedText, audit_faithful_content

        raw = _raw("<p>正文 &amp; 内容</p>")
        policy = self._trusted_policy()
        candidate = normalize(raw, policy=policy)
        forged_body = NormalizedText(text="任意伪造正文", runs=(), edits=())
        forged = replace(
            candidate,
            normalization_policy_id=policy.fingerprint()[::-1],
            body=forged_body,
        )
        assert audit_faithful_content(raw, policy, forged) is False

    def test_self_consistent_body_text_forgery_fails(self) -> None:
        # a candidate whose body text + runs/edits are internally consistent but
        # do NOT match the trusted replay must fail (audit never trusts the
        # candidate's own fields).
        from dataclasses import replace

        from intelligence_engine.normalize import NormalizedText, audit_faithful_content

        raw = _raw("正文内容")
        policy = self._trusted_policy()
        candidate = normalize(raw, policy=policy)
        forged_body = NormalizedText(text="正文内容 EXTRA", runs=(), edits=())
        forged = replace(candidate, body=forged_body)
        assert audit_faithful_content(raw, policy, forged) is False

    def test_title_tampered_fails(self) -> None:
        from dataclasses import replace

        from intelligence_engine.normalize import NormalizedText, audit_faithful_content

        raw = _raw("正文内容", title="真实标题")
        policy = self._trusted_policy()
        candidate = normalize(raw, policy=policy)
        forged = replace(candidate, title=NormalizedText(text="伪造标题", runs=(), edits=()))
        assert audit_faithful_content(raw, policy, forged) is False

    def test_status_tampered_fails(self) -> None:
        # a quality-review result forged to claim OK status must fail.
        from dataclasses import replace

        from intelligence_engine.normalize import audit_faithful_content

        raw = _raw("中文 " + "café".encode().decode("latin-1"))
        policy = self._trusted_policy()
        candidate = normalize(raw, policy=policy)
        assert candidate.status == NormalizationStatus.QUALITY_REVIEW_REQUIRED
        forged = replace(
            candidate,
            status=NormalizationStatus.OK,
            quality_review_reason=None,
        )
        assert audit_faithful_content(raw, policy, forged) is False

    def test_quality_reason_tampered_fails(self) -> None:
        from dataclasses import replace

        from intelligence_engine.normalize import audit_faithful_content

        raw = _raw("中文 " + "café".encode().decode("latin-1"))
        policy = self._trusted_policy()
        candidate = normalize(raw, policy=policy)
        forged = replace(candidate, quality_review_reason=QualityReviewReason.SUSPECTED_MOJIBAKE)
        assert audit_faithful_content(raw, policy, forged) is False

    def test_provenance_tampered_fails(self) -> None:
        # rewrite an identifier that must mirror the trusted raw's provenance.
        from dataclasses import replace

        from intelligence_engine.normalize import audit_faithful_content

        raw = _raw("正文内容")
        policy = self._trusted_policy()
        candidate = normalize(raw, policy=policy)
        forged = replace(candidate, original_fingerprint="deadbeef")
        assert audit_faithful_content(raw, policy, forged) is False

    def test_raw_reference_tampered_fails(self) -> None:
        # the candidate points at a different RawContent (e.g. a live copy of a
        # deleted record) than the trusted raw; must fail.
        from dataclasses import replace

        from event_core.content.raw_content import mark_deleted
        from intelligence_engine.normalize import audit_faithful_content

        raw = _raw("正文内容")
        policy = self._trusted_policy()
        candidate = normalize(raw, policy=policy)
        other_raw = mark_deleted(raw, deleted_at=datetime(2026, 8, 2, tzinfo=UTC))
        forged = replace(candidate, raw=other_raw)
        assert audit_faithful_content(raw, policy, forged) is False

    def test_crlf_edit_span_forgery_fails(self) -> None:
        # a CRLF body normalizes to LF with reversible edits; forging the edits
        # away (claiming no change happened) must fail.
        from dataclasses import replace

        from intelligence_engine.normalize import NormalizedText, audit_faithful_content

        raw = _raw("正文\r\n内容")
        policy = self._trusted_policy()
        candidate = normalize(raw, policy=policy)
        assert candidate.body.edits != ()
        forged_body = NormalizedText(text=candidate.body.text, runs=(), edits=())
        forged = replace(candidate, body=forged_body)
        assert audit_faithful_content(raw, policy, forged) is False
