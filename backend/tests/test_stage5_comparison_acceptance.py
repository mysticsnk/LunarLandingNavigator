import json
from pathlib import Path

import pytest

from app.astronomy import normalize_longitude

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"


@pytest.mark.parametrize(
    ("sunlit_pct", "earth_visible_pct", "golden_pct", "expected_score"),
    [
        (75, 75, 50, 67.5),
        (80, 60, 40, 62.0),
        (50, 50, 25, 42.5),
        (60, 50, 30, 48.0),
        (50, 40, 20, 38.0),
        (60, 40, 25, 43.5),
        (50, 50, 50, 50.0),
    ],
)
def test_independent_v1_score_examples(sunlit_pct, earth_visible_pct, golden_pct, expected_score):
    actual = 0.40 * sunlit_pct + 0.30 * earth_visible_pct + 0.30 * golden_pct
    assert actual == pytest.approx(expected_score, abs=1e-10)


def test_rounded_display_tie_keeps_distinct_explicit_scores():
    score_a = 0.40 * 75 + 0.30 * 75 + 0.30 * 50
    score_b = 0.40 * 75.0347222222222 + 0.30 * 75 + 0.30 * 50

    assert score_a == pytest.approx(67.5)
    assert score_b == pytest.approx(67.5138888888889)
    assert round(score_a, 1) == round(score_b, 1)
    assert score_b > score_a


def test_longitude_forms_resolve_to_the_same_api_coordinate():
    assert normalize_longitude(222.1) == normalize_longitude(-137.9) == -137.9


def test_synthetic_comparison_summary_matches_timeline_fixture():
    comparison_request = json.loads(
        (EXAMPLES / "comparison-request.json").read_text(encoding="utf-8")
    )
    comparison_result = json.loads(
        (EXAMPLES / "comparison-result.json").read_text(encoding="utf-8")
    )
    timeline = json.loads(
        (EXAMPLES / "timeline-two-golden-windows.json").read_text(encoding="utf-8")
    )

    scenario = next(
        item for item in comparison_request["scenarios"] if item["label"] == "Synthetic A"
    )
    ranked = next(
        item for item in comparison_result["ranked_scenarios"] if item["label"] == scenario["label"]
    )
    assert normalize_longitude(scenario["site"]["longitude"]) == timeline["site"]["longitude"]
    assert scenario["site"]["latitude"] == timeline["site"]["latitude"]
    assert ranked["site"]["longitude"] == timeline["site"]["longitude"]
    assert ranked["start_time"] == timeline["start_time"]
    assert ranked["end_time"] == timeline["end_time"]
    assert comparison_request["duration_days"] == 1
    assert timeline["step_minutes"] == comparison_request["step_minutes"]
    assert timeline["meta"]["time_resolution_minutes"] == comparison_request["step_minutes"]
    assert timeline["meta"]["horizon_mode"] == comparison_request["horizon_mode"]
    assert timeline["site"]["observer_height_m"] == comparison_request["observer_height_m"]
    assert timeline["meta"]["model_version"] == ranked["provenance"]["model_version"]
    assert timeline["meta"]["terrain_dataset_id"] == ranked["provenance"]["terrain_dataset_id"]
    assert timeline["meta"]["terrain_dataset_id"] is None
    assert comparison_result["meta"]["terrain_dataset_id"] is None
    assert ranked["summary"] == timeline["summary"]
    assert ranked["score"] == pytest.approx(67.5)
