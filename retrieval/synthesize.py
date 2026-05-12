# pyrefly: ignore [missing-import]
"""
synthesize.py — Answer synthesis using Qwen3-30B thinking mode via Ollama.

Receives retrieved chunks from retrieve.py, constructs a context-grounded
prompt, and calls Qwen3:30b with think=True so the model explicitly reasons
over the evidence before writing the final answer.

The thinking trace is shown (or suppressed with --no-think-trace) and the
final answer includes inline citations [doc_id | date].

Usage:
    python synthesize.py "共立電機製作所の2024年品質報告の主要課題は？"
    python synthesize.py --year 2024 --top-k 5 "品質管理の改善点は？"
    python synthesize.py --no-think-trace --no-rerank "簡単な質問"
"""
import argparse
import json
import logging
import sys
from pathlib import Path
import requests
import time 
from datetime import datetime

def save_results(query : str, chunks: list, results: dict, save_dir: str):

    path = Path(save_dir)
    path.mkdir(exist_ok=True, parents=True)

    # unique name creation
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_query = "".join([c if c.isalnum() else "_" for c in query[:20]])
    filename= f"{timestamp}_{safe_query}.json"
    fullpath = path / filename
    
    # output creation
    output = {
        'metadata' : {
            'query' : query,
            "timestamp": timestamp,
            "model" : SYNTH_MODEL,
            "tokens" : results.get("eval_count")

        },
        "thinking" : results.get("thinking"),
        "answer" : results.get("answer"),
        "sources" : [ {
            "doc_id" : c.doc_id,
            "company" :c.company,
            "date" : c.meeting_date or  f"{c.year}-{c.month}",
            "content" : c.chunk
        }
            for c in chunks
        ]
    }

    with open(fullpath, 'w', encoding='utf-8') as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    log.info("Result archived to : %s" , fullpath)

# add retrieval dir to path so we can import retrieve
sys.path.insert(0, str(Path(__file__).parent))
from retrieve import ( 
    retrieve , load_embed_model, load_rerank_model, build_sudachi,
    RetrievedChunk, FINAL_K,
)

# pyrefly: ignore [missing-import]
import torch

# ─── Config ───────────────────────────────────────────────────────────────────
OLLAMA_URL    = "http://localhost:11434/api/chat"
SYNTH_MODEL   = "qwen3:30b"
OLLAMA_TIMEOUT = 300   # seconds

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ─── Prompt builder ───────────────────────────────────────────────────────────

def build_prompt(query: str, chunks: list[RetrievedChunk]) -> str:
    """Build the system + user prompt with retrieved context."""
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
    )

    user = (
        f"## 参照文書\n\n{context}\n\n"
        f"## 質問\n\n{query}"
    )

    return system, user


# ─── Ollama call ──────────────────────────────────────────────────────────────

def call_ollama(system: str, user: str, think: bool = True) -> dict:
    """
    Call Ollama chat API with optional thinking mode.
    Returns dict with keys: thinking (str|None), answer (str).
    """
    payload = {
        "model": SYNTH_MODEL,
        "think": think,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "options": {
            "temperature": 0.6,    # Qwen3 recommended for thinking mode
            "top_p": 0.95,
            "top_k": 20,
            "num_ctx": 16384,
            "num_predict": 6144,   # cap answer length; prevents context-dump in non-think mode
        },
    }

    log.info("Calling %s (think=%s) ...", SYNTH_MODEL, think)
    resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    msg       = data["message"]
    thinking  = msg.get("thinking")   # present when think=True
    answer    = msg.get("content", "")

    return {"thinking": thinking, "answer": answer, "eval_count": data.get("eval_count")}


# ─── Programmatic API ─────────────────────────────────────────────────────────

def synthesize(
    query:      str,
    chunks:     list[RetrievedChunk],
    think:      bool = True,
) -> dict:
    """
    Synthesize an answer from pre-retrieved chunks.
    Returns dict with keys: answer (str), thinking (str|None), eval_count (int).
    Callable from evaluate.py without going through CLI.
    """
    system, user = build_prompt(query, chunks)
    return call_ollama(system, user, think=think)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="RAG synthesis with Qwen3-30B thinking")
    parser.add_argument("query", help="Natural language query (Japanese)")
    parser.add_argument("--year",           type=int,  default=None)
    parser.add_argument("--month",          type=int,  default=None)
    parser.add_argument("--company",        type=str,  default=None)
    parser.add_argument("--top-k",          type=int,  default=FINAL_K, dest="top_k")
    parser.add_argument("--no-rerank",      action="store_true")
    parser.add_argument("--no-think",       action="store_true",
                        help="Disable thinking mode (faster, lower quality)")
    parser.add_argument("--no-think-trace", action="store_true",
                        help="Hide thinking trace in output (still runs thinking)")
    parser.add_argument("--save", type=str, nargs="?",const='results', help="Save results to disk. Optional: provide directory(default: './results') ")


    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Device: %s", device)

    # Load models
    embed_tok, embed_mod   = load_embed_model(device)
    rerank_tok, rerank_mod = (None, None) if args.no_rerank else load_rerank_model(device)
    sudachi_tok            = build_sudachi()

    # Retrieve
    log.info("Retrieving chunks for: %s", args.query)
    chunks = retrieve(
        query       = args.query,
        embed_tok   = embed_tok,
        embed_mod   = embed_mod,
        rerank_tok  = rerank_tok,
        rerank_mod  = rerank_mod,
        sudachi_tok = sudachi_tok,
        device      = device,
        year        = args.year,
        month       = args.month,
        company     = args.company,
        top_k       = args.top_k,
        no_rerank   = args.no_rerank,
    )

    if not chunks:
        print("No relevant chunks found.")
        return

    log.info("Retrieved %d chunks → synthesizing ...", len(chunks))

    # Build prompt and call model
    system, user = build_prompt(args.query, chunks)
    result = call_ollama(system, user, think=not args.no_think)

    if args.save and "answer" in result:
        save_results(args.query, chunks, result, args.save)

    # Output
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"Query  : {args.query}")
    print(f"Chunks : {len(chunks)}  |  Tokens generated: {result.get('eval_count', '?')}")
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
