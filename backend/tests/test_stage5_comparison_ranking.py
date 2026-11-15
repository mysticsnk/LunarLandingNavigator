"""Tests for Stage 5 comparison scoring, ranking, and recommendation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.astronomy.comparison import (
    EARTH_VISIBLE_WEIGHT,
    GOLDEN_WEIGHT,
    SUNLIT_WEIGHT,
    ScenarioEvaluationInput,
    build_recommendation_reason,
    calculate_v1_score,
    evaluate_comparison,
    rank_scenarios,
    validate_summary_metrics,
)
from app.results import (
    ComparisonResult,
    Meta,
    ResolvedSite,
    Source,
    TimelineSummary,
)


def _sample_site(name: str = "Test Site", lat: float = -89.44, lon: float = 222.1) -> ResolvedSite:
    norm_lon = ((lon + 180.0) % 360.0) - 180.0
    return ResolvedSite(
        site_id=None,
        name=name,
        latitude=lat,
        longitude=norm_lon,
        surface_elevation_m=0.0,
        observer_height_m=2.0,
    )


def _sample_meta() -> Meta:
    return Meta(
        model_version="test-model-v1",
        generated_at=datetime(2027, 7, 16, 0, 0, 0, tzinfo=UTC),
        data_status="fresh",
        horizon_mode="geometric",
        time_resolution_minutes=60,
        terrain_dataset_id=None,
        sources=[
            Source(
                name="Test Ephemeris Source",
                url="https://example.org/test-source",
                version="v1",
                fetched_at=datetime(2027, 7, 15, 0, 0, 0, tzinfo=UTC),
            )
        ],
    )


def _make_scenario(
    label: str,
    sunlit_pct: float,
    earth_visible_pct: float,
    golden_pct: float,
    longest_golden_window_hours: float,
    golden_hours: float | None = None,
    start_time: str = "2027-07-15T00:00:00Z",
    duration_days: int = 1,
) -> ScenarioEvaluationInput:
    dt_start = datetime.fromisoformat(start_time.replace("Z", "+00:00")).astimezone(UTC)
    dt_end = dt_start + timedelta(days=duration_days)
    total_hours = duration_days * 24.0
    calc_golden_hours = (
        golden_hours if golden_hours is not None else (golden_pct / 100.0) * total_hours
    )
    summary = TimelineSummary(
        sunlit_hours=(sunlit_pct / 100.0) * total_hours,
        sunlit_pct=sunlit_pct,
        earth_visible_hours=(earth_visible_pct / 100.0) * total_hours,
        earth_visible_pct=earth_visible_pct,
        golden_hours=calc_golden_hours,
        golden_pct=golden_pct,
        longest_golden_window_hours=longest_golden_window_hours,
        average_sun_elevation_deg=1.5,
        next_sunset_at=None,
        next_earthset_at=None,
    )
    return ScenarioEvaluationInput(
        label=label,
        site=_sample_site(f"Site {label}"),
        start_time=dt_start,
        end_time=dt_end,
        summary=summary,
    )


def test_required_score_verification_examples():
    """Verify exact formula examples from specification:

    A: sunlit=80, Earth=60, golden=50 -> score 65
    B: sunlit=60, Earth=80, golden=50 -> score 63
    C: sunlit=50, Earth=50, golden=0  -> score 35
    """
    summary_a = {
        "sunlit_pct": 80.0,
        "earth_visible_pct": 60.0,
        "golden_pct": 50.0,
        "longest_golden_window_hours": 12.0,
        "golden_hours": 12.0,
    }
    summary_b = {
        "sunlit_pct": 60.0,
        "earth_visible_pct": 80.0,
        "golden_pct": 50.0,
        "longest_golden_window_hours": 12.0,
        "golden_hours": 12.0,
    }
    summary_c = {
        "sunlit_pct": 50.0,
        "earth_visible_pct": 50.0,
        "golden_pct": 0.0,
        "longest_golden_window_hours": 0.0,
        "golden_hours": 0.0,
    }

    score_a = calculate_v1_score(summary_a)
    score_b = calculate_v1_score(summary_b)
    score_c = calculate_v1_score(summary_c)

    assert score_a == pytest.approx(65.0)
    assert score_b == pytest.approx(63.0)
    assert score_c == pytest.approx(35.0)


def test_all_zero_and_all_100_availability():
    """Boundary availability metrics must calculate exact 0.0 and 100.0."""
    zero_summary = {
        "sunlit_pct": 0.0,
        "earth_visible_pct": 0.0,
        "golden_pct": 0.0,
        "longest_golden_window_hours": 0.0,
        "golden_hours": 0.0,
    }
    assert calculate_v1_score(zero_summary) == 0.0

    full_summary = {
        "sunlit_pct": 100.0,
        "earth_visible_pct": 100.0,
        "golden_pct": 100.0,
        "longest_golden_window_hours": 24.0,
        "golden_hours": 24.0,
    }
    assert calculate_v1_score(full_summary) == 100.0


def test_different_weighted_scores_and_weights_constants():
    """Check that weights match 0.40, 0.30, 0.30."""
    assert SUNLIT_WEIGHT == 0.40
    assert EARTH_VISIBLE_WEIGHT == 0.30
    assert GOLDEN_WEIGHT == 0.30

    # 10% sunlight, 0% earth, 0% golden
    s1 = {
        "sunlit_pct": 10.0,
        "earth_visible_pct": 0.0,
        "golden_pct": 0.0,
        "longest_golden_window_hours": 0.0,
    }
    assert calculate_v1_score(s1) == pytest.approx(4.0)

    # 0% sunlight, 10% earth, 0% golden
    s2 = {
        "sunlit_pct": 0.0,
        "earth_visible_pct": 10.0,
        "golden_pct": 0.0,
        "longest_golden_window_hours": 0.0,
    }
    assert calculate_v1_score(s2) == pytest.approx(3.0)

    # 10% sunlight, 10% earth, 10% golden
    s3 = {
        "sunlit_pct": 10.0,
        "earth_visible_pct": 10.0,
        "golden_pct": 10.0,
        "longest_golden_window_hours": 2.4,
        "golden_hours": 2.4,
    }
    assert calculate_v1_score(s3) == pytest.approx(10.0)


def test_identical_scores_with_different_longest_windows():
    """Scenarios with identical score are ranked by longest golden window descending."""
    sc_short = _make_scenario(
        "Short Window",
        sunlit_pct=80.0,
        earth_visible_pct=60.0,
        golden_pct=50.0,
        longest_golden_window_hours=4.0,
    )
    sc_long = _make_scenario(
        "Long Window",
        sunlit_pct=80.0,
        earth_visible_pct=60.0,
        golden_pct=50.0,
        longest_golden_window_hours=10.0,
    )

    # Input order has Short first
    ranked, unrounded = rank_scenarios([sc_short, sc_long])
    assert len(ranked) == 2
    assert ranked[0].label == "Long Window"
    assert ranked[0].rank == 1
    assert ranked[1].label == "Short Window"
    assert ranked[1].rank == 2

    # Recommendation reason explicitly notes longer golden window
    reason = build_recommendation_reason(ranked[0], ranked[1], unrounded[0], unrounded[1])
    assert "longer continuous golden window" in reason
    assert "10.0h vs 4.0h" in reason


def test_complete_ties_preserving_input_order():
    """Scenarios with identical scores and longest windows preserve original request order."""
    sc_a = _make_scenario(
        "Scenario Alpha",
        sunlit_pct=70.0,
        earth_visible_pct=70.0,
        golden_pct=50.0,
        longest_golden_window_hours=8.0,
    )
    sc_b = _make_scenario(
        "Scenario Beta",
        sunlit_pct=70.0,
        earth_visible_pct=70.0,
        golden_pct=50.0,
        longest_golden_window_hours=8.0,
    )
    sc_c = _make_scenario(
        "Scenario Gamma",
        sunlit_pct=70.0,
        earth_visible_pct=70.0,
        golden_pct=50.0,
        longest_golden_window_hours=8.0,
    )

    ranked, unrounded = rank_scenarios([sc_a, sc_b, sc_c])
    assert [r.label for r in ranked] == ["Scenario Alpha", "Scenario Beta", "Scenario Gamma"]
    assert [r.rank for r in ranked] == [1, 2, 3]

    reason = build_recommendation_reason(ranked[0], ranked[1], unrounded[0], unrounded[1])
    assert "equivalent under the v1 ranking rules" in reason
    assert "original request order" in reason


def test_distinct_raw_scores_rounding_to_same_displayed_value():
    """Raw score must break ties before longest window, even if rounded display scores match."""
    # Scenario A has slightly higher raw score: 65.004 vs 65.001
    # 0.40 * 80.01 + 0.30 * 60 + 0.30 * 50 = 32.004 + 18 + 15 = 65.004 -> rounds to 65.00
    # Scenario B has 0.40 * 80.0025 + 0.30 * 60 + 0.30 * 50 = 32.001 + 18 + 15 = 65.001
    # Both round to 65.00 at 2 decimal places.
    # Scenario B has a longer golden window (10h vs 4h, both <= 12h total golden time).
    sc_a = _make_scenario(
        "Raw Score Winner",
        sunlit_pct=80.01,
        earth_visible_pct=60.0,
        golden_pct=50.0,
        longest_golden_window_hours=4.0,
    )
    sc_b = _make_scenario(
        "Longer Window Runner Up",
        sunlit_pct=80.0025,
        earth_visible_pct=60.0,
        golden_pct=50.0,
        longest_golden_window_hours=10.0,
    )

    ranked, _ = rank_scenarios([sc_b, sc_a])  # Input order has B first
    # sc_a wins because unrounded score is higher, despite B having longer window
    assert ranked[0].label == "Raw Score Winner"
    assert ranked[0].rank == 1
    assert ranked[0].score == 65.0  # displayed rounded value
    assert ranked[1].label == "Longer Window Runner Up"
    assert ranked[1].rank == 2
    assert ranked[1].score == 65.0  # displayed rounded value


@pytest.mark.parametrize(
    ("bad_summary", "err_substr"),
    [
        (
            {
                "sunlit_pct": 50.0,
                "earth_visible_pct": 60.0,
                "golden_pct": 65.0,
                "longest_golden_window_hours": 10.0,
            },
            "golden_pct",
        ),
        (
            {
                "sunlit_pct": 70.0,
                "earth_visible_pct": 40.0,
                "golden_pct": 50.0,
                "longest_golden_window_hours": 10.0,
            },
            "golden_pct",
        ),
        (
            {
                "sunlit_pct": 80.0,
                "earth_visible_pct": 80.0,
                "golden_pct": 50.0,
                "golden_hours": 12.0,
                "longest_golden_window_hours": 15.0,
            },
            "cannot exceed total golden_hours",
        ),
        (
            {
                "sunlit_pct": 80.0,
                "earth_visible_pct": 80.0,
                "golden_pct": 0.0,
                "longest_golden_window_hours": 2.0,
            },
            "longest_golden_window_hours must be 0",
        ),
        (
            {
                "sunlit_pct": 105.0,
                "earth_visible_pct": 50.0,
                "golden_pct": 20.0,
                "longest_golden_window_hours": 2.0,
            },
            "between 0.0 and 100.0",
        ),
        (
            {
                "sunlit_pct": -5.0,
                "earth_visible_pct": 50.0,
                "golden_pct": 0.0,
                "longest_golden_window_hours": 0.0,
            },
            "between 0.0 and 100.0",
        ),
        (
            {
                "sunlit_pct": float("nan"),
                "earth_visible_pct": 50.0,
                "golden_pct": 20.0,
                "longest_golden_window_hours": 2.0,
            },
            "must be finite",
        ),
        (
            {
                "sunlit_pct": 50.0,
                "earth_visible_pct": 50.0,
                "golden_pct": 20.0,
                "longest_golden_window_hours": -1.0,
            },
            "non-negative",
        ),
    ],
)
def test_invalid_summaries_raise_value_error(bad_summary, err_substr):
    """Validation must reject invalid summaries and not clamp them."""
    with pytest.raises(ValueError, match=err_substr):
        validate_summary_metrics(bad_summary)


def test_label_and_result_association():
    """Preserve scenario labels, site parameters, and time boundaries."""
    sc_a = _make_scenario(
        "Alpha Site",
        sunlit_pct=80.0,
        earth_visible_pct=60.0,
        golden_pct=50.0,
        longest_golden_window_hours=10.0,
    )
    sc_b = _make_scenario(
        "Beta Site",
        sunlit_pct=60.0,
        earth_visible_pct=80.0,
        golden_pct=50.0,
        longest_golden_window_hours=10.0,
    )

    result = evaluate_comparison([sc_a, sc_b], meta=_sample_meta())
    assert isinstance(result, ComparisonResult)
    assert result.ranking_version == "v1"
    assert result.recommended_label == "Alpha Site"
    assert len(result.ranked_scenarios) == 2

    winner = result.ranked_scenarios[0]
    assert winner.label == "Alpha Site"
    assert winner.rank == 1
    assert winner.score == 65.0
    assert winner.site.name == "Site Alpha Site"
    assert winner.start_time == sc_a.start_time
    assert winner.end_time == sc_a.end_time
    assert winner.summary.sunlit_pct == 80.0

    runner = result.ranked_scenarios[1]
    assert runner.label == "Beta Site"
    assert runner.rank == 2
    assert runner.score == 63.0


def test_duplicate_labels_rejected():
    """Duplicate scenario labels must be rejected."""
    sc1 = _make_scenario(
        "DupLabel",
        sunlit_pct=80.0,
        earth_visible_pct=60.0,
        golden_pct=50.0,
        longest_golden_window_hours=5.0,
    )
    sc2 = _make_scenario(
        "DupLabel",
        sunlit_pct=60.0,
        earth_visible_pct=60.0,
        golden_pct=50.0,
        longest_golden_window_hours=5.0,
    )

    with pytest.raises(ValueError, match="Scenario labels must be unique"):
        rank_scenarios([sc1, sc2])


def test_scenario_count_bounds():
    """Comparison requires between 2 and 6 scenarios."""
    sc = _make_scenario(
        "Only One",
        sunlit_pct=80.0,
        earth_visible_pct=60.0,
        golden_pct=50.0,
        longest_golden_window_hours=5.0,
    )
    with pytest.raises(ValueError, match="Comparison requires between 2 and 6"):
        rank_scenarios([sc])

    many = [
        _make_scenario(
            f"Sc {i}",
            sunlit_pct=50.0,
            earth_visible_pct=50.0,
            golden_pct=20.0,
            longest_golden_window_hours=1.0,
        )
        for i in range(7)
    ]
    with pytest.raises(ValueError, match="Comparison requires between 2 and 6"):
        rank_scenarios(many)


def test_recommendation_reason_has_no_safety_or_certification_claims():
    """Recommendation text must never claim NASA safety certification."""
    sc_a = _make_scenario(
        "A",
        sunlit_pct=80.0,
        earth_visible_pct=60.0,
        golden_pct=50.0,
        longest_golden_window_hours=10.0,
    )
    sc_b = _make_scenario(
        "B",
        sunlit_pct=60.0,
        earth_visible_pct=60.0,
        golden_pct=50.0,
        longest_golden_window_hours=10.0,
    )
    result = evaluate_comparison([sc_a, sc_b], meta=_sample_meta())

    reason_lower = result.recommendation_reason.lower()
    assert "safe" not in reason_lower
    assert "safety" not in reason_lower
    assert "certified" not in reason_lower
    assert "certification" not in reason_lower
    assert "nasa" not in reason_lower or "product" in reason_lower


def test_comparison_result_validates_openapi_example_fixture():
    """Verify that ComparisonResult can validate the official contract example."""
    repo_root = Path(__file__).resolve().parents[2]
    fixture_path = repo_root / "contracts" / "examples" / "comparison-result.json"
    with fixture_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    result = ComparisonResult.model_validate(data)
    assert result.ranking_version == "v1"
    assert result.recommended_label == "Synthetic A"
    assert len(result.ranked_scenarios) == 2
    assert result.ranked_scenarios[0].score == 67.5
    assert result.ranked_scenarios[1].score == 42.5
