"""One learner request -> one reply.

    rule shortcut -> cache -> compact triage -> route -> (RAG) -> generate -> cache

Every decision is recorded in `route_reason`, shown to learners as a small
badge and logged in metrics, so the compact/mid-size split is visible and
explainable to the jury.
"""
from __future__ import annotations

import json
import re
from typing import Awaitable, Callable, Optional

from . import cache, content, metrics, rag
from .llm_gateway import GatewayError, LLMGateway, LLMResult
from .rooms import Room

Emit = Callable[[dict], Awaitable[None]]

INTENTS = {"hint", "explain", "check", "greeting", "off_topic", "other"}
LANGUAGES = {"darija_arabic", "darija_latin", "msa", "fr", "en", "mixed"}

_GREETING_RE = re.compile(
    r"^\s*(salam|slm|ahla|aslema|bonjour|bonsoir|salut|hello|hi|hey|merci|thanks|thank you|يعيشك|سلام|مرحبا|عسلامة)\b[\s!.,]*$",
    re.I,
)
_GREETING_REPLY = {
    "fr": "Salut ! On continue l'exercice ensemble ? Dis-moi où tu bloques.",
    "darija_latin": "Aslema! Nkamlou l'exercice m3a b3adhna? 9olli win t7ebbest.",
    "darija_arabic": "عسلامة! نكملو التمرين مع بعضنا؟ قلّي وين تحبستك.",
    "en": "Hi! Shall we keep going with the exercise? Tell me where you're stuck.",
}


async def handle_message(gateway: LLMGateway, room: Room, text: str, emit: Emit) -> dict:
    ex, step = room.exercise, room.step
    step_number, step_count = room.step_index + 1, len(ex["steps"])

    # 1) Rule shortcut: greetings never need a model call.
    if _GREETING_RE.match(text):
        lang = _guess_language(text)
        metrics.log_call(step="chat", model_class="rule", route_reason="greeting rule")
        return _reply(_GREETING_REPLY.get(lang, _GREETING_REPLY["fr"]), "rule", None, "chat",
                      "Greeting handled by a rule: no model call")

    # 2) Exact cache: same question, same exercise step, same hint level.
    key = cache.make_key(text, ex["id"], str(room.step_index), str(room.hint_level))
    await emit({"kind": "stage", "label": "Checking if this was already answered"})
    hit = cache.get(key)
    if hit:
        metrics.log_call(step=hit.get("step", "?"), model_class="cache", cache_hit=True,
                         route_reason="exact cache hit")
        return {**hit, "cached": True, "route_reason": "Already answered: served from cache (0 model calls)"}

    # 3) Compact triage (one short JSON call).
    await emit({"kind": "stage", "label": "Understanding your question"})
    triage = await _triage(gateway, room, text, emit)
    lang = triage["language"]

    # 4) Route.
    if triage["confused"]:
        room.confused_streak += 1
    else:
        room.confused_streak = 0

    if triage["intent"] in ("greeting", "off_topic"):
        step_name, reason = "chat", f"intent={triage['intent']} -> compact short reply"
    elif triage["intent"] == "explain" or triage["needs_reasoning"] or room.confused_streak >= 2:
        why = ("asked for an explanation" if triage["intent"] == "explain"
               else "needs multi-step reasoning" if triage["needs_reasoning"]
               else "confused twice in a row")
        step_name, reason = "explain", f"{why} -> mid-size explanation"
    else:
        step_name, reason = "hint", f"intent={triage['intent']} -> compact hint (level {room.hint_level})"

    # 5) Generate.
    if step_name == "chat":
        system = content.prompt("chat", exercise_title=ex["title"], language=lang)
        result = await gateway.chat("chat", _messages(system, room, text), route_reason=reason, on_status=emit)

    elif step_name == "hint":
        await emit({"kind": "stage", "label": "Preparing a hint (not the answer)"})
        system = content.prompt(
            "hint", exercise_statement=ex["statement"], step_number=step_number, step_count=step_count,
            step_goal=step["goal"], step_hint=step.get("hint", ""), misconception=step.get("misconception", ""),
            hint_level=min(room.hint_level, 2), language=lang,
        )
        result = await gateway.chat("hint", _messages(system, room, text), route_reason=reason, on_status=emit)
        room.hint_level += 1

    else:  # explain
        await emit({"kind": "stage", "label": "Reading the course notes"})
        chunks = await rag.search(gateway, text, exercise_id=ex["id"], k=3)
        ctx = "\n".join(f"- {c['text']}" for c in chunks) or "(none)"
        await emit({"kind": "stage", "label": "Writing a step-by-step explanation"})
        system = content.prompt(
            "explain", exercise_statement=ex["statement"], step_number=step_number, step_count=step_count,
            step_goal=step["goal"], step_work=step["work"], context=ctx, language=lang,
        )
        result = await gateway.chat("explain", _messages(system, room, text), route_reason=reason, on_status=emit)
        if result.fell_back:
            reason += " (mid-size busy: answered by compact)"
        room.confused_streak = 0

    reply = _reply(result.text, result.model_class, result.model, step_name, reason,
                   latency_ms=result.latency_ms, fell_back=result.fell_back, language=lang)
    if not result.fell_back:            # don't cache degraded answers
        cache.put(key, {k: v for k, v in reply.items() if k != "cached"})
    return reply


async def _triage(gateway: LLMGateway, room: Room, text: str, emit: Emit) -> dict:
    system = content.prompt("triage", exercise_title=room.exercise["title"],
                            step_number=room.step_index + 1, step_goal=room.step["goal"])
    try:
        res: LLMResult = await gateway.chat(
            "triage", [{"role": "system", "content": system}, {"role": "user", "content": text}],
            route_reason="triage", on_status=emit,
        )
        parsed = _parse_json(res.text)
    except GatewayError:
        raise
    except Exception:
        parsed = None
    return _normalize_triage(parsed, text)


def _normalize_triage(parsed: Optional[dict], text: str) -> dict:
    """Small models sometimes return messy JSON: validate, and fall back to rules."""
    parsed = parsed or {}
    intent = parsed.get("intent") if parsed.get("intent") in INTENTS else _guess_intent(text)
    language = parsed.get("language") if parsed.get("language") in LANGUAGES else _guess_language(text)
    return {
        "intent": intent,
        "language": language,
        "confused": bool(parsed.get("confused", _looks_confused(text))),
        "needs_reasoning": bool(parsed.get("needs_reasoning", False)),
    }


def _parse_json(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _guess_intent(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(pourquoi|comment|explique|why|how|explain|3lech|kifech|علاش|كيفاش)\b", t):
        return "explain"
    if re.search(r"=|\d", t):
        return "check"
    return "hint"


def _looks_confused(text: str) -> bool:
    return bool(re.search(r"(ma fhemt|mafhemt|je comprends pas|j'ai pas compris|don't get|lost|ما فهمت|مافهمتش)", text.lower()))


def _guess_language(text: str) -> str:
    if re.search(r"[؀-ۿ]", text):
        return "darija_arabic"
    t = text.lower()
    if re.search(r"\b\w*[3795]\w*\b", t) and re.search(r"[a-z]", t) and re.search(r"\b(chnowa|3lech|kifech|ma|fhemt|9olli|barcha|famma|nheb|n7eb|aslema|wala)\b", t):
        return "darija_latin"
    if re.search(r"\b(le|la|les|est|pourquoi|comment|je|tu|dérivée|calcul)\b", t):
        return "fr"
    if re.search(r"\b(the|is|why|how|what|i|you)\b", t):
        return "en"
    return "mixed"


def _messages(system: str, room: Room, text: str) -> list[dict]:
    """System prompt + the last few turns of the room (kept short to save tokens)."""
    msgs = [{"role": "system", "content": system}]
    for ev in list(room.history)[-6:]:
        if ev.get("type") == "message":
            msgs.append({"role": "user", "content": f"{ev['from']}: {ev['text']}"})
        elif ev.get("type") == "ai_message":
            msgs.append({"role": "assistant", "content": ev["text"]})
    if not msgs or msgs[-1].get("content", "").split(": ", 1)[-1] != text:
        msgs.append({"role": "user", "content": text})
    return msgs


def _reply(text, model_class, model, step, reason, latency_ms=0, fell_back=False, language="fr") -> dict:
    return {
        "text": text,
        "model_class": model_class,
        "model": model,
        "step": step,
        "route_reason": reason,
        "latency_ms": latency_ms,
        "fell_back": fell_back,
        "language": language,
        "cached": False,
    }
