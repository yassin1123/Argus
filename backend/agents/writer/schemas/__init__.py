"""Writer schema registry — Phase 2 / Week 7 / Day 1.

Per-mode Pydantic payloads the writer agent validates against. The
``get_writer_schema(mode_name)`` lookup returns the right class for
each consulting mode; built-in modes share ``GeneralReportPayload``
today, ``m_and_a_diligence`` ships with its own bespoke schema.
"""

from ._base import (  # noqa: F401 — public re-exports
    ExecutiveInsightItem,
    KeyRiskStructuredItem,
    SourceItem,
    WriterReportBase,
)
from ._general import GeneralReportPayload  # noqa: F401
from ._m_and_a import (  # noqa: F401
    ComparableTransaction,
    DealStructureImplications,
    EBITDATrajectory,
    FinancialProfile,
    GeographyExposure,
    InitiativeBlock,
    IntegrationPlan,
    MAndADiligenceReportPayload,
    MarginProfile,
    NPVRange,
    RevenueTrajectory,
    RiskAssessment,
    Segment,
    Synergy,
    SynergyEstimate,
    TargetOverview,
    TrajectoryPoint,
    ValuationPoint,
    ValuationRange,
)
from ._registry import _SCHEMA_REGISTRY, get_writer_schema  # noqa: F401
from .frameworks import (  # noqa: F401 — W8/D3 framework payloads
    ForceAssessment,
    FrameworksPayload,
    PortersFiveForcesAnalysis,
    TwoByTwoItem,
    TwoByTwoMatrix,
    ValueChainActivity,
    ValueChainAnalysis,
)
