"""Explicit local-only AI proposals for official IPC classification selection.

The model is not allowed to run searches, import data, or confirm patent facts.
Only the backend's versioned official catalogue can verify an AI suggestion.
"""
import json
import re

from . import privacy
from .official_ipc import verified_subclass
from .source_planner import CANDIDATES

MAX_QUESTION_CHARS = 360
MAX_CODES = 5
LABELS = {x[0]: x[1] for x in CANDIDATES}
SUBCLASS = re.compile(r"^[A-H][0-9]{2}[A-Z]$")
PROMPT = (
    "あなたは特許分類の調査補助です。次の質問は未公開の発明情報を含み得ます。"
    "質問に関連するIPC分類のサブクラスを、最大5件、重要と思われる順に考えてください。"
    "固定された技術リストから選ぶのではなく、IPCの技術体系を使って提案してください。"
    "出力は単一JSONのみ: codes（IPCサブクラスの文字列配列）, reason（短い日本語の根拠）, "
    "clarify（必要な場合だけ確認質問）。IPCコードを確信できないときはcodesを空配列にしてください。"
    "特許性判断や外部検索・実行はしないでください。"
)


def local_models(providers, config):
    return [
        {"id": p["id"], "label": str(p.get("label") or p["id"])[:100],
         "model": str(p.get("model") or "")[:120]}
        for p in providers.list()
        if p.get("type") != "openrouter" and privacy.confidential_allowed(p, config)
    ]


def parse_answer(content, store=None):
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
    candidates, seen = [], set()
    for code in obj["codes"][:20]:
        if type(code) is not str or not SUBCLASS.fullmatch(code) or code in seen:
            continue
        seen.add(code)
        valid = bool(store is not None and verified_subclass(store, code))
        candidates.append({"code": code, "label": LABELS.get(code),
                           "official_catalog_verified": valid,
                           "status": "ai_unreviewed" if valid else "not_verified_in_official_catalog"})
        if len(candidates) >= MAX_CODES:
            break
    return {"codes": candidates, "reason": obj["reason"].strip()[:800],
            "clarify": str(obj.get("clarify") or "").strip()[:240],
            "provenance": "local_llm_unreviewed", "automatic_search": False,
            "warning": "AI推定は未確認です。公式IPC辞書との一致を示すもの以外は外部検索の選択肢にしません。"}


def advise(question, provider_id, providers, config, store):
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
        overrides={"max_tokens": 600, "temperature": 0.1})
    answer = parse_answer(result["content"], store=store)
    answer["provider"] = provider_id
    answer["model"] = str(result.get("model") or "")[:160]
    return answer
