"""Comparison evaluation and ranking service for lunar landing scenarios.

Implements the agreed v1 scoring formula:
score = 0.40 * sunlit_pct + 0.30 * earth_visible_pct + 0.30 * golden_pct
and deterministic ranking: unrounded score descending, longest continuous
golden window descending, then original request order.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.astronomy.timeline import (
    Summary as AstronomySummary,
)
from app.astronomy.timeline import (
    TimelineCalculationResult,
)
from app.results import (
    ComparisonResult,
    Meta,
    RankedScenario,
    ResolvedSite,
)
from app.results import (
    TimelineSummary as ResultSummary,
)

RANKING_VERSION = "v1"
SUNLIT_WEIGHT = 0.40
EARTH_VISIBLE_WEIGHT = 0.30
GOLDEN_WEIGHT = 0.30
MIN_SCENARIOS = 2
MAX_SCENARIOS = 6
SCORE_PRECISION = 2
_EPSILON = 1e-9

ScenarioSummary = ResultSummary | AstronomySummary


def _coerce_result_summary(summary: Any) -> ResultSummary:
    if isinstance(summary, ResultSummary):
        return summary
    if isinstance(summary, AstronomySummary):
        return ResultSummary.model_validate(summary.model_dump())
    if isinstance(summary, dict):
        return ResultSummary.model_validate(summary)
    if hasattr(summary, "model_dump"):
        return ResultSummary.model_validate(summary.model_dump())
    raise ValueError(f"Unsupported summary format: {type(summary)}")


class ScenarioEvaluationInput(BaseModel):
    """Input scenario representation for comparison evaluation."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    site: ResolvedSite
    start_time: AwareDatetime
    end_time: AwareDatetime
    summary: ScenarioSummary

    @classmethod
    def from_timeline(
        cls,
        label: str,
        timeline: TimelineCalculationResult | dict[str, Any],
        site: ResolvedSite | dict[str, Any],
    ) -> ScenarioEvaluationInput:
        """Create an evaluation input directly from a calculated timeline and resolved site."""
        if hasattr(timeline, "model_dump"):
            tl_dict = timeline.model_dump(mode="python")
        else:
            tl_dict = dict(timeline)
        start_time = tl_dict["start_time"]
        end_time = tl_dict["end_time"]
        summary = tl_dict["summary"]
        return cls(
            label=label,
            site=site if isinstance(site, ResolvedSite) else ResolvedSite.model_validate(site),
            start_time=datetime.fromisoformat(str(start_time).replace("Z", "+00:00")).astimezone(
                UTC
            ),
            end_time=datetime.fromisoformat(str(end_time).replace("Z", "+00:00")).astimezone(UTC),
            summary=(
                summary
                if isinstance(summary, ResultSummary | AstronomySummary)
                else _coerce_result_summary(summary)
            ),
        )


def _get_metric(summary: Any, key: str) -> Any:
    if hasattr(summary, key):
        return getattr(summary, key)
    if isinstance(summary, dict) and key in summary:
        return summary[key]
    return None


def validate_summary_metrics(summary: ScenarioSummary | dict[str, Any]) -> dict[str, float]:
    """Validate physical assumptions of summary metrics without silent clamping."""
    keys = ("sunlit_pct", "earth_visible_pct", "golden_pct", "longest_golden_window_hours")
    values: dict[str, float] = {}
    for key in keys:
        raw = _get_metric(summary, key)
        if raw is None:
            raise ValueError(f"Missing required summary metric: {key}")
        try:
            val = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Summary metric {key} must be a number, got {raw!r}") from exc
        if not math.isfinite(val):
            raise ValueError(f"Summary metric {key} must be finite, got {val}")
        values[key] = val

    for pct_key in ("sunlit_pct", "earth_visible_pct", "golden_pct"):
        if not (0.0 <= values[pct_key] <= 100.0):
            raise ValueError(f"{pct_key} must be between 0.0 and 100.0, got {values[pct_key]}")

    if values["longest_golden_window_hours"] < 0.0:
        raise ValueError(
            "longest_golden_window_hours must be non-negative, got "
            f"{values['longest_golden_window_hours']}"
        )

    # Golden windows require simultaneous sunlight and Earth visibility
    if values["golden_pct"] > values["sunlit_pct"] + 1e-5:
        raise ValueError(
            f"golden_pct ({values['golden_pct']}%) cannot exceed "
            f"sunlit_pct ({values['sunlit_pct']}%)"
        )
    if values["golden_pct"] > values["earth_visible_pct"] + 1e-5:
        raise ValueError(
            f"golden_pct ({values['golden_pct']}%) cannot exceed earth_visible_pct "
            f"({values['earth_visible_pct']}%)"
        )

    # A single continuous window cannot exceed total golden time
    golden_hours_raw = _get_metric(summary, "golden_hours")
    if golden_hours_raw is not None:
        golden_hours = float(golden_hours_raw)
        if not math.isfinite(golden_hours) or golden_hours < 0.0:
            raise ValueError(
                f"golden_hours must be a non-negative finite number, got {golden_hours}"
            )
        if values["longest_golden_window_hours"] > golden_hours + 1e-5:
            raise ValueError(
                f"longest_golden_window_hours ({values['longest_golden_window_hours']}) "
                f"cannot exceed total golden_hours ({golden_hours})"
            )
        values["golden_hours"] = golden_hours

    if values["golden_pct"] == 0.0 and values["longest_golden_window_hours"] > 1e-5:
        raise ValueError("longest_golden_window_hours must be 0 when golden availability is 0%")

    return values


def calculate_v1_score(summary: ScenarioSummary | dict[str, Any]) -> float:
    """Calculate exact unrounded v1 comparison product score."""
    validated = validate_summary_metrics(summary)
    return (
        SUNLIT_WEIGHT * validated["sunlit_pct"]
        + EARTH_VISIBLE_WEIGHT * validated["earth_visible_pct"]
        + GOLDEN_WEIGHT * validated["golden_pct"]
    )


def build_recommendation_reason(
    winner: RankedScenario,
    runner_up: RankedScenario,
    winner_unrounded: float,
    runner_unrounded: float,
) -> str:
    """Generate deterministic English explanation of the winning scenario."""
    diff = winner_unrounded - runner_unrounded
    if diff > _EPSILON:
        return (
            f"{winner.label} ranks first with the highest v1 product score of {winner.score:.2f} "
            f"(sunlit: {winner.summary.sunlit_pct:.1f}%, "
            f"Earth visible: {winner.summary.earth_visible_pct:.1f}%, "
            f"golden: {winner.summary.golden_pct:.1f}%), exceeding {runner_up.label} "
            f"(score {runner_up.score:.2f}) using agreed weights "
            "(40% sunlit, 30% Earth visible, 30% golden)."
        )

    longest_diff = (
        winner.summary.longest_golden_window_hours - runner_up.summary.longest_golden_window_hours
    )
    if longest_diff > _EPSILON:
        return (
            f"{winner.label} and {runner_up.label} have identical v1 product scores "
            f"({winner.score:.2f}), but {winner.label} ranks higher due to a longer "
            f"continuous golden window ({winner.summary.longest_golden_window_hours:.1f}h "
            f"vs {runner_up.summary.longest_golden_window_hours:.1f}h)."
        )

    return (
        f"{winner.label} and {runner_up.label} are equivalent under the v1 ranking rules "
        f"(identical score {winner.score:.2f} and longest golden window of "
        f"{winner.summary.longest_golden_window_hours:.1f}h); {winner.label} is recommended "
        "based on original request order."
    )


def rank_scenarios(
    scenarios: Sequence[ScenarioEvaluationInput | dict[str, Any]],
    *,
    precision: int | None = SCORE_PRECISION,
) -> tuple[list[RankedScenario], list[float]]:
    """Rank scenarios by unrounded score, longest golden window, and original order."""
    if len(scenarios) < MIN_SCENARIOS or len(scenarios) > MAX_SCENARIOS:
        raise ValueError(
            f"Comparison requires between {MIN_SCENARIOS} and {MAX_SCENARIOS} scenarios, "
            f"got {len(scenarios)}"
        )

    normalized: list[ScenarioEvaluationInput] = []
    labels_seen: set[str] = set()
    for item in scenarios:
        sc = (
            item
            if isinstance(item, ScenarioEvaluationInput)
            else ScenarioEvaluationInput.model_validate(item)
        )
        if sc.label in labels_seen:
            raise ValueError(f"Scenario labels must be unique, duplicated: {sc.label!r}")
        labels_seen.add(sc.label)
        normalized.append(sc)

    evaluated = []
    for original_index, sc in enumerate(normalized):
        unrounded = calculate_v1_score(sc.summary)
        longest_window = sc.summary.longest_golden_window_hours
        evaluated.append(
            {
                "original_index": original_index,
                "scenario": sc,
                "unrounded_score": unrounded,
                "longest_golden_window_hours": longest_window,
            }
        )

    # Sort descending by unrounded score, then longest window, then ascending original index
    evaluated.sort(
        key=lambda item: (
            -item["unrounded_score"],
            -item["longest_golden_window_hours"],
            item["original_index"],
        )
    )

    ranked: list[RankedScenario] = []
    unrounded_scores: list[float] = []
    for rank_idx, item in enumerate(evaluated, start=1):
        sc = item["scenario"]
        unrounded = item["unrounded_score"]
        unrounded_scores.append(unrounded)
        display_score = round(unrounded, precision) if precision is not None else unrounded
        ranked.append(
            RankedScenario(
                rank=rank_idx,
                label=sc.label,
                site=sc.site,
                start_time=sc.start_time,
                end_time=sc.end_time,
                score=display_score,
                summary=_coerce_result_summary(sc.summary),
            )
        )

    return ranked, unrounded_scores


def evaluate_scenarios(
    scenarios: Sequence[ScenarioEvaluationInput | dict[str, Any]],
    *,
    precision: int | None = SCORE_PRECISION,
) -> tuple[list[RankedScenario], str]:
    """Rank scenarios and produce the deterministic recommendation reason."""
    ranked, unrounded_scores = rank_scenarios(scenarios, precision=precision)
    reason = build_recommendation_reason(
        ranked[0],
        ranked[1],
        winner_unrounded=unrounded_scores[0],
        runner_unrounded=unrounded_scores[1],
    )
    return ranked, reason


def evaluate_comparison(
    scenarios: Sequence[ScenarioEvaluationInput | dict[str, Any]],
    meta: Meta | dict[str, Any],
    *,
    precision: int | None = SCORE_PRECISION,
) -> ComparisonResult:
    """Evaluate and rank scenarios, returning complete ComparisonResult."""
    ranked, reason = evaluate_scenarios(scenarios, precision=precision)
    meta_obj = meta if isinstance(meta, Meta) else Meta.model_validate(meta)
    return ComparisonResult(
        ranking_version=RANKING_VERSION,
        ranked_scenarios=ranked,
        recommended_label=ranked[0].label,
        recommendation_reason=reason,
        meta=meta_obj,
    )
