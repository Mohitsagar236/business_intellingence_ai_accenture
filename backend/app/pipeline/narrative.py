"""
Stage 4b/4c — Narrative Generation & the anti-hallucination guard (SRS FR-4.2/FR-4.3).

The LLM is given a fixed "evidence pack" (only the Evidence rows persisted for this anomaly)
and instructed to cite an evidence id after every claim. The grounding guard below then
independently re-checks the response: any sentence whose citation is missing or points to
an id outside the evidence pack is stripped from the narrative and recorded in
Report.stripped_claims — the guard does not trust the model's own claim of groundedness.

Reaches Claude one of two ways — a direct Anthropic API key, or an OpenRouter key (an
OpenAI-compatible gateway; used in preference to Anthropic if both are set). If neither is
configured, or the call fails, narrative generation falls back to a deterministic template
writer over the same evidence pack — never a stub, always a real, fully-grounded (if plainer)
report, with `Report.generated_by` marking which path ran.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.config import get_settings
from app.logging_config import event

settings = get_settings()
logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[E(\d+)\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class EvidencePackItem:
    evidence_id: int
    type: str  # structured | unstructured
    description: str
    excerpts: list[str]


@dataclass
class GroundedText:
    text: str
    citations_used: list[int]
    stripped: list[str]


def _ground(raw_text: str, allowed_ids: set[int]) -> GroundedText:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(raw_text.strip()) if s.strip()]
    kept: list[str] = []
    stripped: list[str] = []
    used: set[int] = set()

    for sentence in sentences:
        ids = {int(m) for m in _CITATION_RE.findall(sentence)}
        if not ids:
            stripped.append(sentence)
            continue
        if not ids.issubset(allowed_ids):
            stripped.append(sentence)
            continue
        kept.append(sentence)
        used |= ids

    if not kept:
        # Defensive fallback so a report is never blank: surface the raw evidence directly.
        kept = [f"Evidence [E{i}] was found but could not be phrased into a grounded sentence." for i in sorted(allowed_ids)]

    return GroundedText(text=" ".join(kept), citations_used=sorted(used), stripped=stripped)


def _evidence_block(pack: list[EvidencePackItem]) -> str:
    lines = []
    for item in pack:
        lines.append(f"[E{item.evidence_id}] ({item.type}) {item.description}")
        for ex in item.excerpts[:3]:
            lines.append(f'    excerpt: "{ex}"')
    return "\n".join(lines)


_SYSTEM_PROMPT = (
    "You are a grounded business-intelligence report writer. You may state a claim ONLY if you "
    "immediately cite the evidence id(s) that support it, in the exact format [E<id>]. Never cite "
    "an id that is not in the evidence list you are given, and never state a fact, number, or "
    "detail that is not present in that evidence. Write plain, direct business English — no "
    "hedging filler, no marketing language. Every sentence must end with at least one citation."
)


def _failure_reason(exc: Exception) -> str:
    name = type(exc).__name__
    return "timeout" if "Timeout" in name else "error"


def _call_claude(prompt: str) -> str | None:
    # Never log `prompt` itself — it embeds the evidence pack, which can include excerpted
    # customer text. Only the provider/model routing decision is logged here.
    if settings.gemini_api_key:
        event(logger, logging.INFO, "narrative_generation_started", provider="gemini", model=settings.gemini_model)
        return _call_via_gemini(prompt)
    if settings.openrouter_api_key:
        event(logger, logging.INFO, "narrative_generation_started", provider="openrouter", model=settings.openrouter_model)
        return _call_via_openrouter(prompt)
    if settings.anthropic_api_key:
        event(logger, logging.INFO, "narrative_generation_started", provider="anthropic", model=settings.anthropic_model)
        return _call_via_anthropic(prompt)
    event(logger, logging.INFO, "narrative_no_llm_configured")
    return None


def _call_via_gemini(prompt: str) -> str | None:
    """Google's Generative Language API — a third transport (REST, `contents`/`parts` shape,
    API key as a URL query param rather than a bearer header) alongside the two Claude routes
    above. Same grounding guard applies to whatever comes back, regardless of which model
    produced it."""
    try:
        import httpx

        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            params={"key": settings.gemini_api_key},
            json={
                "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": prompt}]}],
                # This model reasons before answering, and that reasoning draws from the same
                # token budget as the visible output — 500 (enough for Claude's non-reasoning
                # output) was observed truncating the answer before it started. 3000 leaves
                # comfortable headroom for both on a response this short.
                "generationConfig": {"maxOutputTokens": 3000},
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        candidate = data["candidates"][0]
        if candidate.get("finishReason") not in ("STOP", None):
            # MAX_TOKENS (ran out of budget mid-answer, so what's here is a cut-off fragment,
            # not a complete response) or any other non-STOP reason — never return a partial
            # answer as if it were whole; the caller's grounding guard would either strip an
            # incomplete uncited sentence (leaving an empty, blank-looking section) or, worse,
            # let a truncated-but-technically-cited fragment through. Treat as a failure so the
            # deterministic template writer takes over cleanly instead.
            event(logger, logging.WARNING, "llm_generation_failed", provider="gemini", reason="truncated", error_type="finish_reason_" + str(candidate.get("finishReason")))
            return None
        event(logger, logging.INFO, "narrative_generation_succeeded", provider="gemini")
        return candidate["content"]["parts"][0]["text"]
    except Exception as exc:
        # Never log str(exc) wholesale — the request URL itself carries the API key as a query
        # param here, and an httpx error's message can echo the URL it failed on.
        event(logger, logging.WARNING, "llm_generation_failed", provider="gemini", reason=_failure_reason(exc), error_type=type(exc).__name__)
        return None


def _call_via_anthropic(prompt: str) -> str | None:
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=500,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        event(logger, logging.INFO, "narrative_generation_succeeded", provider="anthropic")
        return text
    except Exception as exc:
        # Never log str(exc) wholesale — an HTTP client's exception message can echo back
        # request/response bodies. error_type + a coarse reason category is enough to act on.
        event(logger, logging.WARNING, "llm_generation_failed", provider="anthropic", reason=_failure_reason(exc), error_type=type(exc).__name__)
        return None


def _call_via_openrouter(prompt: str) -> str | None:
    """OpenRouter is an OpenAI-compatible gateway that can route to Claude — a different
    transport (plain REST, chat-completions shape) from the native Anthropic SDK above, but
    the same model family and the same grounding guard applies to whatever comes back."""
    try:
        import httpx

        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://businessintelligence.ai",
                "X-Title": "BusinessIntelligence.ai",
            },
            json={
                "model": settings.openrouter_model,
                "max_tokens": 500,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        event(logger, logging.INFO, "narrative_generation_succeeded", provider="openrouter")
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        event(logger, logging.WARNING, "llm_generation_failed", provider="openrouter", reason=_failure_reason(exc), error_type=type(exc).__name__)
        return None


def _template_cause(pack: list[EvidencePackItem], cause_display: str) -> str:
    sentences = []
    for item in pack:
        desc = item.description.rstrip(".")
        sentences.append(f"{desc} [E{item.evidence_id}].")
    tags = "".join(f"[E{item.evidence_id}]" for item in pack)
    sentences.append(f"Together, this converges on {cause_display.lower()} {tags}.")
    return " ".join(sentences)


def _template_confidence(confidence: float, is_validated: bool) -> str:
    if is_validated:
        return f"Confidence is {confidence:.0%}: both a correlated structured metric and a matching thematic spike in unstructured evidence were found in the same segment and window."
    return f"Confidence is {confidence:.0%}: the available evidence is partial and does not converge on a single explanation."


def generate_cause_and_confidence(
    pack: list[EvidencePackItem],
    cause_display: str,
    confidence: float,
    is_validated: bool,
    is_multi_hypothesis: bool = False,
) -> tuple[GroundedText, GroundedText, str]:
    """Returns (cause_text, confidence_text, generated_by)."""
    allowed_ids = {item.evidence_id for item in pack}
    evidence_block = _evidence_block(pack)

    # "Plain text, no markdown" matters here, not just for tidiness: cause_raw/confidence_raw
    # below are split on the literal word CONFIDENCE and stripped of a leading CAUSE — a model
    # that renders these as "### CAUSE" would leave that "### " sitting in the final report text.
    if is_multi_hypothesis:
        task = (
            f"Evidence:\n{evidence_block}\n\n"
            "The evidence does NOT converge on a single cause. Write one paragraph (2-4 sentences) "
            "under the heading CAUSE describing the competing hypotheses, citing each item you reference. "
            "Then write one paragraph (1-2 sentences) under the heading CONFIDENCE explaining why this is "
            "reported as ambiguous rather than a single finding. Plain text only — the two headings are "
            "just the bare words CAUSE and CONFIDENCE, no markdown symbols like # or *."
        )
    else:
        task = (
            f"Evidence:\n{evidence_block}\n\n"
            f"The validated cause is: {cause_display}. Write one paragraph (2-3 sentences) under the "
            "heading CAUSE explaining how the evidence supports this, citing each item you reference. "
            "Then write one short paragraph (1-2 sentences) under the heading CONFIDENCE explaining the "
            f"basis for a confidence level of {confidence:.0%}. Plain text only — the two headings are "
            "just the bare words CAUSE and CONFIDENCE, no markdown symbols like # or *."
        )

    raw = _call_claude(task)
    # Mirrors _call_claude's own provider priority — Report.generated_by should name whichever
    # provider actually produced the text, not default to "claude" now that Gemini is a real
    # option too (README/frontend both surface this field as a transparency signal).
    if settings.gemini_api_key:
        generated_by = "gemini"
    elif settings.openrouter_api_key or settings.anthropic_api_key:
        generated_by = "claude"
    else:
        generated_by = "template"
    if raw is None:
        generated_by = "template"
        # _call_claude already logged *why* (no_llm_configured is INFO/expected; a real call
        # failure is a WARNING logged in _call_via_anthropic/_call_via_openrouter) — this is
        # the visible confirmation that the architecture's fallback actually engaged rather
        # than the report silently going empty.
        event(logger, logging.INFO, "deterministic_writer_fallback", reason="no_llm_response")
        cause_raw = _template_cause(pack, cause_display)
        confidence_raw = _template_confidence(confidence, is_validated)
    else:
        # Split on the FIRST "CONFIDENCE" heading, colon optional — models don't reliably
        # include the colon, and a regex that requires it lets the whole confidence section
        # bleed into the cause text (a real bug this replaced: the split silently never
        # matched, so cause_raw captured everything through the end of the response).
        parts = re.split(r"\bCONFIDENCE:?\s*", raw, maxsplit=1, flags=re.IGNORECASE)
        cause_raw = re.sub(r"^\s*CAUSE:?\s*", "", parts[0], flags=re.IGNORECASE).strip()
        confidence_raw = parts[1].strip() if len(parts) > 1 else ""
        if not cause_raw:
            cause_raw = raw.strip()
        if not confidence_raw:
            generated_by = "template"
            event(logger, logging.WARNING, "deterministic_writer_fallback", reason="unparseable_confidence_section")
            confidence_raw = _template_confidence(confidence, is_validated)

    cause_grounded = _ground(cause_raw, allowed_ids)
    # Grounding applies to any real LLM output regardless of which provider produced it — only
    # the template path is exempt, since template text is built directly from evidence records
    # and can't cite anything ungrounded in the first place.
    confidence_grounded = _ground(confidence_raw, allowed_ids) if generated_by != "template" else GroundedText(
        text=confidence_raw, citations_used=[], stripped=[]
    )

    return cause_grounded, confidence_grounded, generated_by
