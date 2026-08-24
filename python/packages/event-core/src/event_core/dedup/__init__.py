"""Near-duplicate detection domain (P3-N03).

Pure, deterministic, offline near-duplicate clustering. No I/O, no network, no
LLM, no embedding, no database and no service dependency. This package never
imports ``intelligence_engine``; normalized text and provenance are carried by
value into :class:`DedupInput`.

Algorithm reference (V1, ``DEDUP_ALGORITHM_VERSION = "neardup-v1"``)
===================================================================

Purpose
-------
Recognize reposts / near-duplicates of the *same* piece of content across
sources (转载) so that a later stage sees one cluster with one master record
instead of N copies. Physical records are never merged or deleted: every
member keeps its own ``content_id`` and full provenance; a cluster is only an
overlay that names one member the master.

Input contract and pre-normalization assumptions
-------------------------------------------------
The single input is :class:`DedupInput`, projected *by the caller* (a
normalization service or an assembler) from an already-normalized record. This
node assumes the text has already gone through P3-N02 normalization (unicode
NFC, whitespace/case folding as configured upstream, boilerplate handling); it
does not re-normalize semantics. Each input carries:

* ``content_id`` — stable identity of the normalized content unit.
* ``record_id`` / ``version_id`` / ``source_id`` / ``source_revision`` —
  provenance to trace back to the raw record without any reverse dependency.
* ``available_time`` — the point-in-time axis (timezone-aware, UTC; naive
  datetimes are rejected at the boundary).
* ``normalization_version`` / ``normalization_policy_id`` — the normalization
  identity that produced the text.
* ``title`` / ``body`` — the normalized text to compare.
* ``eligibility`` — a fail-closed consumability decision (see below).
* ``subject_keys`` — optional caller-supplied subject clues (e.g. a security
  symbol or a source subject key). This node does *not* derive subject
  identity itself — entity recognition / security parsing / company
  disambiguation is P3-N04 — it only *uses* conflicting clues defensively.

Exact content hash (``content_hash``)
--------------------------------------
A stable, version-prefixed SHA-256 over normalized ``title`` + ``body``. Field
boundaries are unambiguous: each field is length-prefixed and NUL-separated
(``len:title\\x00len:body``) so no concatenation collision is possible (title
``"ab"`` + body ``"c"`` can never collide with title ``"a"`` + body ``"bc"``).
Source id, url and ingest/scrape time are deliberately excluded — content
similarity must depend only on content. The built-in ``hash()`` is never used
for any persisted identity (policy fingerprint, content hash, cluster id all
use SHA-256 with an explicit ``neardup-v1:`` prefix).

The algorithm version is **not** caller-supplied metadata. ``content_hash`` has
no ``version`` parameter — V1 only implements ``neardup-v1`` and the prefix is
always :data:`DEDUP_ALGORITHM_VERSION`. A caller cannot stamp a ``neardup-v2``,
``latest`` or any other version onto what is really the V1 digest. Adding a V2
requires a real implementation / explicit version dispatch and its own tests,
never a string argument.

Title & body similarity (deterministic text proxy, no LLM/embedding)
--------------------------------------------------------------------
Similarity is a purely deterministic character n-gram (shingle) Jaccard, not an
LLM and not a vector embedding. Character shingles are used instead of
whitespace tokenization because Chinese text is not space-delimited. Steps:

1. Collapse runs of whitespace, then slide a window of ``ngram_size`` (default
   3) characters to produce a shingle set. Text shorter than the window is a
   single whole-text shingle; empty text yields the empty set.
2. Jaccard = ``|A ∩ B| / |A ∪ B|``. Two empty sets are defined as ``0`` bps
   (fail-closed — never reported as identical).

Threshold quantization (integer basis points)
----------------------------------------------
All scores are quantized to integer basis points in ``[0, 10000]``
(``BASIS_POINTS_SCALE``; 10000 bps == 1.0 == identical). Thresholds are
integers too, so a boundary comparison is exact and never drifts across
platforms due to float epsilon.

Pair decision priority (``decide_pair``)
----------------------------------------
Evaluated top-down; the first matching rule wins:

1. **Eligibility** — if either side is not ``ELIGIBLE`` → not a duplicate
   (``NOT_CONSUMABLE``).
2. **Subject conflict** — if both sides have non-empty ``subject_keys`` and
   their intersection is empty → ``SUBJECT_KEY_CONFLICT`` (never merge, even on
   an exact hash match). This protects against merging same-template
   announcements from *different companies*.
3. **Content too short** — a body below ``min_body_chars`` is never
   near-duplicate-merged (``CONTENT_TOO_SHORT``), unless an exact hash matches.
4. **Exact hash match** → duplicate (``EXACT_CONTENT_MATCH``).
5. **Low-information title** — a title in ``low_information_titles`` (e.g.
   "公告", "通知") or shorter than ``min_title_chars`` may not drive clustering
   on its own. A shared *template body* under such a title is **not** enough
   (different issuers reuse boilerplate). A merge is allowed here only when a
   strong body is confirmed by a *reliable, matching subject clue* — both sides
   carry non-empty, intersecting ``subject_keys`` (fail-closed when a clue is
   missing on either side); otherwise → ``LOW_INFORMATION_TITLE``.
6. **Strong body + congruent title** — body ≥ ``body_similarity_threshold_bps``
   AND title ≥ ``title_congruence_floor_bps`` → duplicate
   (``STRONG_TITLE_AND_BODY``). This is the real repost signal: an authoritative
   body carried across sources with a lightly-rewritten but still-congruent
   title.
7. Otherwise not a duplicate, with a specific reason
   (``BODY_TEMPLATE_INSUFFICIENT`` when the body template matches but the title
   is below the floor — i.e. different topics sharing a boilerplate body;
   ``TITLE_ONLY_INSUFFICIENT`` / ``BELOW_THRESHOLD`` otherwise).

The dual title threshold — ``title_similarity_threshold_bps`` (7500, a title
strong enough to stand alone) and ``title_congruence_floor_bps`` (3000, a
minimum "same topic" floor) — is what lets a lightly-retitled repost cluster
while a shared boilerplate body across different subjects does not.

Different-company false-merge protection
-----------------------------------------
Three guards, in priority order: (a) an explicit ``subject_keys`` conflict
(both non-empty and disjoint) blocks the merge outright, even on an exact
content hash — and this protection is **always on** (``enforce_subject_conflict``
is fixed True in V1; constructing a policy with it disabled is rejected, so
there is no "valid but unsafe" policy); (b) a low-information title requires a
reliable, matching subject clue before a strong body may merge, so a shared
boilerplate body under "公告"/"通知" with no subject clue never merges; (c) for
high-information titles, a body-template match with a title below the
congruence floor is refused (``BODY_TEMPLATE_INSUFFICIENT``). The evaluation set
enforces a strict ``FP == 0`` on the different-company cases.

Clustering (``cluster_contents``)
---------------------------------
Input identity: every candidate's ``content_id`` must be unique within a single
call. A repeated ``content_id`` — including the same object passed twice, and
even when one collider would later be dropped by point-in-time or eligibility —
is rejected fail-closed *before* any filtering or clustering, because it makes
cluster identity, master selection and downstream evidence attribution
ambiguous.

Complete-linkage grouping: a candidate joins a cluster only if it is a pairwise
duplicate of *every* existing member. This prevents chain-bridging on a real
transitive chain — when A~B and B~C are both duplicates yet A≁C, A and C must
never be pulled into one cluster (character n-gram Jaccard is not a metric, so
such chains genuinely occur). ``EMPTY_CONTENT`` records are
kept as their own singletons and never merged; ``NOT_CONSUMABLE`` records are
excluded entirely. Output clusters are sorted by ``master_content_id`` so the
result is independent of input order.

Master record selection (``select_master``)
--------------------------------------------
Deterministic and independent of input order, wall-clock time or randomness:
earliest ``available_time`` wins (``EARLIEST_AVAILABLE_TIME``); ties are broken
by lexicographic ``content_id`` (``CONTENT_ID_TIE_BREAK``). A one-member
cluster records ``SOLE_MEMBER``.

Point-in-time semantics
-----------------------
``cluster_contents`` **requires** an explicit ``decision_time`` — a pure domain
function has no trustworthy wall clock, and defaulting to "now" or "everything"
would leak future-available content into a historical decision. Only records
with ``available_time <= decision_time`` participate (equality is visible), so a
cluster is reconstructed exactly as it would have looked at that instant. There
is no implicit "cluster everything" path. All timestamps are timezone-aware
UTC; naive datetimes are rejected, and the same instant in any timezone yields
the same result.

Version namespace consistency
-----------------------------
``content_hash``, ``DedupPolicy.fingerprint`` and ``cluster_identity`` all share
the same ``neardup-v1:`` version prefix. V1 implements exactly one algorithm
generation, so a ``DedupPolicy`` whose ``version`` is not
``DEDUP_ALGORITHM_VERSION`` is rejected — this prevents an inconsistent identity
where the policy fingerprint claims one version while the cluster id runs
another. The public identity helpers cannot be used to bypass that gate:
``content_hash`` takes no ``version`` argument, and ``cluster_identity`` takes a
validated ``DedupPolicy`` (never a bare fingerprint string), deriving both the
prefix and the fingerprint from the policy. Bumping ``DEDUP_ALGORITHM_VERSION``
is the only sanctioned way to change semantics.

Cluster identity (``cluster_identity``)
---------------------------------------
A version-prefixed SHA-256 over the *sorted* member content ids plus the policy
fingerprint, so the same member set under the same policy always yields the
same id regardless of input order, and two different policies never collide on
the same members. The signature is ``cluster_identity(member_content_ids, *,
policy)``: it requires a validated ``DedupPolicy`` and calls
``policy.fingerprint()`` itself. A caller cannot inject a forged
``policy_fingerprint`` string, and the version prefix comes from
``policy.version`` (already constrained to ``DEDUP_ALGORITHM_VERSION``).

Evaluation set (``build_evaluation_set`` / ``evaluate_labeled_set``)
--------------------------------------------------------------------
A synthetic, de-identified labeled set with stable ``case_id`` values and
``duplicate`` / ``non-duplicate`` labels; it contains no production news,
private data or unauthorized content. The set has its own identity —
``EVALUATION_SET_VERSION`` plus a deterministic ``evaluation_set_fingerprint``
(version-prefixed SHA-256 over the sorted cases' ids, decision-relevant input
fields and labels; never the built-in ``hash()``) — so any change to a case
input, a label, an id or the set version changes the fingerprint.
``evaluate_labeled_set`` produces a confusion matrix (TP/FP/TN/FN) plus
precision and recall in basis points (a zero denominator returns 0), bound to
*both* the ``policy_fingerprint`` and the evaluation-set identity. The set
covers exact/near duplicates, cross-source reposts, template announcements from
the same and different companies, low-information titles, short/empty text and a
conflicting-subject exact-content counterexample; the different-company cases
must contribute zero false positives.

Explicit non-goals (V1)
-----------------------
No LLM, no embedding, no vector database, no online service, no network call.
No entity recognition / security parsing / company disambiguation (P3-N04). No
MarketEvent, event extraction, hotspot aggregation, storage, API or UI.
Original records are never deleted or physically merged — deduplication is an
overlay only.
"""

from __future__ import annotations

from event_core.dedup.engine import cluster_contents, decide_pair, select_master
from event_core.dedup.evaluation import (
    EVALUATION_SET_VERSION,
    EvaluationCase,
    EvaluationResult,
    build_evaluation_set,
    evaluate_labeled_set,
    evaluation_set_fingerprint,
)
from event_core.dedup.models import (
    BASIS_POINTS_SCALE,
    DEDUP_ALGORITHM_VERSION,
    ClusterMember,
    ContentCluster,
    DecisionReason,
    DedupInput,
    DedupPolicy,
    Eligibility,
    MasterReason,
    PairDecision,
    SimilaritySignals,
    cluster_identity,
    content_hash,
)
from event_core.dedup.similarity import (
    body_similarity_bps,
    jaccard_bps,
    ngram_shingles,
    title_similarity_bps,
)

__all__ = [
    "BASIS_POINTS_SCALE",
    "DEDUP_ALGORITHM_VERSION",
    "EVALUATION_SET_VERSION",
    "ClusterMember",
    "ContentCluster",
    "DecisionReason",
    "DedupInput",
    "DedupPolicy",
    "Eligibility",
    "EvaluationCase",
    "EvaluationResult",
    "MasterReason",
    "PairDecision",
    "SimilaritySignals",
    "body_similarity_bps",
    "build_evaluation_set",
    "cluster_contents",
    "cluster_identity",
    "content_hash",
    "decide_pair",
    "evaluate_labeled_set",
    "evaluation_set_fingerprint",
    "jaccard_bps",
    "ngram_shingles",
    "select_master",
    "title_similarity_bps",
]
