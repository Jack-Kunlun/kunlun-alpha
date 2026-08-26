# Generated from packages/contracts/schemas/. DO NOT EDIT BY HAND.

from ashare_contracts.backtest_regression import (
    BacktestRegressionArtifact as BacktestRegressionArtifact,
)
from ashare_contracts.backtest_regression import (
    BacktestRegressionBaseline as BacktestRegressionBaseline,
)
from ashare_contracts.backtest_regression import (
    BacktestRegressionComparison as BacktestRegressionComparison,
)
from ashare_contracts.backtest_regression import (
    BacktestRegressionComparison1 as BacktestRegressionComparison1,
)
from ashare_contracts.backtest_regression import (
    BacktestRegressionComparison2 as BacktestRegressionComparison2,
)
from ashare_contracts.backtest_regression import (
    BacktestRegressionComparison3 as BacktestRegressionComparison3,
)
from ashare_contracts.backtest_regression import (
    BacktestRegressionComparison4 as BacktestRegressionComparison4,
)
from ashare_contracts.backtest_regression import (
    BacktestRegressionComparison5 as BacktestRegressionComparison5,
)
from ashare_contracts.backtest_regression import BacktestRegressionDiff as BacktestRegressionDiff
from ashare_contracts.backtest_regression import (
    BacktestRegressionRunSummary as BacktestRegressionRunSummary,
)
from ashare_contracts.backtest_regression import BaselineApproval as BaselineApproval
from ashare_contracts.backtest_regression import Category as Category
from ashare_contracts.backtest_regression import CategoryCounts as CategoryCounts
from ashare_contracts.backtest_regression import CodeDigestEntry as CodeDigestEntry
from ashare_contracts.backtest_regression import CodeProvenance as CodeProvenance
from ashare_contracts.backtest_regression import ContentDigestReference as ContentDigestReference
from ashare_contracts.backtest_regression import Counts as Counts
from ashare_contracts.backtest_regression import DigestEntry as DigestEntry
from ashare_contracts.backtest_regression import (
    EvidenceIntegrityConfidence as EvidenceIntegrityConfidence,
)
from ashare_contracts.backtest_regression import FinalValuation as FinalValuation
from ashare_contracts.backtest_regression import Metrics as Metrics
from ashare_contracts.backtest_regression import MetricValue as MetricValue
from ashare_contracts.backtest_regression import Mode as Mode
from ashare_contracts.backtest_regression import Observation as Observation
from ashare_contracts.backtest_regression import (
    OpaqueExternalDigestReference as OpaqueExternalDigestReference,
)
from ashare_contracts.backtest_regression import Pnl as Pnl
from ashare_contracts.backtest_regression import PortfolioHistoryRef as PortfolioHistoryRef
from ashare_contracts.backtest_regression import RegressionInputs as RegressionInputs
from ashare_contracts.backtest_regression import RegressionManifest as RegressionManifest
from ashare_contracts.backtest_regression import RegressionProvenance as RegressionProvenance
from ashare_contracts.backtest_regression import RegressionResults as RegressionResults
from ashare_contracts.backtest_regression import RegressionTrust as RegressionTrust
from ashare_contracts.backtest_regression import RegressionVersions as RegressionVersions
from ashare_contracts.backtest_regression import RiskFreeObservation as RiskFreeObservation
from ashare_contracts.backtest_regression import Sha256 as Sha256
from ashare_contracts.backtest_regression import Status as Status
from ashare_contracts.backtest_regression import Status1 as Status1
from ashare_contracts.backtest_regression import Status2 as Status2
from ashare_contracts.backtest_regression import Status5 as Status5
from ashare_contracts.backtest_regression import ToolchainEvidence as ToolchainEvidence
from ashare_contracts.backtest_regression import TPlusOneInputs as TPlusOneInputs
from ashare_contracts.backtest_regression import TPlusOneObservation as TPlusOneObservation
from ashare_contracts.backtest_regression import TPlusOneResults as TPlusOneResults
from ashare_contracts.backtest_regression import ValuationLineage as ValuationLineage
from ashare_contracts.backtest_regression import ValuationLineageItem as ValuationLineageItem
from ashare_contracts.backtest_regression import ZeroCategoryCounts as ZeroCategoryCounts
from ashare_contracts.backtest_regression_semantics import validate_backtest_regression_comparison
from ashare_contracts.benchmark_series_semantics import is_canonical_benchmark_id
from ashare_contracts.calendar_holiday import Exchange as Exchange
from ashare_contracts.calendar_holiday import Holiday as Holiday
from ashare_contracts.calendar_holiday import Reason as Reason
from ashare_contracts.calendar_trading_day import Exchange as Exchange_1
from ashare_contracts.calendar_trading_day import Reason as Reason_1
from ashare_contracts.calendar_trading_day import TradingDay as TradingDay
from ashare_contracts.calendar_trading_session import Exchange as Exchange_2
from ashare_contracts.calendar_trading_session import Kind as Kind
from ashare_contracts.calendar_trading_session import TradingSession as TradingSession
from ashare_contracts.content_raw_content import ContentSource as ContentSource
from ashare_contracts.content_raw_content import ContentType as ContentType
from ashare_contracts.content_raw_content import FingerprintVersion as FingerprintVersion
from ashare_contracts.content_raw_content import LicenseMetadata as LicenseMetadata
from ashare_contracts.content_raw_content import RawContent as RawContent
from ashare_contracts.emotion_limit_event import EventType as EventType
from ashare_contracts.emotion_limit_event import Exchange as Exchange_3
from ashare_contracts.emotion_limit_event import LimitEvent as LimitEvent
from ashare_contracts.emotion_limit_pool_snapshot import LimitPoolSnapshot as LimitPoolSnapshot
from ashare_contracts.emotion_market_emotion_snapshot import EvidenceId as EvidenceId
from ashare_contracts.emotion_market_emotion_snapshot import LadderItem as LadderItem
from ashare_contracts.emotion_market_emotion_snapshot import (
    MarketEmotionSnapshot as MarketEmotionSnapshot,
)
from ashare_contracts.emotion_market_emotion_snapshot import SourceVersion as SourceVersion
from ashare_contracts.emotion_terminal_limit_pool_snapshot import AgeSeconds as AgeSeconds
from ashare_contracts.emotion_terminal_limit_pool_snapshot import EvidenceId as EvidenceId_1
from ashare_contracts.emotion_terminal_limit_pool_snapshot import Exchange as Exchange_4
from ashare_contracts.emotion_terminal_limit_pool_snapshot import Freshness as Freshness
from ashare_contracts.emotion_terminal_limit_pool_snapshot import (
    LimitPoolLadderLevel as LimitPoolLadderLevel,
)
from ashare_contracts.emotion_terminal_limit_pool_snapshot import (
    LimitPoolListingBoard as LimitPoolListingBoard,
)
from ashare_contracts.emotion_terminal_limit_pool_snapshot import LimitPoolSide as LimitPoolSide
from ashare_contracts.emotion_terminal_limit_pool_snapshot import LimitPoolState as LimitPoolState
from ashare_contracts.emotion_terminal_limit_pool_snapshot import (
    LimitPoolTerminalCompleteness as LimitPoolTerminalCompleteness,
)
from ashare_contracts.emotion_terminal_limit_pool_snapshot import (
    LimitPoolTerminalEntry as LimitPoolTerminalEntry,
)
from ashare_contracts.emotion_terminal_limit_pool_snapshot import (
    LimitPoolTerminalFreshnessStatus as LimitPoolTerminalFreshnessStatus,
)
from ashare_contracts.emotion_terminal_limit_pool_snapshot import (
    LimitPoolTerminalSnapshot as LimitPoolTerminalSnapshot,
)
from ashare_contracts.emotion_terminal_limit_pool_snapshot import MissingReason as MissingReason
from ashare_contracts.emotion_terminal_limit_pool_snapshot import Mode as Mode_1
from ashare_contracts.emotion_terminal_limit_pool_snapshot import (
    NullableVersion1 as NullableVersion1,
)
from ashare_contracts.emotion_terminal_limit_pool_snapshot import (
    PromotionRateBps as PromotionRateBps,
)
from ashare_contracts.emotion_terminal_limit_pool_snapshot import Revision as Revision
from ashare_contracts.emotion_terminal_limit_pool_snapshot import SourceVersion as SourceVersion_1
from ashare_contracts.emotion_terminal_market_overview import AgeSeconds as AgeSeconds_1
from ashare_contracts.emotion_terminal_market_overview import Completeness as Completeness
from ashare_contracts.emotion_terminal_market_overview import EvidenceId as EvidenceId_2
from ashare_contracts.emotion_terminal_market_overview import Freshness as Freshness_1
from ashare_contracts.emotion_terminal_market_overview import (
    MarketOverviewBreadthMetric as MarketOverviewBreadthMetric,
)
from ashare_contracts.emotion_terminal_market_overview import (
    MarketOverviewEmotionMetric as MarketOverviewEmotionMetric,
)
from ashare_contracts.emotion_terminal_market_overview import (
    MarketOverviewFreshnessStatus as MarketOverviewFreshnessStatus,
)
from ashare_contracts.emotion_terminal_market_overview import (
    MarketOverviewIndexMetric as MarketOverviewIndexMetric,
)
from ashare_contracts.emotion_terminal_market_overview import (
    MarketOverviewRiskMetric as MarketOverviewRiskMetric,
)
from ashare_contracts.emotion_terminal_market_overview import (
    MarketOverviewSnapshot as MarketOverviewSnapshot,
)
from ashare_contracts.emotion_terminal_market_overview import (
    MarketOverviewTurnoverMetric as MarketOverviewTurnoverMetric,
)
from ashare_contracts.emotion_terminal_market_overview import Mode as Mode_2
from ashare_contracts.emotion_terminal_market_overview import SourceVersion as SourceVersion_2
from ashare_contracts.emotion_terminal_market_overview import State as State
from ashare_contracts.event_event_feedback import Action as Action
from ashare_contracts.event_event_feedback import Correction as Correction
from ashare_contracts.event_event_feedback import EventFeedback as EventFeedback
from ashare_contracts.event_event_feedback import EventType as EventType_1
from ashare_contracts.event_event_feedback import EvidenceId as EvidenceId_3
from ashare_contracts.event_event_feedback import InstrumentId as InstrumentId
from ashare_contracts.event_event_feedback import ReasonCode as ReasonCode
from ashare_contracts.event_event_feedback import SectorId as SectorId
from ashare_contracts.event_event_feedback_submission import Action as Action_1
from ashare_contracts.event_event_feedback_submission import Correction as Correction_1
from ashare_contracts.event_event_feedback_submission import (
    EventFeedbackSubmission as EventFeedbackSubmission,
)
from ashare_contracts.event_event_feedback_submission import EventType as EventType_2
from ashare_contracts.event_event_feedback_submission import EvidenceId as EvidenceId_4
from ashare_contracts.event_event_feedback_submission import InstrumentId as InstrumentId_1
from ashare_contracts.event_event_feedback_submission import ReasonCode as ReasonCode_1
from ashare_contracts.event_event_feedback_submission import SectorId as SectorId_1
from ashare_contracts.event_hot_topic_snapshot import Components as Components
from ashare_contracts.event_hot_topic_snapshot import EventId as EventId
from ashare_contracts.event_hot_topic_snapshot import HotTopicSnapshot as HotTopicSnapshot
from ashare_contracts.event_hot_topic_snapshot import Lifecycle as Lifecycle
from ashare_contracts.event_market_event import EvidenceReference as EvidenceReference
from ashare_contracts.event_market_event import InstrumentId as InstrumentId_2
from ashare_contracts.event_market_event import MarketEvent as MarketEvent
from ashare_contracts.event_market_event import MarketEventType as MarketEventType
from ashare_contracts.event_market_event import ModelProvenance as ModelProvenance
from ashare_contracts.event_market_event import OutputSchemaVersion as OutputSchemaVersion
from ashare_contracts.event_market_event import ProducerType as ProducerType
from ashare_contracts.event_market_event import SchemaVersion as SchemaVersion
from ashare_contracts.event_market_event import SectorId as SectorId_2
from ashare_contracts.feature_feature_spec import AvailabilityPolicy as AvailabilityPolicy
from ashare_contracts.feature_feature_spec import Dependencies as Dependencies
from ashare_contracts.feature_feature_spec import Entity as Entity
from ashare_contracts.feature_feature_spec import FeatureSpec as FeatureSpec
from ashare_contracts.feature_feature_spec import Frequency as Frequency
from ashare_contracts.feature_feature_spec import SourceContracts as SourceContracts
from ashare_contracts.feature_feature_spec import ValueType as ValueType
from ashare_contracts.funds_benchmark_series_point import (
    BenchmarkSeriesPoint as BenchmarkSeriesPoint,
)
from ashare_contracts.funds_fund_nav import FundNav as FundNav
from ashare_contracts.funds_precious_metal_fund import AssetType as AssetType
from ashare_contracts.funds_precious_metal_fund import Exchange as Exchange_5
from ashare_contracts.funds_precious_metal_fund import PreciousMetalFund as PreciousMetalFund
from ashare_contracts.funds_precious_metal_fund import RecurringFee as RecurringFee
from ashare_contracts.funds_precious_metal_fund import ReviewStatus as ReviewStatus
from ashare_contracts.funds_precious_metal_fund import UnderlyingCommodity as UnderlyingCommodity
from ashare_contracts.health_status_v1 import HealthStatus as HealthStatus
from ashare_contracts.health_status_v1 import Status as Status_1
from ashare_contracts.instrument_board import Board as Board
from ashare_contracts.instrument_board import Exchange as Exchange_6
from ashare_contracts.instrument_board import Id as Id
from ashare_contracts.instrument_exchange import Code as Code
from ashare_contracts.instrument_exchange import Country as Country
from ashare_contracts.instrument_exchange import Currency as Currency
from ashare_contracts.instrument_exchange import Exchange as Exchange_7
from ashare_contracts.instrument_instrument import Board as Board_1
from ashare_contracts.instrument_instrument import Currency as Currency_1
from ashare_contracts.instrument_instrument import Exchange as Exchange_8
from ashare_contracts.instrument_instrument import Instrument as Instrument
from ashare_contracts.instrument_instrument import TradingStatus as TradingStatus
from ashare_contracts.instrument_instrument import Type as Type
from ashare_contracts.instrument_intelligence_detail import Access as Access
from ashare_contracts.instrument_intelligence_detail import Board as Board_2
from ashare_contracts.instrument_intelligence_detail import ClaimMeaning as ClaimMeaning
from ashare_contracts.instrument_intelligence_detail import Consistency as Consistency
from ashare_contracts.instrument_intelligence_detail import Currency as Currency_2
from ashare_contracts.instrument_intelligence_detail import DataMeaning as DataMeaning
from ashare_contracts.instrument_intelligence_detail import DataMeaning1 as DataMeaning1
from ashare_contracts.instrument_intelligence_detail import Emotion as Emotion
from ashare_contracts.instrument_intelligence_detail import EmotionSection as EmotionSection
from ashare_contracts.instrument_intelligence_detail import EventItem as EventItem
from ashare_contracts.instrument_intelligence_detail import EventSection as EventSection
from ashare_contracts.instrument_intelligence_detail import EvidenceId as EvidenceId_5
from ashare_contracts.instrument_intelligence_detail import EvidenceLink as EvidenceLink
from ashare_contracts.instrument_intelligence_detail import Exchange as Exchange_9
from ashare_contracts.instrument_intelligence_detail import FeatureItem as FeatureItem
from ashare_contracts.instrument_intelligence_detail import FeatureSection as FeatureSection
from ashare_contracts.instrument_intelligence_detail import Identity as Identity
from ashare_contracts.instrument_intelligence_detail import IdentitySection as IdentitySection
from ashare_contracts.instrument_intelligence_detail import (
    InstrumentIntelligenceDetail as InstrumentIntelligenceDetail,
)
from ashare_contracts.instrument_intelligence_detail import Kind as Kind_1
from ashare_contracts.instrument_intelligence_detail import KolClaimItem as KolClaimItem
from ashare_contracts.instrument_intelligence_detail import KolClaimSection as KolClaimSection
from ashare_contracts.instrument_intelligence_detail import MarketBar as MarketBar
from ashare_contracts.instrument_intelligence_detail import MarketSection as MarketSection
from ashare_contracts.instrument_intelligence_detail import Mode as Mode_3
from ashare_contracts.instrument_intelligence_detail import PostgresIsolation as PostgresIsolation
from ashare_contracts.instrument_intelligence_detail import ReviewStatus as ReviewStatus_1
from ashare_contracts.instrument_intelligence_detail import SchemaVersion as SchemaVersion_1
from ashare_contracts.instrument_intelligence_detail import SeatItem as SeatItem
from ashare_contracts.instrument_intelligence_detail import SeatSection as SeatSection
from ashare_contracts.instrument_intelligence_detail import SectionMetadata as SectionMetadata
from ashare_contracts.instrument_intelligence_detail import Sections as Sections
from ashare_contracts.instrument_intelligence_detail import SectorItem as SectorItem
from ashare_contracts.instrument_intelligence_detail import SectorSection as SectorSection
from ashare_contracts.instrument_intelligence_detail import SnapshotBoundary as SnapshotBoundary
from ashare_contracts.instrument_intelligence_detail import SourceVersion as SourceVersion_3
from ashare_contracts.instrument_intelligence_detail import Status as Status_2
from ashare_contracts.instrument_intelligence_detail import Store as Store
from ashare_contracts.instrument_intelligence_detail import TradingStatus as TradingStatus_1
from ashare_contracts.instrument_intelligence_detail import Type as Type_1
from ashare_contracts.instrument_trading_status import TradingStatus as TradingStatus_2
from ashare_contracts.instrument_trading_status import Value as Value
from ashare_contracts.kol_claim import KolClaim as KolClaim
from ashare_contracts.kol_claim import KolClaimAttribution as KolClaimAttribution
from ashare_contracts.kol_claim import KolClaimDirection as KolClaimDirection
from ashare_contracts.kol_claim import KolClaimEvidenceReference as KolClaimEvidenceReference
from ashare_contracts.kol_claim import KolClaimReviewStatus as KolClaimReviewStatus
from ashare_contracts.kol_claim import KolClaimSchemaVersion as KolClaimSchemaVersion
from ashare_contracts.kol_claim import KolClaimStatementKind as KolClaimStatementKind
from ashare_contracts.kol_claim import KolClaimUncertainty as KolClaimUncertainty
from ashare_contracts.kol_claim_extraction_candidate import AlgorithmVersion as AlgorithmVersion
from ashare_contracts.kol_claim_extraction_candidate import AnchorBase as AnchorBase
from ashare_contracts.kol_claim_extraction_candidate import AnchorType as AnchorType
from ashare_contracts.kol_claim_extraction_candidate import ClaimAction as ClaimAction
from ashare_contracts.kol_claim_extraction_candidate import ClaimAttribution as ClaimAttribution
from ashare_contracts.kol_claim_extraction_candidate import (
    ClaimConditionality as ClaimConditionality,
)
from ashare_contracts.kol_claim_extraction_candidate import ClaimPolarity as ClaimPolarity
from ashare_contracts.kol_claim_extraction_candidate import ClaimStatementKind as ClaimStatementKind
from ashare_contracts.kol_claim_extraction_candidate import ContentExactAnchor as ContentExactAnchor
from ashare_contracts.kol_claim_extraction_candidate import EventTimeStatus as EventTimeStatus
from ashare_contracts.kol_claim_extraction_candidate import EvidenceGrade as EvidenceGrade
from ashare_contracts.kol_claim_extraction_candidate import (
    EvidenceGradeVersion as EvidenceGradeVersion,
)
from ashare_contracts.kol_claim_extraction_candidate import (
    KolClaimExtractionCandidate as KolClaimExtractionCandidate,
)
from ashare_contracts.kol_claim_extraction_candidate import MediaExactAnchor as MediaExactAnchor
from ashare_contracts.kol_claim_extraction_candidate import ReviewStatus as ReviewStatus_2
from ashare_contracts.kol_claim_extraction_candidate import SchemaVersion as SchemaVersion_2
from ashare_contracts.kol_claim_extraction_candidate import SegmentIndex as SegmentIndex
from ashare_contracts.kol_claim_extraction_candidate import SemanticLabel as SemanticLabel
from ashare_contracts.kol_claim_review import Decision as Decision
from ashare_contracts.kol_claim_review import KolClaimReview as KolClaimReview
from ashare_contracts.kol_claim_review import ReviewMeaning as ReviewMeaning
from ashare_contracts.kol_claim_review import SchemaVersion as SchemaVersion_3
from ashare_contracts.kol_claim_review_submission import Decision as Decision_1
from ashare_contracts.kol_claim_review_submission import (
    KolClaimReviewSubmission as KolClaimReviewSubmission,
)
from ashare_contracts.kol_claim_review_submission import SchemaVersion as SchemaVersion_4
from ashare_contracts.kol_content import KolContent as KolContent
from ashare_contracts.kol_content import (
    KolContentFingerprintAlgorithmVersion as KolContentFingerprintAlgorithmVersion,
)
from ashare_contracts.kol_content import KolContentSchemaVersion as KolContentSchemaVersion
from ashare_contracts.kol_content import KolContentType as KolContentType
from ashare_contracts.kol_evidence import KolEvidence as KolEvidence
from ashare_contracts.kol_evidence import KolEvidenceGrade as KolEvidenceGrade
from ashare_contracts.kol_evidence import KolEvidenceGradeVersion as KolEvidenceGradeVersion
from ashare_contracts.kol_evidence import KolEvidenceLocatorType as KolEvidenceLocatorType
from ashare_contracts.kol_evidence import KolEvidenceSchemaVersion as KolEvidenceSchemaVersion
from ashare_contracts.kol_media_text_evidence import KolMediaTextEvidence as KolMediaTextEvidence
from ashare_contracts.kol_media_text_evidence import MediaBoundingBox as MediaBoundingBox
from ashare_contracts.kol_media_text_evidence import (
    MediaEvidenceProvenance as MediaEvidenceProvenance,
)
from ashare_contracts.kol_media_text_evidence import MediaKind as MediaKind
from ashare_contracts.kol_media_text_evidence import MediaManifest as MediaManifest
from ashare_contracts.kol_media_text_evidence import MediaProcessorKind as MediaProcessorKind
from ashare_contracts.kol_media_text_evidence import (
    MediaTextEvidenceSchemaVersion as MediaTextEvidenceSchemaVersion,
)
from ashare_contracts.kol_media_text_evidence import MediaTextSegment as MediaTextSegment
from ashare_contracts.kol_mention import KolMention as KolMention
from ashare_contracts.kol_mention import KolMentionSchemaVersion as KolMentionSchemaVersion
from ashare_contracts.kol_mention import KolMentionType as KolMentionType
from ashare_contracts.kol_position_claim import KolExecutionSemantics as KolExecutionSemantics
from ashare_contracts.kol_position_claim import KolPositionClaim as KolPositionClaim
from ashare_contracts.kol_position_claim import (
    KolPositionClaimSchemaVersion as KolPositionClaimSchemaVersion,
)
from ashare_contracts.kol_position_claim import KolPositionDirection as KolPositionDirection
from ashare_contracts.kol_position_claim import KolPositionReviewStatus as KolPositionReviewStatus
from ashare_contracts.kol_position_claim import KolPositionTimeHorizon as KolPositionTimeHorizon
from ashare_contracts.market_data_adjustment_factor import AdjustmentFactor as AdjustmentFactor
from ashare_contracts.market_data_adjustment_factor import Exchange as Exchange_10
from ashare_contracts.market_data_adjustment_factor import FactorType as FactorType
from ashare_contracts.market_data_bar import Bar as Bar
from ashare_contracts.market_data_bar import Exchange as Exchange_11
from ashare_contracts.market_data_bar import Interval as Interval
from ashare_contracts.market_data_bar import PriceType as PriceType
from ashare_contracts.market_data_bar import Session as Session
from ashare_contracts.market_data_corporate_action import ActionType as ActionType
from ashare_contracts.market_data_corporate_action import CorporateAction as CorporateAction
from ashare_contracts.market_data_corporate_action import Exchange as Exchange_12
from ashare_contracts.market_data_tick import Direction as Direction
from ashare_contracts.market_data_tick import Exchange as Exchange_13
from ashare_contracts.market_data_tick import Tick as Tick
from ashare_contracts.market_data_tick import TradeType as TradeType
from ashare_contracts.seat_alias import SeatAlias as SeatAlias
from ashare_contracts.seat_alias import SeatAliasSchemaVersion as SeatAliasSchemaVersion
from ashare_contracts.seat_alias import SeatAliasType as SeatAliasType
from ashare_contracts.seat_kol_workbench_snapshot import Alias as Alias
from ashare_contracts.seat_kol_workbench_snapshot import Claim as Claim
from ashare_contracts.seat_kol_workbench_snapshot import Cooccurrence as Cooccurrence
from ashare_contracts.seat_kol_workbench_snapshot import Direction as Direction_1
from ashare_contracts.seat_kol_workbench_snapshot import Evidence as Evidence
from ashare_contracts.seat_kol_workbench_snapshot import EvidenceId as EvidenceId_6
from ashare_contracts.seat_kol_workbench_snapshot import Kind as Kind_2
from ashare_contracts.seat_kol_workbench_snapshot import KolProfile as KolProfile
from ashare_contracts.seat_kol_workbench_snapshot import LeftEntityType as LeftEntityType
from ashare_contracts.seat_kol_workbench_snapshot import Metric as Metric
from ashare_contracts.seat_kol_workbench_snapshot import MetricName as MetricName
from ashare_contracts.seat_kol_workbench_snapshot import Mode as Mode_4
from ashare_contracts.seat_kol_workbench_snapshot import ReviewQueueItem as ReviewQueueItem
from ashare_contracts.seat_kol_workbench_snapshot import ReviewStatus as ReviewStatus_3
from ashare_contracts.seat_kol_workbench_snapshot import RightEntityType as RightEntityType
from ashare_contracts.seat_kol_workbench_snapshot import SeatKind as SeatKind
from ashare_contracts.seat_kol_workbench_snapshot import (
    SeatKolWorkbenchSnapshot as SeatKolWorkbenchSnapshot,
)
from ashare_contracts.seat_kol_workbench_snapshot import SeatProfile as SeatProfile
from ashare_contracts.seat_kol_workbench_snapshot import TimelineEntry as TimelineEntry
from ashare_contracts.seat_performance import SeatPerformance as SeatPerformance
from ashare_contracts.seat_performance import (
    SeatPerformanceSchemaVersion as SeatPerformanceSchemaVersion,
)
from ashare_contracts.seat_preference import SeatPreference as SeatPreference
from ashare_contracts.seat_preference import (
    SeatPreferenceSchemaVersion as SeatPreferenceSchemaVersion,
)
from ashare_contracts.seat_preference import StyleTag as StyleTag
from ashare_contracts.seat_seat_profile import PredecessorSeatId as PredecessorSeatId
from ashare_contracts.seat_seat_profile import SeatLineage as SeatLineage
from ashare_contracts.seat_seat_profile import SeatProfile as SeatProfile_1
from ashare_contracts.seat_seat_profile import (
    SeatProfileLineageRelation as SeatProfileLineageRelation,
)
from ashare_contracts.seat_seat_profile import SeatProfileSchemaVersion as SeatProfileSchemaVersion
from ashare_contracts.seat_seat_profile import (
    SeatProfileSeatIdAlgorithm as SeatProfileSeatIdAlgorithm,
)
from ashare_contracts.seat_seat_profile import SeatProfileSeatKind as SeatProfileSeatKind
from ashare_contracts.seat_seat_profile import SuccessorSeatId as SuccessorSeatId
from ashare_contracts.seat_trade import Currency as Currency_3
from ashare_contracts.seat_trade import SeatTrade as SeatTrade
from ashare_contracts.seat_trade import SeatTradeSchemaVersion as SeatTradeSchemaVersion
from ashare_contracts.sector_sector import Alias as Alias_1
from ashare_contracts.sector_sector import Kind as Kind_3
from ashare_contracts.sector_sector import Sector as Sector
from ashare_contracts.sector_sector_membership import SectorMembership as SectorMembership
from ashare_contracts.sector_sector_rotation_event import EventType as EventType_3
from ashare_contracts.sector_sector_rotation_event import EvidenceId as EvidenceId_7
from ashare_contracts.sector_sector_rotation_event import SectorRotationEvent as SectorRotationEvent
from ashare_contracts.sector_sector_rotation_event import SourceVersion as SourceVersion_4
from ashare_contracts.strategy_signal import Direction as Direction_2
from ashare_contracts.strategy_signal import EvidenceId as EvidenceId_8
from ashare_contracts.strategy_signal import Signal as Signal
from ashare_contracts.strategy_strategy_descriptor import (
    BooleanParameterSpec as BooleanParameterSpec,
)
from ashare_contracts.strategy_strategy_descriptor import (
    DecimalParameterSpec as DecimalParameterSpec,
)
from ashare_contracts.strategy_strategy_descriptor import (
    IntegerParameterSpec as IntegerParameterSpec,
)
from ashare_contracts.strategy_strategy_descriptor import RequiredFeature as RequiredFeature
from ashare_contracts.strategy_strategy_descriptor import StrategyDescriptor as StrategyDescriptor
from ashare_contracts.strategy_strategy_descriptor import StringParameterSpec as StringParameterSpec

__all__ = [
    "BacktestRegressionArtifact",
    "BacktestRegressionBaseline",
    "BacktestRegressionComparison",
    "BacktestRegressionComparison1",
    "BacktestRegressionComparison2",
    "BacktestRegressionComparison3",
    "BacktestRegressionComparison4",
    "BacktestRegressionComparison5",
    "BacktestRegressionDiff",
    "BacktestRegressionRunSummary",
    "BaselineApproval",
    "Category",
    "CategoryCounts",
    "CodeDigestEntry",
    "CodeProvenance",
    "ContentDigestReference",
    "Counts",
    "DigestEntry",
    "EvidenceIntegrityConfidence",
    "FinalValuation",
    "MetricValue",
    "Metrics",
    "Mode",
    "Observation",
    "OpaqueExternalDigestReference",
    "Pnl",
    "PortfolioHistoryRef",
    "RegressionInputs",
    "RegressionManifest",
    "RegressionProvenance",
    "RegressionResults",
    "RegressionTrust",
    "RegressionVersions",
    "RiskFreeObservation",
    "Sha256",
    "Status",
    "Status1",
    "Status2",
    "Status5",
    "TPlusOneInputs",
    "TPlusOneObservation",
    "TPlusOneResults",
    "ToolchainEvidence",
    "ValuationLineage",
    "ValuationLineageItem",
    "ZeroCategoryCounts",
    "Exchange",
    "Holiday",
    "Reason",
    "Exchange_1",
    "Reason_1",
    "TradingDay",
    "Exchange_2",
    "Kind",
    "TradingSession",
    "ContentSource",
    "ContentType",
    "FingerprintVersion",
    "LicenseMetadata",
    "RawContent",
    "EventType",
    "Exchange_3",
    "LimitEvent",
    "LimitPoolSnapshot",
    "EvidenceId",
    "LadderItem",
    "MarketEmotionSnapshot",
    "SourceVersion",
    "AgeSeconds",
    "EvidenceId_1",
    "Exchange_4",
    "Freshness",
    "LimitPoolLadderLevel",
    "LimitPoolListingBoard",
    "LimitPoolSide",
    "LimitPoolState",
    "LimitPoolTerminalCompleteness",
    "LimitPoolTerminalEntry",
    "LimitPoolTerminalFreshnessStatus",
    "LimitPoolTerminalSnapshot",
    "MissingReason",
    "Mode_1",
    "NullableVersion1",
    "PromotionRateBps",
    "Revision",
    "SourceVersion_1",
    "AgeSeconds_1",
    "Completeness",
    "EvidenceId_2",
    "Freshness_1",
    "MarketOverviewBreadthMetric",
    "MarketOverviewEmotionMetric",
    "MarketOverviewFreshnessStatus",
    "MarketOverviewIndexMetric",
    "MarketOverviewRiskMetric",
    "MarketOverviewSnapshot",
    "MarketOverviewTurnoverMetric",
    "Mode_2",
    "SourceVersion_2",
    "State",
    "Action",
    "Correction",
    "EventFeedback",
    "EventType_1",
    "EvidenceId_3",
    "InstrumentId",
    "ReasonCode",
    "SectorId",
    "Action_1",
    "Correction_1",
    "EventFeedbackSubmission",
    "EventType_2",
    "EvidenceId_4",
    "InstrumentId_1",
    "ReasonCode_1",
    "SectorId_1",
    "Components",
    "EventId",
    "HotTopicSnapshot",
    "Lifecycle",
    "EvidenceReference",
    "InstrumentId_2",
    "MarketEvent",
    "MarketEventType",
    "ModelProvenance",
    "OutputSchemaVersion",
    "ProducerType",
    "SchemaVersion",
    "SectorId_2",
    "AvailabilityPolicy",
    "Dependencies",
    "Entity",
    "FeatureSpec",
    "Frequency",
    "SourceContracts",
    "ValueType",
    "BenchmarkSeriesPoint",
    "FundNav",
    "AssetType",
    "Exchange_5",
    "PreciousMetalFund",
    "RecurringFee",
    "ReviewStatus",
    "UnderlyingCommodity",
    "HealthStatus",
    "Status_1",
    "Board",
    "Exchange_6",
    "Id",
    "Code",
    "Country",
    "Currency",
    "Exchange_7",
    "Board_1",
    "Currency_1",
    "Exchange_8",
    "Instrument",
    "TradingStatus",
    "Type",
    "Access",
    "Board_2",
    "ClaimMeaning",
    "Consistency",
    "Currency_2",
    "DataMeaning",
    "DataMeaning1",
    "Emotion",
    "EmotionSection",
    "EventItem",
    "EventSection",
    "EvidenceId_5",
    "EvidenceLink",
    "Exchange_9",
    "FeatureItem",
    "FeatureSection",
    "Identity",
    "IdentitySection",
    "InstrumentIntelligenceDetail",
    "Kind_1",
    "KolClaimItem",
    "KolClaimSection",
    "MarketBar",
    "MarketSection",
    "Mode_3",
    "PostgresIsolation",
    "ReviewStatus_1",
    "SchemaVersion_1",
    "SeatItem",
    "SeatSection",
    "SectionMetadata",
    "Sections",
    "SectorItem",
    "SectorSection",
    "SnapshotBoundary",
    "SourceVersion_3",
    "Status_2",
    "Store",
    "TradingStatus_1",
    "Type_1",
    "TradingStatus_2",
    "Value",
    "KolClaim",
    "KolClaimAttribution",
    "KolClaimDirection",
    "KolClaimEvidenceReference",
    "KolClaimReviewStatus",
    "KolClaimSchemaVersion",
    "KolClaimStatementKind",
    "KolClaimUncertainty",
    "AlgorithmVersion",
    "AnchorBase",
    "AnchorType",
    "ClaimAction",
    "ClaimAttribution",
    "ClaimConditionality",
    "ClaimPolarity",
    "ClaimStatementKind",
    "ContentExactAnchor",
    "EventTimeStatus",
    "EvidenceGrade",
    "EvidenceGradeVersion",
    "KolClaimExtractionCandidate",
    "MediaExactAnchor",
    "ReviewStatus_2",
    "SchemaVersion_2",
    "SegmentIndex",
    "SemanticLabel",
    "Decision",
    "KolClaimReview",
    "ReviewMeaning",
    "SchemaVersion_3",
    "Decision_1",
    "KolClaimReviewSubmission",
    "SchemaVersion_4",
    "KolContent",
    "KolContentFingerprintAlgorithmVersion",
    "KolContentSchemaVersion",
    "KolContentType",
    "KolEvidence",
    "KolEvidenceGrade",
    "KolEvidenceGradeVersion",
    "KolEvidenceLocatorType",
    "KolEvidenceSchemaVersion",
    "KolMediaTextEvidence",
    "MediaBoundingBox",
    "MediaEvidenceProvenance",
    "MediaKind",
    "MediaManifest",
    "MediaProcessorKind",
    "MediaTextEvidenceSchemaVersion",
    "MediaTextSegment",
    "KolMention",
    "KolMentionSchemaVersion",
    "KolMentionType",
    "KolExecutionSemantics",
    "KolPositionClaim",
    "KolPositionClaimSchemaVersion",
    "KolPositionDirection",
    "KolPositionReviewStatus",
    "KolPositionTimeHorizon",
    "AdjustmentFactor",
    "Exchange_10",
    "FactorType",
    "Bar",
    "Exchange_11",
    "Interval",
    "PriceType",
    "Session",
    "ActionType",
    "CorporateAction",
    "Exchange_12",
    "Direction",
    "Exchange_13",
    "Tick",
    "TradeType",
    "SeatAlias",
    "SeatAliasSchemaVersion",
    "SeatAliasType",
    "Alias",
    "Claim",
    "Cooccurrence",
    "Direction_1",
    "Evidence",
    "EvidenceId_6",
    "Kind_2",
    "KolProfile",
    "LeftEntityType",
    "Metric",
    "MetricName",
    "Mode_4",
    "ReviewQueueItem",
    "ReviewStatus_3",
    "RightEntityType",
    "SeatKind",
    "SeatKolWorkbenchSnapshot",
    "SeatProfile",
    "TimelineEntry",
    "SeatPerformance",
    "SeatPerformanceSchemaVersion",
    "SeatPreference",
    "SeatPreferenceSchemaVersion",
    "StyleTag",
    "PredecessorSeatId",
    "SeatLineage",
    "SeatProfile_1",
    "SeatProfileLineageRelation",
    "SeatProfileSchemaVersion",
    "SeatProfileSeatIdAlgorithm",
    "SeatProfileSeatKind",
    "SuccessorSeatId",
    "Currency_3",
    "SeatTrade",
    "SeatTradeSchemaVersion",
    "Alias_1",
    "Kind_3",
    "Sector",
    "SectorMembership",
    "EventType_3",
    "EvidenceId_7",
    "SectorRotationEvent",
    "SourceVersion_4",
    "Direction_2",
    "EvidenceId_8",
    "Signal",
    "BooleanParameterSpec",
    "DecimalParameterSpec",
    "IntegerParameterSpec",
    "RequiredFeature",
    "StrategyDescriptor",
    "StringParameterSpec",
    "is_canonical_benchmark_id",
    "validate_backtest_regression_comparison",
]
