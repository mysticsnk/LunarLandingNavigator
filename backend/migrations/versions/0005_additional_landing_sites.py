"""Add additional landing sites for CLPS, International, and Artemis missions.

Revision ID: 0005_additional_landing_sites
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_additional_landing_sites"
down_revision = "0004_stage5_comparison_jobs"
branch_labels = None
depends_on = None

ADDITIONAL_SITES = [
    # CLPS & Commercial
    {
        "id": "im-1-odysseus",
        "name": "Intuitive Machines IM-1 (Odysseus)",
        "category": "clps",
        "latitude": -80.13,
        "longitude": 1.44,
        "description": (
            "First commercial CLPS soft landing, near Malapert A in the lunar south polar region."
        ),
        "source_url": "https://www.nasa.gov/commercial-lunar-payload-services/",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    {
        "id": "im-2-athena",
        "name": "Intuitive Machines IM-2 (Athena)",
        "category": "clps",
        "latitude": -84.79,
        "longitude": -29.20,
        "description": (
            "Targeted CLPS mission carrying the PRIME-1 polar ice drill near "
            "Shackleton Connecting Ridge."
        ),
        "source_url": "https://www.nasa.gov/commercial-lunar-payload-services/",
        "quickmap_url": None,
        "terrain_region_id": "shackleton_connecting_ridge",
    },
    {
        "id": "griffin-mission-1",
        "name": "Astrobotic Griffin Mission 1",
        "category": "clps",
        "latitude": -85.40,
        "longitude": 31.70,
        "description": (
            "Targeted CLPS lunar south polar delivery near Mons Mouton and the Nobile region."
        ),
        "source_url": "https://www.nasa.gov/commercial-lunar-payload-services/",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    {
        "id": "blue-ghost-1",
        "name": "Firefly Blue Ghost Mission 1",
        "category": "clps",
        "latitude": 18.56,
        "longitude": 61.81,
        "description": "Commercial payload mission destined for Mare Crisium lunar basin.",
        "source_url": "https://www.nasa.gov/commercial-lunar-payload-services/",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    {
        "id": "hakuto-r-m1",
        "name": "ispace HAKUTO-R Mission 1",
        "category": "clps",
        "latitude": 47.58,
        "longitude": 44.46,
        "description": "Commercial lunar exploration landing site in Atlas crater.",
        "source_url": "https://ispace-inc.com/",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    # International missions
    {
        "id": "chandrayaan-3",
        "name": "Chandrayaan-3 (Shiv Shakti Point)",
        "category": "international",
        "latitude": -69.373,
        "longitude": 32.319,
        "description": "ISRO lander and Pragyan rover southern high-latitude landing site.",
        "source_url": "https://www.isro.gov.in/Chandrayaan3.html",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    {
        "id": "change-4",
        "name": "Chang'e 4 (Yutu-2)",
        "category": "international",
        "latitude": -45.457,
        "longitude": 177.589,
        "description": "First historic soft landing on the lunar far side in Von Kármán crater.",
        "source_url": "http://www.cnsa.gov.cn/",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    {
        "id": "change-5",
        "name": "Chang'e 5",
        "category": "international",
        "latitude": 43.058,
        "longitude": -51.916,
        "description": (
            "CNSA lunar sample return mission site in Northern Oceanus "
            "Procellarum near Mons Rümker."
        ),
        "source_url": "http://www.cnsa.gov.cn/",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    {
        "id": "change-6",
        "name": "Chang'e 6",
        "category": "international",
        "latitude": -41.625,
        "longitude": -153.985,
        "description": (
            "Historic lunar far-side sample return mission site in the southern Apollo basin."
        ),
        "source_url": "http://www.cnsa.gov.cn/",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    {
        "id": "slim-shioli",
        "name": "SLIM (Smart Lander - JAXA)",
        "category": "international",
        "latitude": -13.316,
        "longitude": 25.251,
        "description": "JAXA pinpoint lunar landing mission site inside Shioli crater.",
        "source_url": "https://www.isas.jaxa.jp/en/missions/spacecraft/current/slim.html",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    {
        "id": "luna-24",
        "name": "Luna 24",
        "category": "international",
        "latitude": 12.714,
        "longitude": 62.213,
        "description": (
            "Soviet Luna sample return spacecraft touchdown in southeastern Mare Crisium."
        ),
        "source_url": "https://nssdc.gsfc.nasa.gov/planetary/lunar/lunar_sites.html",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    # Additional Artemis Candidate Sites
    {
        "id": "peak-near-shackleton",
        "name": "Peak Near Shackleton",
        "category": "artemis",
        "latitude": -89.66,
        "longitude": 125.0,
        "description": (
            "Artemis candidate landing region on the prominent ridge near Shackleton crater."
        ),
        "source_url": "https://pgda.gsfc.nasa.gov/products/78",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    {
        "id": "haworth-crater-rim",
        "name": "Haworth Crater Rim",
        "category": "artemis",
        "latitude": -87.50,
        "longitude": -15.0,
        "description": (
            "Artemis candidate landing region along the rim of permanently shadowed Haworth crater."
        ),
        "source_url": "https://pgda.gsfc.nasa.gov/products/78",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
    {
        "id": "nobile-rim-1",
        "name": "Nobile Rim 1",
        "category": "artemis",
        "latitude": -85.20,
        "longitude": 36.10,
        "description": "Artemis candidate landing region along the northern rim of Nobile crater.",
        "source_url": "https://pgda.gsfc.nasa.gov/products/78",
        "quickmap_url": None,
        "terrain_region_id": None,
    },
]


def upgrade():
    sites_table = sa.table(
        "sites",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("latitude", sa.Float),
        sa.column("longitude", sa.Float),
        sa.column("description", sa.String),
        sa.column("source_url", sa.String),
        sa.column("quickmap_url", sa.String),
        sa.column("terrain_region_id", sa.String),
    )
    bind = op.get_bind()
    for site in ADDITIONAL_SITES:
        bind.execute(
            postgresql.insert(sites_table)
            .values(**site)
            .on_conflict_do_nothing(index_elements=["id"])
        )


def downgrade():
    bind = op.get_bind()
    ids = [site["id"] for site in ADDITIONAL_SITES]
    bind.execute(
        sa.text("DELETE FROM sites WHERE id = ANY(:ids)"),
        {"ids": ids},
    )
