"""
intent.py — LLM-based query intent classification and filter extraction.

Calls Ollama qwen3:30b (think=False) as primary.
Falls back to Anthropic claude-sonnet-4-6 if Ollama is unavailable or returns
malformed output.

Returns a structured intent dict that drives retrieve() call count, synthesis
think mode, and top_k.
"""
import json
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "config" / ".env")

log = logging.getLogger(__name__)

OLLAMA_URL     = "http://localhost:11434/api/chat"
OLLAMA_MODEL   = "qwen3:30b"
OLLAMA_TIMEOUT = 60

ANTHROPIC_MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Allowed canonical values — injected into system prompt so the LLM can only
# output values that exist in the DB.
# ---------------------------------------------------------------------------
_COMPANIES = ["共立電機製作所", "共立電照"]

_DOC_TYPES = ["monthly_report"]

# Per-company org structure — used both for prompt construction and validation
_ORG = {
    "共立電機製作所": {
        "depts": [
            "営業部", "設計部", "生産管理部", "総務部", "製造部",
            "配線部", "検査部", "品質環境管理部", "エンジニアリング部",
        ],
        "sections": [
            "東京支店", "大阪支店", "福岡支店",
            "電気設計課", "構造設計課",
            "工程課", "資材課", "KIP AI/IOTグループ",
            "加工課", "フレーム課", "薄物1課", "塗装課",
            "A-1課", "A-2課", "A-3課", "B-1課", "B-2課", "B-3課",
        ],
    },
    "共立電照": {
        "depts": [
            "営業部", "設計部", "製造部", "管理部",
            "品質環境管理課", "808MERA",
        ],
        "sections": [
            "営業全体", "営業-東京", "営業-大阪", "営業-福岡", "営業-宮崎・沖縄",
            "設計課", "電気設計課", "企画開発課", "製品開発課",
            "工程管理課", "資材課", "薄物2課", "配線組立課", "検査課",
        ],
    },
}

_SYSTEM_PROMPT = f"""あなたは社内RAGシステムのクエリ解析エージェントです。
ユーザーの質問を解析し、以下のJSON形式のみで回答してください。余分なテキストは一切含めないこと。

## 出力形式
{{
  "intent": "<lookup|causal|comparative|aggregative>",
  "think": <true|false>,
  "top_k": <8|20>,
  "retrievals": [
    {{
      "company": "<value or null>",
      "dept": "<value or null>",
      "section": "<value or null>",
      "doc_type": "<value or null>",
      "year": <integer or null>,
      "month": <integer or null>,
      "meeting_date": "<YYYY-MM-DD or null>"
    }}
  ]
}}

## インテント定義
- lookup: 単一の事実を直接問う
- causal: 原因・分析・理由を問う【比較対象が1つの場合のみ】 (think=true)
- comparative: 複数期間・複数部署・複数会社を比較する【retrievalsが2件以上になる場合は必ずcomparative】(think=true, retrievalsに比較対象ごとのエントリを追加)
- aggregative: 期間・テーマが広く曖昧な質問 (think=true, top_k=20, month=null)

## 重要ルール
- 質問に複数の期間（例：11月と12月）が含まれる場合 → 必ず comparative
- 質問に複数の会社や部署が含まれる場合 → 必ず comparative
- 「なぜ差が生じるのか」などの比較＋因果質問 → comparative（causalではない）

## 組織構造（company ごとに有効な dept/section が異なる。必ずこの表に従うこと）
共立電機製作所:
  dept:    {json.dumps(_ORG["共立電機製作所"]["depts"], ensure_ascii=False)}
  section: {json.dumps(_ORG["共立電機製作所"]["sections"], ensure_ascii=False)}

共立電照:
  dept:    {json.dumps(_ORG["共立電照"]["depts"], ensure_ascii=False)}
  section: {json.dumps(_ORG["共立電照"]["sections"], ensure_ascii=False)}

## 制約
- company は必ず以下のいずれか(または null): {json.dumps(_COMPANIES, ensure_ascii=False)}
- doc_type は必ず以下のいずれか(または null): {json.dumps(_DOC_TYPES, ensure_ascii=False)}
- company が特定できない場合は "共立電機製作所" をデフォルトとする
- dept と section は上記「組織構造」の表にある値のみ使用すること。他の値は絶対に使わないこと。
- comparative の場合、retrievals に比較対象ごとのエントリを含める
- aggregative の場合、month は null にする
- JSONのみ出力すること。思考や説明は一切含めないこと。"""


def _parse_intent(raw: str) -> dict:
    """Extract and validate JSON from LLM response."""
    raw = raw.strip()
    # strip qwen3 thinking block: <think>...</think>
    if "</think>" in raw:
        raw = raw[raw.index("</think>") + len("</think>"):].strip()
    # strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(l for l in lines if not l.startswith("```")).strip()

    data = json.loads(raw)

    assert data["intent"] in ("lookup", "causal", "comparative", "aggregative")
    assert isinstance(data["retrievals"], list) and len(data["retrievals"]) >= 1
    for r in data["retrievals"]:
        for field in ("company", "dept", "section", "doc_type", "year", "month", "meeting_date"):
            assert field in r
        # clamp year to known data range — nullify out-of-range years
        if r["year"] is not None and not (2023 <= r["year"] <= 2026):
            r["year"] = None
        # nullify dept/section if they don't belong to the specified company
        company_org = _ORG.get(r["company"] or "共立電機製作所")
        if r["dept"] is not None and r["dept"] not in company_org["depts"]:
            r["dept"] = None
        if r["section"] is not None and r["section"] not in company_org["sections"]:
            r["section"] = None

    # deduplicate retrievals — keep unique filter combinations only
    seen = []
    unique = []
    for r in data["retrievals"]:
        key = (r["company"], r["dept"], r["section"], r["doc_type"], r["year"], r["month"], r["meeting_date"])
        if key not in seen:
            seen.append(key)
            unique.append(r)
    data["retrievals"] = unique

    return data


def _call_ollama(query: str) -> dict:
    payload = {
        "model":  OLLAMA_MODEL,
        "think":  False,
        "stream": False,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": f"/no_think\n{query}"},
        ],
        "options": {"temperature": 0.0, "num_predict": 4096},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
    resp.raise_for_status()
    msg = resp.json()["message"]
    # qwen3 sometimes puts output in thinking field when think=False
    content = msg.get("content") or msg.get("thinking") or ""
    return _parse_intent(content)


def _call_anthropic(query: str) -> dict:
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": query}],
    )
    content = msg.content[0].text
    return _parse_intent(content)


def llm_intent_pass(query: str) -> dict:
    """
    Classify query intent and extract filter sets.

    Tries Ollama first, falls back to Anthropic claude-sonnet-4-6.
    Raises RuntimeError if both fail.
    """
    try:
        result = _call_ollama(query)
        log.info("Intent (ollama): %s  retrievals=%d", result["intent"], len(result["retrievals"]))
        return result
    except Exception as e:
        log.warning("Ollama intent failed (%s), falling back to Anthropic", e)

    try:
        result = _call_anthropic(query)
        log.info("Intent (anthropic): %s  retrievals=%d", result["intent"], len(result["retrievals"]))
        return result
    except Exception as e:
        log.error("Anthropic intent also failed: %s", e)
        raise RuntimeError(f"Both intent backends failed: {e}") from e
