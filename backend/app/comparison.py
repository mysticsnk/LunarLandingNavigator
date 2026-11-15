"""Comparison service interface module."""

from app.astronomy.comparison import (
    EARTH_VISIBLE_WEIGHT,
    GOLDEN_WEIGHT,
    MAX_SCENARIOS,
    MIN_SCENARIOS,
    RANKING_VERSION,
    SCORE_PRECISION,
    SUNLIT_WEIGHT,
    ScenarioEvaluationInput,
    build_recommendation_reason,
    calculate_v1_score,
    evaluate_comparison,
    evaluate_scenarios,
    rank_scenarios,
    validate_summary_metrics,
)
from app.results import ComparisonResult, RankedScenario

__all__ = [
    "ComparisonResult",
    "EARTH_VISIBLE_WEIGHT",
    "GOLDEN_WEIGHT",
    "MAX_SCENARIOS",
    "MIN_SCENARIOS",
    "RANKING_VERSION",
    "RankedScenario",
    "SCORE_PRECISION",
    "SUNLIT_WEIGHT",
    "ScenarioEvaluationInput",
    "build_recommendation_reason",
    "calculate_v1_score",
    "evaluate_comparison",
    "evaluate_scenarios",
    "rank_scenarios",
    "validate_summary_metrics",
]
