"""Strictly local, on-demand technical classification advisor.

All outputs are unreviewed; no search, storage mutation, or cloud fallback.
"""
import json
import re

from . import privacy
from .source_planner import CANDIDATES, SUPPORTED

MAX_QUESTION_CHARS = 360
MAX_CODES = 5
LABELS = {x[0]: x[1] for x in CANDIDATES}
PROMPT = (
    "You help a Japanese patent researcher choose preliminary IPC subclasses. "
    "The user's question may describe an unpublished invention and must remain private. "
    "Only choose codes from: " +
    ", ".join(x + " (" + LABELS[x] + ")" for x in sorted(SUPPORTED)) + ". "
    "Return one JSON object: codes (array of strings), reason (Japanese short string), "
    "clarify (optional Japanese question). Maximum five codes. "
    "If the allowed set is insufficient, return an empty codes array. "
    "All codes are proposals, not patentability findings or complete classification."
)

def quick_presets():
    return [
        {"label": "インバータ", "topic": "インバータ", "codes": ["H02M", "H02P", "B60L"]},
        {"label": "モータ制御", "topic": "モータ制御", "codes": ["H02P", "H02M"]},
        {"label": "電源・回路", "topic": "電源 電気", "codes": ["H02J", "H02M", "H01F"]},
        {"label": "チョーク・インダクタ", "topic": "チョーク インダクタ", "codes": ["H01F"]},
        {"label": "機械・駆動", "topic": "機械 ギヤ", "codes": ["F16H", "F16C"]},
        {"label": "ポンプ・冷却", "topic": "ポンプ 送風機", "codes": ["F04D"]},
    ]


def local_models(providers, config):
    return [
        {"id": p["id"], "label": str(p.get("label") or p["id"])[:100],
         "model": str(p.get("model") or "")[:120]}
        for p in providers.list()
        if p.get("type") != "openrouter" and privacy.confidential_allowed(p, config)
    ]


def parse_answer(content):
    if not isinstance(content, str) or not 1 <= len(content) <= 3500:
        raise ValueError("AI回答が長すぎるか空です")
    value = content.strip()
    fence = chr(96) * 3
    if value.startswith(fence) and value.endswith(fence):
        value = re.sub(r"^" + re.escape(fence) + r"(?:json)?\s*|\s*" +
                       re.escape(fence) + r"$", "", value, flags=re.I).strip()
    try:
        obj = json.loads(value)
    except ValueError:
        raise ValueError("AI回答のJSON形式が不正です") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("codes"), list) or type(obj.get("reason")) is not str:
        raise ValueError("AI回答の分類候補形式が不正です")
    codes = []
    for code in obj["codes"][:20]:
        if type(code) is str and code in SUPPORTED and code not in codes:
            codes.append(code)
    return {"codes": [{"code": code, "label": LABELS[code], "status": "ai_unreviewed"}
                      for code in codes[:MAX_CODES]],
            "reason": obj["reason"].strip()[:800],
            "clarify": str(obj.get("clarify") or "").strip()[:240],
            "provenance": "local_llm_unreviewed", "automatic_search": False,
            "warning": "AIの候補です。原典確認と操作者の承認が必要です。"}


def advise(question, provider_id, providers, config):
    if (not isinstance(question, str) or not 1 <= len(question.strip()) <= MAX_QUESTION_CHARS
            or any(ord(ch) < 32 for ch in question)):
        raise ValueError("AIへの質問は1〜360文字、制御文字なしで指定してください")
    if not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 80:
        raise ValueError("ローカルAIを選択してください")
    if provider_id not in {p["id"] for p in local_models(providers, config)}:
        raise ValueError("選択したモデルはローカルAIとして検証されていません")
    result = providers.chat(
        [{"role": "system", "content": PROMPT}, {"role": "user", "content": question.strip()}],
        provider=provider_id, scope="confidential", timeout=60,
        overrides={"max_tokens": 600, "temperature": 0.1},
    )
    response = parse_answer(result["content"])
    response["provider"] = provider_id
    response["model"] = str(result.get("model") or "")[:160]
    return response
