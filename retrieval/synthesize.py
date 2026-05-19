# pyrefly: ignore [missing-import]
"""
synthesize.py — Answer synthesis using Qwen3-30B thinking mode via Ollama.

Pipeline:
  1. taxonomy_pass  → lists of companies, depts, sections, periods
  2. keyword lookup → dept routing for semantic terms (売上高 → 営業部)
  3. Cartesian product of filters → capped at 4 combinations
  4. Parallel retrieve() per combination (ThreadPoolExecutor)
  5. Dedup + merge chunks
  6. Fallback LLM dept routing if dept still None after steps 1-2
  7. Qwen3-30B synthesis with think mode

Usage:
    python synthesize.py "2025年12月と11月の売上高を比較して"
    python synthesize.py --dept 営業部 --month 11 "売上の状況は？"
    python synthesize.py --no-think-trace "簡単な質問"
"""
import argparse
import json
import logging
import sys
from itertools import product
from pathlib import Path
from datetime import datetime

import requests

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from retrieve import (
    retrieve, load_embed_model, load_rerank_model, build_sudachi,
    RetrievedChunk,
)
from filters import taxonomy_pass
from config.org import DEPTS

# pyrefly: ignore [missing-import]
import torch

# ─── Config ───────────────────────────────────────────────────────────────────
OLLAMA_URL     = "http://localhost:11434/api/chat"
SYNTH_MODEL    = "qwen3:30b"
OLLAMA_TIMEOUT = 300
MAX_COMBOS     = 4   # cartesian product cap

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ─── Filter combination builder ───────────────────────────────────────────────

def build_filter_combos(
    tax:     dict,
    cli_company:  str | None = None,
    cli_dept:     str | None = None,
    cli_section:  str | None = None,
    cli_year:     int | None = None,
    cli_month:    int | None = None,
) -> list[dict]:
    """
    Build up to MAX_COMBOS filter dicts from taxonomy output.
    CLI overrides take priority over taxonomy values.
    Explicit matches (user named them in query) are prioritised when capping.
    """
    # CLI overrides win outright
    companies = [cli_company] if cli_company else tax["companies"]
    depts     = [cli_dept]    if cli_dept    else tax["depts"]    or [None]
    sections  = [cli_section] if cli_section else tax["sections"] or [None]
    doc_types = tax["doc_types"] or [None]

    # Periods — CLI override or taxonomy
    if cli_year is not None and cli_month is not None:
        periods = [(cli_year, cli_month)]
    elif cli_year is not None:
        periods = [(cli_year, p[1]) for p in tax["periods"]] if tax["periods"] else [(cli_year, None)]
    elif cli_month is not None:
        periods = [(p[0], cli_month) for p in tax["periods"]] if tax["periods"] else [(None, cli_month)]
    else:
        periods = tax["periods"] or [(None, None)]

    # Build cartesian product: company × dept × period
    # (section and doc_type don't fan out — use first value only)
    section  = sections[0]
    doc_type = doc_types[0]

    combos_raw = list(product(companies, depts, periods))

    # If over cap: prioritise combos where dept is explicitly named (not None)
    original_count = len(combos_raw)
    if len(combos_raw) > MAX_COMBOS:
        explicit = [c for c in combos_raw if c[1] is not None]
        rest     = [c for c in combos_raw if c[1] is None]
        combos_raw = (explicit + rest)[:MAX_COMBOS]
        log.info("Filter combos capped at %d (dropped %d)", MAX_COMBOS, original_count - MAX_COMBOS)

    combos = []
    for company, dept, (year, month) in combos_raw:
        combos.append({
            "company":  company,
            "dept":     dept,
            "section":  section,
            "doc_type": doc_type,
            "year":     year,
            "month":    month,
        })

    return combos


# ─── Fallback LLM dept router ─────────────────────────────────────────────────

def _fallback_dept(query: str, company: str) -> str | None:
    """
    Call Ollama qwen3:30b in a closed space to pick a dept from the known list.
    Returns canonical dept string or None if no match.
    """
    dept_list = DEPTS.get(company, [])
    if not dept_list:
        return None

    prompt = (
        f"以下は社内RAGシステムの部署リストです：\n{dept_list}\n\n"
        f"次の質問に最も関連する部署を上記リストから1つだけ選んでください。"
        f"リストにない部署や外部知識は使わないこと。該当なければ \"null\" と答えること。\n\n"
        f"質問：{query}\n\n"
        f"回答（部署名のみ）："
    )
    payload = {
        "model":  SYNTH_MODEL,
        "think":  False,
        "stream": False,
        "messages": [{"role": "user", "content": f"/no_think\n{prompt}"}],
        "options": {"temperature": 0.0, "num_predict": 32},
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=30)
        resp.raise_for_status()
        answer = resp.json()["message"].get("content", "").strip()
        # strip thinking block if leaked
        if "</think>" in answer:
            answer = answer[answer.index("</think>") + len("</think>"):].strip()
        answer = answer.strip('"').strip()
        if answer and answer != "null" and answer in dept_list:
            log.info("Fallback LLM dept: %s", answer)
            return answer
    except Exception as e:
        log.warning("Fallback LLM dept routing failed: %s", e)
    return None


# ─── Dedup ────────────────────────────────────────────────────────────────────

def _dedup(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    seen: dict[str, RetrievedChunk] = {}
    for c in chunks:
        if c.doc_chunk_id not in seen:
            seen[c.doc_chunk_id] = c
        elif (c.rerank_score or 0) > (seen[c.doc_chunk_id].rerank_score or 0):
            seen[c.doc_chunk_id] = c
    return list(seen.values())


# ─── Prompt builder ───────────────────────────────────────────────────────────

def build_prompt(query: str, chunks: list[RetrievedChunk]) -> tuple[str, str]:
    ctx_parts = []
    for i, c in enumerate(chunks, 1):
        date_str = c.meeting_date or f"{c.year}-{c.month:02d}"
        header   = f"[{i}] {c.doc_id} | {c.company} | {c.dept} | {date_str}"
        ctx_parts.append(f"{header}\n{c.chunk}")

    context = "\n\n---\n\n".join(ctx_parts)
    system = (
        "あなたは共立電機グループの内部文書に基づいて質問に答えるアナリストです。\n"
        "以下のルールに従ってください：\n"
        "1. 回答は提供された文書のみを根拠にする。文書にない情報は推測しない。\n"
        "2. 各主張には出典を [doc_id | 日付] 形式で明示する。\n"
        "3. 複数の文書に矛盾がある場合は、その旨を明記する。\n"
        "4. 情報が不足している場合は「文書には記載なし」と答える。\n"
        "5. 日本語で回答すること。"
        "6. 段階的に考えましょう。まず理由を考え、それから行動しましょう。"
    )
    user = f"## 参照文書\n\n{context}\n\n## 質問\n\n{query}"
    return system, user


# ─── Ollama synthesis call ────────────────────────────────────────────────────

def call_ollama(system: str, user: str, think: bool = True) -> dict:
    payload = {
        "model":  SYNTH_MODEL,
        "think":  think,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "options": {
            "temperature": 0.6,
            "top_p":       0.95,
            "top_k":       20,
            "num_ctx":     32768,
            "num_predict": 8192,
        },
    }
    log.info("Calling %s (think=%s) ...", SYNTH_MODEL, think)
    resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    msg  = data["message"]
    return {
        "thinking":   msg.get("thinking"),
        "answer":     msg.get("content", ""),
        "eval_count": data.get("eval_count"),
    }


# ─── Programmatic API ─────────────────────────────────────────────────────────

def synthesize(
    query:  str,
    chunks: list[RetrievedChunk],
    think:  bool = True,
) -> dict:
    """Callable from evaluate.py. Synthesizes answer from pre-retrieved chunks."""
    system, user = build_prompt(query, chunks)
    return call_ollama(system, user, think=think)


# ─── Save results ─────────────────────────────────────────────────────────────

def save_results(query: str, chunks: list, results: dict, save_dir: str):
    path = Path(save_dir)
    path.mkdir(exist_ok=True, parents=True)
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_query = "".join([c if c.isalnum() else "_" for c in query[:20]])
    fullpath   = path / f"{timestamp}_{safe_query}.json"
    output = {
        "metadata": {"query": query, "timestamp": timestamp,
                     "model": SYNTH_MODEL, "tokens": results.get("eval_count")},
        "thinking": results.get("thinking"),
        "answer":   results.get("answer"),
        "sources":  [{"doc_id": c.doc_id, "company": c.company,
                      "date": c.meeting_date or f"{c.year}-{c.month}",
                      "content": c.chunk} for c in chunks],
    }
    with open(fullpath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info("Result archived to: %s", fullpath)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="RAG synthesis with Qwen3-30B")
    parser.add_argument("query",               help="Natural language query (Japanese)")
    parser.add_argument("--year",     type=int, default=None)
    parser.add_argument("--month",    type=int, default=None)
    parser.add_argument("--company",  type=str, default=None)
    parser.add_argument("--dept",     type=str, default=None)
    parser.add_argument("--section",  type=str, default=None)
    parser.add_argument("--top-k",    type=int, default=8, dest="top_k")
    parser.add_argument("--no-rerank",      action="store_true")
    parser.add_argument("--no-think",       action="store_true")
    parser.add_argument("--no-think-trace", action="store_true")
    parser.add_argument("--save", type=str, nargs="?", const="results")
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Device: %s", device)

    embed_tok, embed_mod   = load_embed_model(device)
    rerank_tok, rerank_mod = (None, None) if args.no_rerank else load_rerank_model(device)
    sudachi_tok            = build_sudachi()

    # ── Taxonomy pass ────────────────────────────────────────────────────────
    tax = taxonomy_pass(args.query)
    log.info("Taxonomy: companies=%s depts=%s sections=%s periods=%s",
             tax["companies"], tax["depts"], tax["sections"], tax["periods"])

    # ── Fallback LLM dept routing if taxonomy found nothing ──────────────────
    if not tax["depts"] and not args.dept:
        company = args.company or (tax["companies"][0] if tax["companies"] else "共立電機製作所")
        fallback = _fallback_dept(args.query, company)
        if fallback:
            tax["depts"] = [fallback]

    # ── Build filter combinations ────────────────────────────────────────────
    combos = build_filter_combos(
        tax,
        cli_company = args.company,
        cli_dept    = args.dept,
        cli_section = args.section,
        cli_year    = args.year,
        cli_month   = args.month,
    )
    log.info("%d filter combination(s):", len(combos))
    for i, c in enumerate(combos, 1):
        log.info("  [%d] %s", i, c)

    # ── Sequential retrieval (GPU models not thread-safe) ──────────────────
    all_chunks: list[RetrievedChunk] = []

    def _run(combo: dict) -> list[RetrievedChunk]:
        return retrieve(
            query        = args.query,
            embed_tok    = embed_tok,
            embed_mod    = embed_mod,
            rerank_tok   = rerank_tok,
            rerank_mod   = rerank_mod,
            sudachi_tok  = sudachi_tok,
            device       = device,
            year         = combo["year"],
            month        = combo["month"],
            company      = combo["company"],
            dept         = combo["dept"],
            section      = combo["section"],
            doc_type     = combo["doc_type"],
            top_k        = args.top_k,
            no_rerank    = args.no_rerank,
        )

    # GPU models (embed + rerank) are not thread-safe — run sequentially
    for i, combo in enumerate(combos, 1):
        result = _run(combo)
        log.info("  combo %d/%d %s → %d chunks", i, len(combos), combo, len(result))
        all_chunks.extend(result)

    chunks = _dedup(all_chunks)
    log.info("Total after dedup: %d chunks", len(chunks))

    if not chunks:
        print("No relevant chunks found.")
        return

    log.info("Synthesizing over %d chunks ...", len(chunks))
    system, user = build_prompt(args.query, chunks)
    result = call_ollama(system, user, think=not args.no_think)

    if args.save and "answer" in result:
        save_results(args.query, chunks, result, args.save)

    sep = "=" * 70
    print(f"\n{sep}")
    print(f"Query  : {args.query}")
    print(f"Chunks : {len(chunks)}  |  Tokens: {result.get('eval_count', '?')}")
    print(sep)

    if result["thinking"] and not args.no_think_trace:
        print("\n[THINKING]\n")
        print(result["thinking"])
        print(f"\n{'-'*70}\n")

    print("[ANSWER]\n")
    print(result["answer"])

    print(f"\n{sep}")
    print("Sources:")
    for i, c in enumerate(chunks, 1):
        date_str = c.meeting_date or f"{c.year}-{c.month:02d}"
        print(f"  [{i}] {c.doc_id} | {c.company} | {c.dept} | {date_str}")
    print(sep)


if __name__ == "__main__":
    main()
