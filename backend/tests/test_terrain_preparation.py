"""Deterministic integrity tests for the terrain source acquisition tool."""

from __future__ import annotations

import hashlib
import io
import json

import pytest

from tools.prepare_terrain import (
    REPOSITORY_ROOT,
    TerrainProduct,
    download_file,
    external_path,
    verify_file,
)


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, *, status: int = 200, headers: dict | None = None):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Length": str(len(body)), **(headers or {})}


def tiny_product() -> TerrainProduct:
    return TerrainProduct(
        "fixture.tif",
        "controlled fixture",
        "test-v1",
        "https://pgda.gsfc.nasa.gov/fixture.tif",
        "https://pgda.gsfc.nasa.gov/products/test",
        8,
        1,
        1,
        1.0,
        b"II*\x00",
        "one-pixel controlled fixture",
        None,
    )


def test_source_file_verification_records_checksum_and_readiness_boundary(tmp_path):
    source = tmp_path / "fixture.tif"
    source.write_bytes(b"II*\x00data")
    manifest = verify_file(tiny_product(), source)
    assert manifest["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert manifest["checksum_pinned"] is False
    assert manifest["preparation_status"] == (
        "source_size_and_tiff_signature_checked_not_horizon_ready"
    )
    json.dumps(manifest)


@pytest.mark.parametrize("body", (b"II*\x00short", b"MM\x00*data"))
def test_source_file_verification_rejects_wrong_size_or_tiff_header(tmp_path, body):
    source = tmp_path / "fixture.tif"
    source.write_bytes(body)
    with pytest.raises(ValueError):
        verify_file(tiny_product(), source)


def test_source_file_verification_rejects_a_mismatched_pinned_checksum(tmp_path):
    source = tmp_path / "fixture.tif"
    source.write_bytes(b"II*\x00data")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_file(tiny_product(), source, "0" * 64)


def test_download_is_atomic_and_checks_length_and_checksum(tmp_path, monkeypatch):
    from tools import prepare_terrain

    body = b"II*\x00data"
    monkeypatch.setattr(prepare_terrain, "urlopen", lambda request, timeout: FakeResponse(body))
    target = tmp_path / "external" / "fixture.tif"
    manifest = download_file(
        tiny_product(),
        target,
        expected_sha256=hashlib.sha256(body).hexdigest(),
    )
    assert target.read_bytes() == body
    assert manifest["checksum_pinned"] is True
    assert not list(target.parent.glob("*.part"))


def test_large_download_requires_explicit_opt_in(tmp_path, monkeypatch):
    from tools import prepare_terrain

    body = b"II*\x00data"
    monkeypatch.setattr(prepare_terrain, "LARGE_FILE_THRESHOLD_BYTES", 4)
    monkeypatch.setattr(prepare_terrain, "urlopen", lambda request, timeout: FakeResponse(body))
    target = tmp_path / "external" / "fixture.tif"

    with pytest.raises(ValueError, match="allow-large-download"):
        download_file(tiny_product(), target)

    manifest = download_file(tiny_product(), target, allow_large_file=True)
    assert target.read_bytes() == body
    assert manifest["checksum_pinned"] is False


def test_large_download_resumes_only_a_matching_http_byte_range(tmp_path, monkeypatch):
    from tools import prepare_terrain

    body = b"II*\x00data"
    requests = []

    def ranged_response(request, timeout):
        requests.append(request)
        assert timeout == 30.0
        return FakeResponse(
            body[4:],
            status=206,
            headers={"Content-Range": f"bytes 4-7/{len(body)}"},
        )

    monkeypatch.setattr(prepare_terrain, "LARGE_FILE_THRESHOLD_BYTES", 4)
    monkeypatch.setattr(prepare_terrain, "urlopen", ranged_response)
    target = tmp_path / "external" / "fixture.tif"
    target.parent.mkdir()
    target.with_name(target.name + ".part").write_bytes(body[:4])

    manifest = download_file(tiny_product(), target, allow_large_file=True, resume=True)

    assert target.read_bytes() == body
    assert dict(requests[0].header_items())["Range"] == "bytes=4-"
    assert manifest["sha256"] == hashlib.sha256(body).hexdigest()
    assert not target.with_name(target.name + ".part").exists()


def test_resume_rejects_a_mismatched_content_range_and_preserves_partial(tmp_path, monkeypatch):
    from tools import prepare_terrain

    monkeypatch.setattr(
        prepare_terrain,
        "urlopen",
        lambda request, timeout: FakeResponse(
            b"data", status=206, headers={"Content-Range": "bytes 0-3/8"}
        ),
    )
    target = tmp_path / "external" / "fixture.tif"
    target.parent.mkdir()
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(b"II*\x00")

    with pytest.raises(ValueError, match="Content-Range"):
        download_file(tiny_product(), target, resume=True)

    assert partial.read_bytes() == b"II*\x00"
    assert not target.exists()


def test_terrain_file_path_cannot_be_created_in_repository(tmp_path):
    with pytest.raises(ValueError, match="outside the repository"):
        external_path(REPOSITORY_ROOT / "terrain.tif")
    assert external_path(tmp_path / "terrain.tif") == (tmp_path / "terrain.tif").resolve()
