"""LLM backend for the semantic section resolver (B9, M4).

Resolves the low-confidence tail (codes the deterministic matcher couldn't derive:
empty/garbage expansions like AL, T; semantic gaps like WB rubber->resilient base)
by grounded multiple-choice over the division-filtered candidate sections.

Design (locked D1-D4):
  * Grounded: the model must pick a section number from the provided candidates or
    say 'none' (via a strict `select_section` tool); any out-of-candidate answer is
    rejected. No hallucinated section numbers reach the graph.
  * Pluggable + offline-safe: the matcher takes an injectable `client` callable
    (request dict -> response dict). Tests inject a ReplayClient backed by recorded
    fixtures (or a fake); the real AnthropicSectionClient lazily imports `anthropic`
    so core CI needs neither the SDK nor network.
  * Degrades: any error -> (None, 0.0) so the pipeline falls through to the seed
    override. The LLM can never break the build.

Model: claude-haiku-4-5 (cheap bounded classification). Runs on the distinct-code
set (~a handful per project), once, batchable and cacheable.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

_MODEL = "claude-haiku-4-5"

_SELECT_TOOL = {
    "name": "select_section",
    "description": "Select the CSI spec section that specifies the given material or "
                   "finish, chosen from the provided candidates, or 'none' if none fit.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "section": {"type": "string",
                        "description": "A section number copied from the candidate list, or 'none'."},
            "confidence": {"type": "number", "description": "0.0-1.0"},
            "reason": {"type": "string", "description": "One short clause."},
        },
        "required": ["section", "confidence", "reason"],
        "additionalProperties": False,
    },
}

_SYSTEM = ("You map a construction material or finish code to the CSI specification "
           "section that specifies it. Choose only from the provided candidate section "
           "numbers; if none is a genuine fit, answer 'none'. Do not invent numbers.")


def request_key(req: dict) -> str:
    """Stable content hash of the salient request fields, for fixture keying."""
    payload = {"code": req["code"], "context": req["context"],
               "candidates": dict(sorted(req["candidates"].items()))}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class LLMSectionMatcher:
    """Wraps an injectable client with grounding + graceful degradation."""

    def __init__(self, client):
        self.client = client  # callable(request: dict) -> {section, confidence, reason}

    def resolve(self, code: str, context: str, description: str,
                candidates: dict[str, str]) -> tuple[str | None, float, str]:
        req = {"code": code, "context": context, "description": description,
               "candidates": candidates}
        try:
            resp = self.client(req)
        except Exception:
            return None, 0.0, "llm_error"
        section = resp.get("section")
        conf = float(resp.get("confidence", 0.0) or 0.0)
        reason = resp.get("reason", "")
        if section not in candidates:          # grounding: reject 'none' / hallucinations
            return None, conf, reason
        return section, conf, reason


class AnthropicSectionClient:
    """Real backend. Lazily imports `anthropic` so it's an optional dependency."""

    def __init__(self, model: str = _MODEL, client=None):
        if client is None:
            import anthropic  # optional dep; only needed for the live backend
            client = anthropic.Anthropic()
        self.client = client
        self.model = model

    def __call__(self, req: dict) -> dict:
        cands = "\n".join(f"  {n}: {t}" for n, t in sorted(req["candidates"].items()))
        user = (f"Code: {req['code']}\n"
                f"Appears in: {req['context']} schedule\n"
                f"Known description: {req['description'] or '(none available)'}\n\n"
                f"Candidate CSI sections:\n{cands}\n\n"
                "Which section specifies this? Call select_section with a candidate "
                "number, or section='none'.")
        msg = self.client.messages.create(
            model=self.model, max_tokens=512, system=_SYSTEM,
            tools=[_SELECT_TOOL], tool_choice={"type": "tool", "name": "select_section"},
            messages=[{"role": "user", "content": user}],
        )
        for block in msg.content:
            if block.type == "tool_use":
                return dict(block.input)
        return {"section": "none", "confidence": 0.0, "reason": "no tool use"}


class ReplayClient:
    """Deterministic offline backend: replays recorded responses by request key."""

    def __init__(self, path: str | pathlib.Path):
        p = pathlib.Path(path)
        self.data = json.loads(p.read_text()) if p.exists() else {}

    def __call__(self, req: dict) -> dict:
        key = request_key(req)
        if key not in self.data:
            raise KeyError(f"no recorded fixture for {req['code']!r} ({key})")
        return self.data[key]


class RecordingClient:
    """Wraps a live client and writes each response to a fixture file (for the
    one-time recording pass; run with credentials, then commit the fixtures)."""

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
