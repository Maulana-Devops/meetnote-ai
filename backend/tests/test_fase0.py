"""Pengujian fondasi mutu Fase 0: request ID dan health diagnostics.

Test ini sengaja memakai provider mock yang sudah diatur di ``conftest.py``.
Tidak ada API key, jaringan, atau data pengguna yang dipakai.
"""

from fastapi.testclient import TestClient


def test_request_id_diterima_dan_dikembalikan(s2_client: TestClient) -> None:
    """Header X-Request-ID dari klien harus dipakai ulang di response/body."""
    response = s2_client.get(
        "/api/v1/health/diagnostics",
        headers={"X-Request-ID": "fase0-check-123"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-Request-ID"] == "fase0-check-123"
    assert response.json()["request_id"] == "fase0-check-123"


def test_request_id_dibuat_bila_tidak_dikirim(s2_client: TestClient) -> None:
    """Tanpa header, middleware membuat ID dan tetap mengembalikannya."""
    response = s2_client.get("/api/v1/health")
    assert response.status_code == 200, response.text
    request_id = response.headers.get("X-Request-ID")
    assert request_id
    assert request_id != "-"
