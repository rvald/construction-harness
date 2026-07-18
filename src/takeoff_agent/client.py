"""HTTP client for the takeoff ingestion service — the agent's ONE seam to the pipeline.

Every takeoff number the agent sees comes back through these calls. This talks to the
service's public HTTP contract only (no service internals, no pipeline imports), so the
agent cannot reach past the API. Endpoints wrapped — see service/api/ingestions.py + query.py:

  POST /v1/takeoff/ingestions                      submit a drawings PDF (async → job id)
  GET  /v1/takeoff/ingestions/{id}                 job status + manifest summary
  GET  /v1/takeoff/ingestions/{id}/summary         grounded rollups + reconciliation flags
  GET  /v1/takeoff/ingestions/{id}/items           paginated schedule items (+ filters)
  GET  /v1/takeoff/ingestions/{id}/fixture-counts  paginated fixture counts
  GET  /v1/takeoff/ingestions/{id}/room-areas      paginated room areas
  GET  /v1/takeoff/ingestions/{id}/artifact        the canonical report blob
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

_DEFAULT_BASE_URL = os.environ.get("TAKEOFF_API_BASE_URL", "http://localhost:8089")
_PREFIX = "/v1/takeoff/ingestions"


class TakeoffApiError(Exception):
    """A controlled failure from the takeoff API. Carries the service's error envelope
    ({code, message, request_id}) so the caller sees the same stable code the API returns."""

    def __init__(self, status_code: int, code: str, message: str, request_id: str | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"[{status_code} {code}] {message}")


class TakeoffClient:
    """Async client over the takeoff ingestion API. Owns one httpx.AsyncClient; use as an
    async context manager (`async with TakeoffClient() as c:`) or pass a client in."""

    def __init__(self, base_url: str = _DEFAULT_BASE_URL, *, timeout: float = 60.0,
                 client: httpx.AsyncClient | None = None):
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def __aenter__(self) -> "TakeoffClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # --- submit -------------------------------------------------------------

    async def submit(self, pdf_path: str | Path, *, config: dict | None = None,
                     idempotency_key: str | None = None) -> dict:
        """POST a drawings PDF. Returns {job_id, status}. 202 = new job, 200 = dedupe hit
        (both success). Raises TakeoffApiError on a 4xx/5xx envelope."""
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        data = {"config": json.dumps(config)} if config is not None else {}
        with open(pdf_path, "rb") as fh:
            files = {"drawings": (Path(pdf_path).name, fh, "application/pdf")}
            resp = await self._client.post(_PREFIX, files=files, data=data, headers=headers)
        return self._json(resp)

    # --- status + results ---------------------------------------------------

    async def status(self, job_id: str) -> dict:
        return self._json(await self._client.get(f"{_PREFIX}/{job_id}"))

    async def summary(self, job_id: str) -> dict:
        return self._json(await self._client.get(f"{_PREFIX}/{job_id}/summary"))

    async def items(self, job_id: str, *, schedule: str | None = None, mark: str | None = None,
                    quantity_basis: str | None = None, shape: str | None = None,
                    page: int = 1, page_size: int = 50) -> dict:
        params = _drop_none(schedule=schedule, mark=mark, quantity_basis=quantity_basis,
                            shape=shape, page=page, page_size=page_size)
        return self._json(await self._client.get(f"{_PREFIX}/{job_id}/items", params=params))

    async def fixture_counts(self, job_id: str, *, symbol_id: str | None = None,
                             verified: bool | None = None, min_confidence: float | None = None,
                             page: int = 1, page_size: int = 50) -> dict:
        params = _drop_none(symbol_id=symbol_id, verified=verified, min_confidence=min_confidence,
                            page=page, page_size=page_size)
        return self._json(await self._client.get(f"{_PREFIX}/{job_id}/fixture-counts", params=params))

    async def room_areas(self, job_id: str, *, room_number: str | None = None,
                         min_confidence: float | None = None,
                         page: int = 1, page_size: int = 50) -> dict:
        params = _drop_none(room_number=room_number, min_confidence=min_confidence,
                            page=page, page_size=page_size)
        return self._json(await self._client.get(f"{_PREFIX}/{job_id}/room-areas", params=params))

    async def artifact(self, job_id: str) -> dict:
        """The canonical report blob (application/json), returned as a dict."""
        return self._json(await self._client.get(f"{_PREFIX}/{job_id}/artifact"))

    # --- internals ----------------------------------------------------------

    def _json(self, resp: httpx.Response) -> dict:
        """Parsed JSON on success; the service's error envelope raised on failure."""
        if resp.is_success:
            return resp.json()
        code, message, request_id = "http_error", resp.text, None
        try:                                  # the service answers non-2xx with {"error": {...}}
            err = resp.json().get("error", {})
            code, message, request_id = err.get("code", code), err.get("message", message), err.get("request_id")
        except Exception:
            pass
        raise TakeoffApiError(resp.status_code, code, message, request_id)


def _drop_none(**kwargs) -> dict:
    """Query params with None values omitted, so unset filters aren't sent."""
    return {k: v for k, v in kwargs.items() if v is not None}
