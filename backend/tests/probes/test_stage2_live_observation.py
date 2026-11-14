import os

import pytest

from app.astronomy import HorizonsProvider, calculate_geometric_observation

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_LIVE_HORIZONS"),
    reason="Set TEST_LIVE_HORIZONS to run bounded live JPL Horizons control checks",
)


@pytest.mark.parametrize(
    ("latitude", "longitude", "sun", "earth"),
    [
        (
            -89.44,
            222.1,
            (177.278712, -1.088272),
            (142.714718, -6.178829),
        ),
        (
            -87.45,
            77.0,
            (322.365998, 1.490814),
            (288.064862, -4.947411),
        ),
    ],
    ids=("shackleton", "faustini"),
)
@pytest.mark.timeout(25)
def test_live_two_body_observation_matches_documented_control(latitude, longitude, sun, earth):
    point = calculate_geometric_observation(
        latitude=latitude,
        longitude=longitude,
        target_time="2027-07-15T12:00:00Z",
        observer_height_m=2.0,
        visibility_margin_deg=0.0,
        provider=HorizonsProvider(timeout=10.0, max_retries=0),
    )

    assert point.timestamp == "2027-07-15T12:00:00Z"
    assert (point.sun.azimuth_deg, point.sun.elevation_deg) == pytest.approx(sun, abs=1e-5)
    assert (point.earth.azimuth_deg, point.earth.elevation_deg) == pytest.approx(earth, abs=1e-5)
    assert [source.target for source in point.sources] == ["Sun", "Earth"]
    assert all(
        source.url.startswith("https://ssd.jpl.nasa.gov/api/horizons.api?")
        for source in point.sources
    )
