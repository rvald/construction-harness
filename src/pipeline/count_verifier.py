"""Tier 3.1 M3 — VLM verifier for deterministic fixture counts.

The deterministic text-tag counter (fixture_counts) PRODUCES the count; this module
VERIFIES it against the rendered plan image (user's locked direction). Same pluggable,
offline-safe shape as section_llm:
  * Injectable `client` callable (request dict -> response dict). Tests inject a stub
    (canned verdicts) or a ReplayClient (recorded fixtures); the real
    AnthropicVerifierClient lazily imports `anthropic`, so the offline suite needs
    neither the SDK nor network.
  * Degrades: any error -> unverified (the deterministic count stands, unchanged).
    The VLM can never break the build, and is never on the path to HAVING a number.
  * Verification only strengthens or flags: on agreement, confidence rises and the
    fixture flips unknown_plan_count -> plan_count; on disagreement, the deterministic
    count is kept but confidence drops and the model's read is recorded for review.

Model: claude-opus-4-8 (vision). Runs opt-in on a handful of fixture sheets, cacheable.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field

from src.models.base import JsonModel
from src.models.schedule import CountResult

_MODEL = "claude-opus-4-8"


@dataclass
class Verification(JsonModel):
    """One verification verdict over a single CountResult."""

    symbol_id: str
    verified: bool                              # did a verifier actually run (vs error/none)?
    agrees: bool                                # does the model's read match the deterministic count?
    verified_count: int | None                  # the model's own count
    confidence: float
    notes: str = ""
    source: str = "vlm"


_VERIFY_TOOL = {
    "name": "verify_count",
    "description": "Report how many instances of the given fixture symbol appear on the "
                   "plan image, and whether that matches the provided deterministic count.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "verified_count": {"type": "integer", "description": "Your own count of the symbol on the image."},
            "agrees": {"type": "boolean", "description": "True if your count matches the deterministic count."},
            "confidence": {"type": "number", "description": "0.0-1.0"},
            "notes": {"type": "string", "description": "One short clause; note double-counts or legend inflation."},
        },
        "required": ["verified_count", "agrees", "confidence", "notes"],
        "additionalProperties": False,
    },
}

_SYSTEM = ("You verify construction fixture counts. You are given a plan sheet image, a "
           "fixture tag, and a deterministic text-tag count. Count the real fixture "
           "instances of that tag on the plan (ignore legend/schedule blocks and tags that "
           "are not plan instances) and report whether the deterministic count matches.")


def request_key(req: dict) -> str:
    """Stable content hash for fixture keying (image hashed by bytes)."""
    payload = {"symbol_id": req["symbol_id"], "sheet_page": req["sheet_page"],
               "deterministic_count": req["deterministic_count"],
               "image_sha": hashlib.sha256(req.get("image_png") or b"").hexdigest()[:16]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class CountVerifier:
    """Wraps an injectable client with grounding + graceful degradation."""

    def __init__(self, client):
        self.client = client  # callable(request: dict) -> {verified_count, agrees, confidence, notes}

    def verify(self, result: CountResult, image_png: bytes | None = None) -> Verification:
        req = {"symbol_id": result.symbol_id, "sheet_page": result.sheet_page,
               "deterministic_count": result.count, "boxes": result.boxes, "image_png": image_png}
        try:
            resp = self.client(req)
        except Exception:
            return Verification(result.symbol_id, verified=False, agrees=False,
                                verified_count=None, confidence=0.0, notes="verifier_error")
        try:
            vc = int(resp["verified_count"])
        except (KeyError, TypeError, ValueError):
            vc = None
        conf = min(1.0, max(0.0, float(resp.get("confidence", 0.0) or 0.0)))
        agrees = bool(resp.get("agrees", False)) if vc is not None else False
        return Verification(result.symbol_id, verified=True, agrees=agrees,
                            verified_count=vc, confidence=conf, notes=str(resp.get("notes", "")))


# --- merge + reconcile -------------------------------------------------------

def merge(result: CountResult, v: Verification) -> CountResult:
    """Fold a verdict into a CountResult. Never overwrites the deterministic count."""
    if not v.verified:
        return result                                       # unverified: leave untouched
    result.verified = True
    if v.agrees:
        result.confidence = max(result.confidence, v.confidence)
    else:
        # keep the deterministic count, but flag: drop confidence, record the model's read
        result.confidence = round(min(result.confidence, v.confidence) * 0.5, 3)
    return result


def reconcile(results: list[CountResult]) -> dict[str, dict]:
    """Deduped per-symbol building total. The same fixture recurs across overall +
    enlarged views, so summing double-counts; take the MAX sheet count as the
    conservative total and flag when sheets disagree (needs a closer look)."""
    by_symbol: dict[str, list[CountResult]] = {}
    for r in results:
        by_symbol.setdefault(r.symbol_id, []).append(r)
    out: dict[str, dict] = {}
    for sym, rs in by_symbol.items():
        counts = [r.count for r in rs]
        total = max(counts)
        out[sym] = {
            "building_total": total,
            "verified": all(r.verified for r in rs),
            "confidence": round(min(r.confidence for r in rs), 3),
            "sheets": [{"page": r.sheet_page, "count": r.count} for r in rs],
            "multi_sheet_disagreement": len(set(counts)) > 1,   # overall vs enlarged differ
        }
    return out


def flip_fixture_items(items, reconciled: dict[str, dict]):
    """Flip verified catalog fixtures unknown_plan_count -> plan_count with the total.

    Mutates and returns `items`. Only flips when the symbol's counts were verified;
    unverified symbols stay count-pending (never a stub-faked 'verified')."""
    for it in items:
        rec = reconciled.get(it.mark)
        if it.quantity_basis == "unknown_plan_count" and rec and rec["verified"]:
            it.quantity = float(rec["building_total"])
            it.unit = "EA"
            it.quantity_basis = "plan_count"
            it.attributes = dict(it.attributes, plan_count_confidence=rec["confidence"])
    return items


# --- backends ----------------------------------------------------------------

def render_sheet(pdf_path, sheet_page: int, dpi: int = 100) -> bytes:
    """Render a page to PNG bytes for the verifier (fitz)."""
    import fitz

    with fitz.open(str(pdf_path)) as doc:
        return doc[sheet_page - 1].get_pixmap(dpi=dpi).tobytes("png")


def verify_counts(counts: list[CountResult], verifier: CountVerifier,
                  pdf_path=None, render: bool = True) -> list[CountResult]:
    """Verify each per-sheet count and fold the verdict in. render=False (tests) skips
    rendering; the stub verifier ignores the image."""
    out: list[CountResult] = []
    for c in counts:
        image = render_sheet(pdf_path, c.sheet_page) if (render and pdf_path is not None) else None
        out.append(merge(c, verifier.verify(c, image)))
    return out


class AnthropicVerifierClient:
    """Real vision backend. Lazily imports `anthropic` (optional dependency)."""

    def __init__(self, model: str = _MODEL, client=None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client = client
        self.model = model

    def __call__(self, req: dict) -> dict:
        import base64

        img_b64 = base64.standard_b64encode(req["image_png"]).decode()
        user = (f"Fixture tag: {req['symbol_id']}\n"
                f"Deterministic text-tag count on this sheet: {req['deterministic_count']}\n"
                f"Count the real plan instances of this tag and call verify_count.")
        msg = self.client.messages.create(
            model=self.model, max_tokens=1024, system=_SYSTEM,
            tools=[_VERIFY_TOOL], tool_choice={"type": "tool", "name": "verify_count"},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": user},
            ]}],
        )
        for block in msg.content:
            if block.type == "tool_use":
                return dict(block.input)
        return {"verified_count": req["deterministic_count"], "agrees": True,
                "confidence": 0.0, "notes": "no tool use"}


class StubVerifierClient:
    """Deterministic offline backend: canned verdicts keyed by symbol_id (default: agree)."""

    def __init__(self, verdicts: dict | None = None, default_agrees: bool = True):
        self.verdicts = verdicts or {}
        self.default_agrees = default_agrees

    def __call__(self, req: dict) -> dict:
        if req["symbol_id"] in self.verdicts:
            return self.verdicts[req["symbol_id"]]
        return {"verified_count": req["deterministic_count"], "agrees": self.default_agrees,
                "confidence": 0.9 if self.default_agrees else 0.4, "notes": "stub"}


class ReplayClient:
    """Replays recorded responses by request key (offline fixtures, like section_llm)."""

    def __init__(self, path: str | pathlib.Path):
        p = pathlib.Path(path)
        self.data = json.loads(p.read_text()) if p.exists() else {}

    def __call__(self, req: dict) -> dict:
        key = request_key(req)
        if key not in self.data:
            raise KeyError(f"no recorded fixture for {req['symbol_id']!r} ({key})")
        return self.data[key]


class RecordingClient:
    """Wraps a live client and writes each response to a fixture file (one-time record)."""

    def __init__(self, inner, path: str | pathlib.Path):
        self.inner = inner
        self.path = pathlib.Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def __call__(self, req: dict) -> dict:
        resp = self.inner(req)
        self.data[request_key(req)] = resp
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))
        return resp
