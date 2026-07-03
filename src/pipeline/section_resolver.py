"""Semantic Section Resolver (B9) — derive code->section edges instead of hardcoding.

Replaces the hand-authored MATERIAL_SECTION / FINISH_SECTION dicts by matching a
material/finish code's *expansion* against the project's real TOC section titles,
constrained by CSI division.

M1 (this file, so far): EXPANSION ASSEMBLY. A code like `ACT` or `P` is meaningless
to a matcher; its human-readable description is the query text. Descriptions come
from two already-parsed sources:
  * the architectural abbreviation list  (HM -> "HOLLOW METAL", GYP -> "GYPSUM"), and
  * the applied-finish-list `TYPE:` field (P-1 -> "GENERAL PAINT",
    CPT-1 -> "18\"X36\" CARPET TILE", CON-1 -> "POLISHED & SEALED CONCRETE").
The finish `TYPE:` is usually richer than the bare abbreviation, so for finish-code
prefixes we prefer it, falling back to the abbreviation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Field keywords that terminate a finish-list TYPE: description.
_FINISH_FIELDS = ("TYPE", "STYLE", "MANUFACTURE", "MANUFACTURER", "LOCATION", "COLOR",
                  "INSTALL", "NOTES", "GRID", "PROFILE", "CONTENT", "ELEVATION", "CONTACT")
_FIELD_RE = re.compile(rf"\b(?:{'|'.join(_FINISH_FIELDS)})\s*:", re.I)
_ALPHA_PREFIX_RE = re.compile(r"[A-Za-z]+")


def _alpha_prefix(code: str) -> str:
    m = _ALPHA_PREFIX_RE.match(code or "")
    return m.group().upper() if m else ""


def _finish_type(definition: str) -> str:
    """Extract the TYPE: value from an applied-finish-list definition, up to the
    next field keyword. 'CPT-1 TYPE: 18"X36" CARPET TILE STYLE: MATTE' -> the size
    and 'CARPET TILE'."""
    m = re.search(r"TYPE\s*:\s*(.*)", definition or "", re.I | re.S)
    if not m:
        return ""
    tail = m.group(1)
    nxt = _FIELD_RE.search(tail)
    return (tail[:nxt.start()] if nxt else tail).strip()


def finish_type_descriptions(prefix: str, applied: dict[str, str]) -> list[str]:
    """All applied-finish TYPE descriptions whose code shares this alpha prefix."""
    p = prefix.upper()
    out: list[str] = []
    for code, definition in applied.items():
        if _alpha_prefix(code) == p:
            desc = _finish_type(definition)
            if desc:
                out.append(desc)
    return out


def expansion(code: str, abbrev: dict[str, str], applied: dict[str, str],
              prefer: str = "finish") -> str:
    """Best human-readable description for a material/finish code.

    Context matters: the same alpha prefix can mean different things in a door
    schedule vs a finish schedule (WD = wood *door* material, but WD-1 = wood-slat
    *ceiling* finish). So `prefer="material"` favors the abbreviation (material
    sense) and `prefer="finish"` favors the applied-finish TYPE: (finish sense);
    each falls back to the other, then to empty.
    """
    prefix = _alpha_prefix(code)
    abbr_desc = abbrev.get(code) or abbrev.get(prefix) or ""
    finish = finish_type_descriptions(prefix, applied)
    # shortest TYPE tends to be the cleanest generic description (P-1 'GENERAL
    # PAINT' over P-1B 'LAB WALL & CEILING GENERAL PAINT ...').
    finish_desc = min(finish, key=len) if finish else ""
    return (abbr_desc or finish_desc) if prefer == "material" else (finish_desc or abbr_desc)


# --- M2: deterministic matcher -----------------------------------------------

_STOP = {"and", "of", "the", "for", "a", "to", "with", "or", "in", "at"}


def _tokens(s: str) -> list[str]:
    return [t for t in re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split()
            if t not in _STOP and len(t) > 1]


def _tok_match(a: str, b: str) -> bool:
    """Equal, or a prefix relationship for words >= 4 chars — cheaply handles
    carpet/carpeting, acoustic/acoustical, paint/painting, ceiling/ceilings without
    risky stemming (which would maul 'metal' -> 'met')."""
    if a == b:
        return True
    return len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a))


def score_title(expansion: str, title: str) -> float:
    """Fraction of expansion tokens that appear (by _tok_match) in the title."""
    q = _tokens(expansion)
    if not q:
        return 0.0
    t = _tokens(title)
    return sum(1 for qt in q if any(_tok_match(qt, tt) for tt in t)) / len(q)


def match_section(
    expansion: str, titles: dict[str, str],
    division: str | None = None, min_conf: float = 0.5,
) -> tuple[str | None, float]:
    """Best-matching section for an expansion, optionally constrained to a CSI
    division. Returns (section_number, confidence); (None, score) when the best
    score is below min_conf (the low-confidence tail → override/LLM). A coincidental
    zero-overlap argmax therefore never yields an edge."""
    best, best_sc = None, 0.0
    for num, title in titles.items():
        if division and not num.startswith(division):
            continue
        sc = score_title(expansion, title)
        if sc > best_sc:
            best, best_sc = num, sc
    return (best, round(best_sc, 3)) if best_sc >= min_conf else (None, round(best_sc, 3))


# --- M3: resolve a code set to sections (derive, with seed as shrinking override) -


@dataclass
class SectionLink:
    section: str | None
    method: str            # derived_lexical | derived_llm | override | unresolved
    confidence: float


def build_section_map(
    codes, abbrev: dict[str, str], applied: dict[str, str], titles: dict[str, str],
    kind: str, division: str | None, seed: dict[str, str] | None = None,
    matcher=match_section,
) -> dict[str, SectionLink]:
    """Resolve each code to a spec section by derivation, using `seed` (the
    hand-authored map) only as an override for cases the matcher can't yet derive.

    Derivation is primary: when the matcher agrees with the seed (or no seed is
    given, e.g. a new project) the edge is `derived_*`. When it disagrees or finds
    nothing but a seed exists, we fall back to `override` — so UCCS stays
    byte-identical while the override table shrinks as the matcher (M4 LLM) improves.
    """
    seed = seed or {}
    out: dict[str, SectionLink] = {}
    for code in codes:
        exp = expansion(code, abbrev, applied, "material" if kind == "material" else "finish")
        got, conf = matcher(exp, titles, division)
        want = seed.get(code)
        if got is not None and (want is None or got == want):
            out[code] = SectionLink(got, "derived_lexical", conf)
        elif want is not None:
            out[code] = SectionLink(want, "override", conf)
        else:
            out[code] = SectionLink(None, "unresolved", conf)
    return out


if __name__ == "__main__":
    from src.pipeline.phase2_abbreviation_parser import abbreviations_as_dict, parse_abbreviations
    from src.pipeline.phase2_schedule_parser import parse_applied_finish_list
    from src.pipeline.phase5_graph_builder import FINISH_SECTION, MATERIAL_SECTION

    from src.pipeline.phase2_spec_parser import parse_spec_toc

    abbr = abbreviations_as_dict(parse_abbreviations())
    applied = parse_applied_finish_list()
    toc = parse_spec_toc()
    titles = {s["number"]: s["title"] for d in toc.divisions for s in d["sections"]}

    derived = 0
    total = 0
    for kind, codes, div in (("mat", MATERIAL_SECTION, "08"), ("finish", FINISH_SECTION, None)):
        for code, want in codes.items():
            exp = expansion(code, abbr, applied, "material" if kind == "mat" else "finish")
            got, conf = match_section(exp, titles, div)
            ok = got == want
            derived += ok
            total += 1
            tag = "OK" if ok else ("tail" if got is None else f"WRONG->{got}")
            print(f"  [{kind:<6}] {code:<7} exp={exp!r:<26} want={want} conf={conf:<5} {tag}")
    print(f"--- deterministically derived (agree with hand-authored): {derived}/{total} ---")
