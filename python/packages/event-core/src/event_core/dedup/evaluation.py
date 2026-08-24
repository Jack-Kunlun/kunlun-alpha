"""Deterministic, sanitized threshold evaluation set and metrics (P3-N03).

The evaluation set is small, synthetic and safe to commit: it contains no
production news, cookies, accounts or private raw data. Every case has a stable
id and a duplicate/non-duplicate label, and the set covers exact duplicates,
light title rewrites, small body edits, cross-source reposts, template
announcements, different-company same-type announcements, short text, empty
text and a threshold-boundary case.

:func:`evaluate_labeled_set` runs the deterministic pair decision over each
labeled pair and returns a confusion matrix with precision/recall quantized to
integer basis points, bound to the policy fingerprint that produced it. Zero
denominators return an explicit ``0`` rather than raising.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from event_core.dedup.engine import decide_pair
from event_core.dedup.models import (
    BASIS_POINTS_SCALE,
    DedupInput,
    DedupPolicy,
    Eligibility,
)

# Independent identity for the labeled evaluation set. It is versioned so that
# any change to the cases (inputs, labels, ordering, field boundaries) yields a
# different, auditable fingerprint. It is deliberately separate from the
# algorithm/policy version: the evaluation set and the policy are two distinct
# artifacts, and a result must be traceable to *both*.
EVALUATION_SET_VERSION = "dedup-eval-v1"

_BASE = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)

# A shared, templated announcement body (company name/symbol are the only real
# distinguishers between different issuers using the same boilerplate).
_TEMPLATE_BODY = (
    "公司董事会现就本次权益分派事项公告如下：本次利润分配以方案实施时股权登记日的总股本为基数，"
    "每十股派发现金红利若干元，具体股权登记日及除权除息日详见后续公告，敬请广大投资者注意投资风险。"
)

_ACQUISITION_BODY = (
    "某上市公司发布公告，宣布拟以现金方式收购目标资产，交易金额约为人民币十亿元，"
    "本次交易尚需通过股东大会审议以及监管机构批准。公司表示本次收购有助于完善产业链布局，"
    "提升核心竞争力与持续盈利能力，敬请广大投资者理性投资并注意相关风险。"
)


@dataclass(frozen=True)
class EvaluationCase:
    """One labeled pair with a stable id and a duplicate/non-duplicate label."""

    case_id: str
    left: DedupInput
    right: DedupInput
    expected_duplicate: bool


@dataclass(frozen=True)
class EvaluationResult:
    """Confusion matrix + quantized metrics, bound to policy AND dataset.

    A result is only reproducible if it is tied to *both* the policy that made
    the decisions and the exact evaluation set that was scored. Both are
    recorded here, so changing either one is visible and auditable.
    """

    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision_bps: int
    recall_bps: int
    policy_fingerprint: str
    evaluation_set_version: str
    evaluation_set_fingerprint: str


def evaluation_set_fingerprint(cases: tuple[EvaluationCase, ...]) -> str:
    """Deterministic, version-prefixed SHA-256 over the labeled evaluation set.

    The fingerprint covers the evaluation-set version, every case id, the
    decision-relevant fields of both inputs (title / body / eligibility /
    subject_keys) and the ``expected_duplicate`` label. Cases are sorted by
    ``case_id`` so input order never changes the identity, and each field is an
    explicit key so no concatenation ambiguity is possible. Canonical JSON
    (sorted keys, fixed separators, UTF-8, non-ASCII preserved) is hashed with
    SHA-256; the built-in ``hash()`` is never used. Changing any input, label,
    case id or the set version changes the fingerprint.
    """

    def case_material(case: EvaluationCase) -> dict[str, object]:
        def side(item: DedupInput) -> dict[str, object]:
            return {
                "title": item.title,
                "body": item.body,
                "eligibility": item.eligibility.value,
                "subject_keys": list(item.subject_keys),
            }

        return {
            "case_id": case.case_id,
            "left": side(case.left),
            "right": side(case.right),
            "expected_duplicate": case.expected_duplicate,
        }

    material = {
        "version": EVALUATION_SET_VERSION,
        "cases": [case_material(c) for c in sorted(cases, key=lambda c: c.case_id)],
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{EVALUATION_SET_VERSION}:{digest}"


def _mk(
    content_id: str,
    *,
    title: str,
    body: str,
    source_id: str,
    subject_keys: tuple[str, ...] = (),
    eligibility: Eligibility = Eligibility.ELIGIBLE,
) -> DedupInput:
    return DedupInput(
        content_id=content_id,
        record_id=f"rec-{content_id}",
        version_id="f" * 64,
        source_id=source_id,
        source_revision="v1",
        available_time=_BASE,
        normalization_version="norm-v1",
        normalization_policy_id="pol-fp-1",
        title=title,
        body=body,
        eligibility=eligibility,
        subject_keys=subject_keys,
    )


def build_evaluation_set() -> tuple[EvaluationCase, ...]:
    """Build the deterministic labeled evaluation set (synthetic, sanitized)."""
    cases: list[EvaluationCase] = []

    # 1. exact duplicate, different sources -> duplicate
    cases.append(
        EvaluationCase(
            case_id="exact-cross-source",
            left=_mk(
                "exact-a",
                title="重大资产收购公告",
                body=_ACQUISITION_BODY,
                source_id="cninfo",
                subject_keys=("600000.SH",),
            ),
            right=_mk(
                "exact-b",
                title="重大资产收购公告",
                body=_ACQUISITION_BODY,
                source_id="sina",
                subject_keys=("600000.SH",),
            ),
            expected_duplicate=True,
        )
    )

    # 2. light title rewrite, same body, same subject -> duplicate
    cases.append(
        EvaluationCase(
            case_id="light-title-rewrite",
            left=_mk(
                "lt-a",
                title="某公司重大资产收购公告",
                body=_ACQUISITION_BODY,
                source_id="cninfo",
                subject_keys=("600000.SH",),
            ),
            right=_mk(
                "lt-b",
                title="某公司重大资产收购事项公告",
                body=_ACQUISITION_BODY,
                source_id="sina",
                subject_keys=("600000.SH",),
            ),
            expected_duplicate=True,
        )
    )

    # 3. small body edit repost -> duplicate
    cases.append(
        EvaluationCase(
            case_id="small-body-edit",
            left=_mk(
                "sb-a",
                title="重大资产收购公告",
                body=_ACQUISITION_BODY,
                source_id="cninfo",
                subject_keys=("600000.SH",),
            ),
            right=_mk(
                "sb-b",
                title="重大资产收购公告",
                body=_ACQUISITION_BODY + "（转载）",
                source_id="eastmoney",
                subject_keys=("600000.SH",),
            ),
            expected_duplicate=True,
        )
    )

    # 4. cross-source repost, subject unknown on one side -> duplicate
    cases.append(
        EvaluationCase(
            case_id="cross-source-repost",
            left=_mk("cs-a", title="重大合同签订公告", body=_ACQUISITION_BODY, source_id="cninfo"),
            right=_mk(
                "cs-b", title="重大合同签订公告", body=_ACQUISITION_BODY, source_id="wallstreet"
            ),
            expected_duplicate=True,
        )
    )

    # 5. template announcement, SAME company -> duplicate
    cases.append(
        EvaluationCase(
            case_id="template-same-company",
            left=_mk(
                "ts-a",
                title="甲公司权益分派公告",
                body="甲公司" + _TEMPLATE_BODY,
                source_id="cninfo",
                subject_keys=("600000.SH",),
            ),
            right=_mk(
                "ts-b",
                title="甲公司权益分派公告",
                body="甲公司" + _TEMPLATE_BODY,
                source_id="sina",
                subject_keys=("600000.SH",),
            ),
            expected_duplicate=True,
        )
    )

    # 6. different-company same-type template announcement -> NOT duplicate
    cases.append(
        EvaluationCase(
            case_id="template-different-company",
            left=_mk(
                "td-a",
                title="甲公司权益分派公告",
                body="甲公司" + _TEMPLATE_BODY,
                source_id="cninfo",
                subject_keys=("600000.SH",),
            ),
            right=_mk(
                "td-b",
                title="乙公司权益分派公告",
                body="乙公司" + _TEMPLATE_BODY,
                source_id="cninfo",
                subject_keys=("000001.SZ",),
            ),
            expected_duplicate=False,
        )
    )

    # 7. template body, different company, no subject key -> NOT duplicate
    #    (must be blocked by title/body joint constraint, not subject key)
    cases.append(
        EvaluationCase(
            case_id="template-different-title-no-subject",
            left=_mk("tn-a", title="甲公司权益分派公告", body=_TEMPLATE_BODY, source_id="cninfo"),
            right=_mk("tn-b", title="乙公司季度业绩预告", body=_TEMPLATE_BODY, source_id="cninfo"),
            expected_duplicate=False,
        )
    )

    # 8. short text -> NOT duplicate
    cases.append(
        EvaluationCase(
            case_id="short-text",
            left=_mk("st-a", title="停牌", body="今起停牌", source_id="cninfo"),
            right=_mk("st-b", title="停牌", body="今起停牌", source_id="sina"),
            expected_duplicate=False,
        )
    )

    # 9. empty text -> NOT duplicate
    cases.append(
        EvaluationCase(
            case_id="empty-text",
            left=_mk(
                "et-a",
                title="仅标题公告",
                body="",
                source_id="cninfo",
                eligibility=Eligibility.EMPTY_CONTENT,
            ),
            right=_mk(
                "et-b",
                title="仅标题公告",
                body="",
                source_id="sina",
                eligibility=Eligibility.EMPTY_CONTENT,
            ),
            expected_duplicate=False,
        )
    )

    # 10. generic low-information title, different bodies -> NOT duplicate
    cases.append(
        EvaluationCase(
            case_id="generic-title-different-body",
            left=_mk(
                "gt-a",
                title="公告",
                body="甲公司今日召开董事会审议年度经营计划相关重要议案。",
                source_id="cninfo",
            ),
            right=_mk(
                "gt-b",
                title="公告",
                body="乙公司完成了对某海外子公司的股权出售交易全部流程。",
                source_id="sina",
            ),
            expected_duplicate=False,
        )
    )

    # 11. low-information title + shared template body + NO subject key ->
    #     NOT duplicate (must fail closed: different issuers reuse boilerplate
    #     under a generic title, and no subject clue confirms the same issuer).
    cases.append(
        EvaluationCase(
            case_id="low-info-title-template-no-subject",
            left=_mk("li-a", title="公告", body="甲公司" + _TEMPLATE_BODY, source_id="cninfo"),
            right=_mk("li-b", title="公告", body="乙公司" + _TEMPLATE_BODY, source_id="sina"),
            expected_duplicate=False,
        )
    )

    # 12. conflicting subjects, identical high-information content ->
    #     NOT duplicate (subject conflict blocks even an exact content match).
    _conflict_body = "完全相同的重大事项正文说明。" + _ACQUISITION_BODY
    cases.append(
        EvaluationCase(
            case_id="conflicting-subject-exact-content",
            left=_mk(
                "cf-a",
                title="重大事项进展公告",
                body=_conflict_body,
                source_id="cninfo",
                subject_keys=("600000.SH",),
            ),
            right=_mk(
                "cf-b",
                title="重大事项进展公告",
                body=_conflict_body,
                source_id="sina",
                subject_keys=("000001.SZ",),
            ),
            expected_duplicate=False,
        )
    )

    return tuple(cases)


def evaluate_labeled_set(
    cases: tuple[EvaluationCase, ...], *, policy: DedupPolicy
) -> EvaluationResult:
    """Evaluate the labeled pairs and return a confusion matrix + metrics.

    Precision = TP / (TP + FP); recall = TP / (TP + FN); both quantized to
    integer basis points. A zero denominator yields an explicit ``0`` (never a
    crash). The result carries the policy fingerprint it was computed under.
    """
    tp = fp = tn = fn = 0
    for case in cases:
        predicted = decide_pair(case.left, case.right, policy=policy).is_duplicate
        if case.expected_duplicate and predicted:
            tp += 1
        elif case.expected_duplicate and not predicted:
            fn += 1
        elif not case.expected_duplicate and predicted:
            fp += 1
        else:
            tn += 1
    precision_bps = round(BASIS_POINTS_SCALE * tp / (tp + fp)) if (tp + fp) else 0
    recall_bps = round(BASIS_POINTS_SCALE * tp / (tp + fn)) if (tp + fn) else 0
    return EvaluationResult(
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision_bps=precision_bps,
        recall_bps=recall_bps,
        policy_fingerprint=policy.fingerprint(),
        evaluation_set_version=EVALUATION_SET_VERSION,
        evaluation_set_fingerprint=evaluation_set_fingerprint(cases),
    )
