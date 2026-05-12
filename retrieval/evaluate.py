# pyrefly: ignore [missing-import]
"""
evaluate.py — RAGAS + DeepEval evaluation with ablation (RRF-only vs RRF+reranker).

Judge LLM: Qwen/Qwen3-8B loaded locally via HuggingFace transformers.

RAGAS metrics  : Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall
DeepEval metrics: ContextualRelevancy, Hallucination, AnswerRelevancy

Runs each question twice (ablation) and writes:
  - logs/eval_results.json   — full per-question scores
  - logs/eval_summary.json   — aggregate scores per config + category

Usage:
    python evaluate.py                              # full 30-question eval
    python evaluate.py --dataset eval_dataset.json  # custom dataset path
    python evaluate.py --limit 5                    # smoke test (first 5 Qs)
"""
import argparse
import gc
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
# pyrefly: ignore [missing-import]
import torch
# pyrefly: ignore [missing-import]
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline

# ─── Path setup ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from retrieve import (  # pyrefly: ignore
    load_embed_model, load_rerank_model, build_sudachi,
    retrieve_rrf_pool, finish_retrieve,
)
from synthesize import synthesize  # pyrefly: ignore

OLLAMA_URL  = "http://localhost:11434/api/chat"
SYNTH_MODEL = "qwen3:30b"


# ─── VRAM management ──────────────────────────────────────────────────────────

def unload_ollama():
    """Tell Ollama to evict the synthesis model from VRAM immediately."""
    try:
        requests.post(OLLAMA_URL, json={
            "model": SYNTH_MODEL, "keep_alive": 0,
            "messages": [{"role": "user", "content": ""}],
        }, timeout=10)
        log.info("Ollama: %s unloaded from VRAM.", SYNTH_MODEL)
    except Exception as e:
        log.warning("Ollama unload failed (non-fatal): %s", e)


def free_retrieval_vram(*model_refs):
    """Delete PyTorch model references + clear CUDA cache."""
    for ref in model_refs:
        if ref is not None:
            del ref
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    log.info("Retrieval models freed. VRAM available: %.1f GB",
             torch.cuda.mem_get_info()[0] / 1e9 if torch.cuda.is_available() else 0)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

JUDGE_MODEL     = "Qwen/Qwen3-8B"
DEFAULT_DATASET = Path(__file__).parent / "eval_dataset.json"
RESULTS_DIR     = Path(__file__).parent.parent / "logs"


def setup_file_logging(run_id: str) -> None:
    log_path = RESULTS_DIR / f"eval_{run_id}.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logging.getLogger().addHandler(fh)
    log.info("File log → %s", log_path)


# ─── Checkpoint helpers ───────────────────────────────────────────────────────

def _ckpt_path() -> Path:
    return RESULTS_DIR / "eval_checkpoint.jsonl"


def load_checkpoint() -> dict:
    """Returns {(q_id, config): record} for all already-completed questions."""
    done: dict = {}
    p = _ckpt_path()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done[(rec["id"], rec["config"])] = rec
        log.info("Checkpoint: %d records loaded from %s", len(done), p)
    return done


def append_checkpoint(rec: dict) -> None:
    with open(_ckpt_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ─── Qwen3-8B judge — shared wrapper for RAGAS + DeepEval ─────────────────────

class Qwen3Judge:
    """Local Qwen3-8B inference for LLM-as-judge. Single instance, shared."""

    def __init__(self, device: str):
        log.info("Loading judge model %s ...", JUDGE_MODEL)
        self.tokenizer = AutoTokenizer.from_pretrained(JUDGE_MODEL)
        model = AutoModelForCausalLM.from_pretrained(
            JUDGE_MODEL,
            torch_dtype=torch.bfloat16,
            device_map=device,
        )
        self.pipe = pipeline(
            "text-generation",
            model=model,
            tokenizer=self.tokenizer,
            max_new_tokens=2048,
            temperature=0.1,
            do_sample=True,
            pad_token_id=self.tokenizer.eos_token_id,
        )
        log.info("Judge model ready.")

    def generate(self, prompt: str) -> str:
        msgs = [{"role": "user", "content": prompt}]
        text = self.tokenizer.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        out = self.pipe(text, return_full_text=False)
        return out[0]["generated_text"].strip()


# ─── RAGAS wrapper ────────────────────────────────────────────────────────────

def build_ragas_llm(judge: Qwen3Judge):
    """Wrap Qwen3Judge as a LangChain-compatible LLM for RAGAS."""
    from langchain_core.language_models.llms import LLM
    from langchain_core.callbacks.manager import CallbackManagerForLLMRun

    class _LocalLLM(LLM):
        @property
        def _llm_type(self) -> str:
            return "qwen3-8b-local"

        def _call(self, prompt: str,
                  stop=None,
                  run_manager: Optional[CallbackManagerForLLMRun] = None,
                  **kwargs) -> str:
            return judge.generate(prompt)

    from langchain_core.embeddings import Embeddings
    import numpy as np

    class _DummyEmbeddings(Embeddings):
        """RAGAS requires an embeddings model; use a dummy since we supply contexts."""
        def embed_documents(self, texts):
            return [[0.0] * 768] * len(texts)
        def embed_query(self, text):
            return [0.0] * 768

    return _LocalLLM(), _DummyEmbeddings()


def run_ragas(questions, answers, contexts_list, ground_truths, judge: Qwen3Judge) -> dict:
    import warnings
    from ragas import evaluate
    from ragas.run_config import RunConfig  # pyrefly: ignore
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from ragas.metrics import (  # pyrefly: ignore
            faithfulness, answer_relevancy,
            context_precision, context_recall,
        )
    from datasets import Dataset

    llm, embeddings = build_ragas_llm(judge)

    data = Dataset.from_dict({
        "question":     questions,
        "answer":       answers,
        "contexts":     contexts_list,
        "ground_truth": ground_truths,
    })

    # inject local LLM into metrics
    for metric in [faithfulness, answer_relevancy, context_precision, context_recall]:
        metric.llm = llm
        if hasattr(metric, "embeddings"):
            metric.embeddings = embeddings

    result = evaluate(
        data,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        raise_exceptions=False,
        run_config=RunConfig(max_workers=1, timeout=300),
    )
    df = result.to_pandas()
    ragas_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    return {k: df[k].tolist() if k in df.columns else [None] * len(questions)
            for k in ragas_keys}


# ─── DeepEval wrapper ─────────────────────────────────────────────────────────

def build_deepeval_llm(judge: Qwen3Judge):
    from deepeval.models.base_model import DeepEvalBaseLLM

    class _Qwen3Local(DeepEvalBaseLLM):
        def __init__(self):
            super().__init__()

        def load_model(self):
            return judge

        def generate(self, prompt: str, schema=None) -> str:
            return judge.generate(prompt)

        async def a_generate(self, prompt: str, schema=None) -> str:
            return self.generate(prompt)

        def get_model_name(self) -> str:
            return "qwen3-8b-local"

    return _Qwen3Local()


def run_deepeval(questions, answers, contexts_list, ground_truths, judge: Qwen3Judge) -> list[dict]:
    from deepeval.metrics import (
        HallucinationMetric,
        AnswerRelevancyMetric,
    )
    from deepeval.test_case import LLMTestCase

    dv_llm = build_deepeval_llm(judge)

    scores = []
    for i, (q, a, ctx, gt) in enumerate(zip(questions, answers, contexts_list, ground_truths)):
        ctx3 = ctx[:3]  # top-3 chunks; ContextualRelevancy dropped (per-stmt JSON too complex for 8B)
        tc = LLMTestCase(
            input=q,
            actual_output=a,
            context=ctx3,           # required by HallucinationMetric
            retrieval_context=ctx3,
            expected_output=gt,
        )
        row = {}
        for metric in [
            HallucinationMetric(model=dv_llm,   include_reason=True),
            AnswerRelevancyMetric(model=dv_llm,  include_reason=True),
        ]:
            try:
                metric.measure(tc)
                row[metric.__class__.__name__] = {"score": metric.score, "reason": metric.reason}
            except Exception as e:
                log.warning("DeepEval metric %s Q%d failed: %s", metric.__class__.__name__, i + 1, e)
                row[metric.__class__.__name__] = {"score": None, "reason": str(e)}
        scores.append(row)
        log.info("  DeepEval Q%d scored: %s", i + 1,
                 {k: v["score"] for k, v in row.items()})
    return scores


# ─── Phase 1: retrieve + synthesize (shared RRF pool, checkpoint/resume) ─────

def _make_record(item: dict, config: str, answer: str, ctx_txts: list[str]) -> dict:
    return {
        "id":            item["id"],
        "doc_id":        item["doc_id"],
        "category":      item["category"],
        "question_type": item["question_type"],
        "config":        config,
        "question":      item["question"],
        "ground_truth":  item["ground_truth"],
        "answer":        answer,
        "contexts":      ctx_txts,
        "n_chunks":      len(ctx_txts),
    }


def retrieval_phase(
    items: list[dict],
    ablation: bool,
    embed_tok, embed_mod,
    rerank_tok, rerank_mod,
    sudachi_tok,
    device: str,
    think: bool,
    checkpoint: dict,
) -> tuple[list[dict], list[dict]]:
    """
    For each question: embed+BM25+vector+RRF once, then branch at reranking.
    Resumes from checkpoint; appends completed records to checkpoint file.
    Returns (records_a [rrf+reranker], records_b [rrf_only]).
    """
    records_a: list[dict] = []
    records_b: list[dict] = []

    for item in items:
        q_id = item["id"]
        q    = item["question"]
        need_a = (q_id, "rrf+reranker") not in checkpoint
        need_b = ablation and (q_id, "rrf_only") not in checkpoint

        if not need_a and not need_b:
            log.info("Q%d: skipped (checkpoint)", q_id)
            records_a.append(checkpoint[(q_id, "rrf+reranker")])
            if ablation:
                records_b.append(checkpoint[(q_id, "rrf_only")])
            continue

        log.info("Q%d: %s", q_id, q[:60])

        # Embed + BM25 + vector + RRF — computed once for both configs
        try:
            pool = retrieve_rrf_pool(
                query=q, embed_tok=embed_tok, embed_mod=embed_mod,
                sudachi_tok=sudachi_tok, device=device,
            )
        except Exception as e:
            log.error("  Q%d RRF pool failed: %s", q_id, e)
            pool = []

        # Config A: rrf+reranker
        if need_a:
            try:
                chunks = finish_retrieve(q, pool, rerank_tok, rerank_mod, device)
                ans    = synthesize(q, chunks, think=think)["answer"]
                ctx    = [c.chunk for c in chunks]
            except Exception as e:
                log.error("  Q%d rrf+reranker failed: %s", q_id, e)
                ans, ctx = "", []
            rec_a = _make_record(item, "rrf+reranker", ans, ctx)
            append_checkpoint(rec_a)
            checkpoint[(q_id, "rrf+reranker")] = rec_a
            log.info("  rrf+reranker: %d chunks, answer=%d chars", len(ctx), len(ans))
        records_a.append(checkpoint[(q_id, "rrf+reranker")])

        # Config B: rrf_only (ablation)
        if need_b:
            try:
                chunks = finish_retrieve(q, pool, None, None, device, no_rerank=True)
                ans    = synthesize(q, chunks, think=think)["answer"]
                ctx    = [c.chunk for c in chunks]
            except Exception as e:
                log.error("  Q%d rrf_only failed: %s", q_id, e)
                ans, ctx = "", []
            rec_b = _make_record(item, "rrf_only", ans, ctx)
            append_checkpoint(rec_b)
            checkpoint[(q_id, "rrf_only")] = rec_b
            log.info("  rrf_only: %d chunks, answer=%d chars", len(ctx), len(ans))
        if ablation:
            records_b.append(checkpoint[(q_id, "rrf_only")])

    return records_a, records_b


# ─── Phase 2: score (judge only in VRAM) ─────────────────────────────────────

def scoring_phase(records: list[dict], judge: Qwen3Judge) -> list[dict]:
    """Add RAGAS + DeepEval scores to records in-place. Returns updated records."""
    questions     = [r["question"]     for r in records]
    answers       = [r["answer"]       for r in records]
    contexts_list = [r["contexts"]     for r in records]
    ground_truths = [r["ground_truth"] for r in records]
    config_label  = records[0]["config"] if records else "unknown"

    log.info("[%s] RAGAS scoring ...", config_label)
    ragas_scores = run_ragas(questions, answers, contexts_list, ground_truths, judge)

    log.info("[%s] DeepEval scoring ...", config_label)
    deepeval_scores = run_deepeval(questions, answers, contexts_list, ground_truths, judge)

    ragas_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    for i, rec in enumerate(records):
        rec["ragas"] = {
            k: float(ragas_scores.get(k, [None] * len(records))[i] or 0)
            for k in ragas_keys
        }
        rec["deepeval"] = deepeval_scores[i] if i < len(deepeval_scores) else {}
        del rec["contexts"]   # keep JSON small; contexts already in eval_dataset.json

    return records


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset",     type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit",       type=int,  default=None)
    parser.add_argument("--no-ablation", action="store_true")
    parser.add_argument("--think",       action="store_true",
                        help="Enable Qwen3-30B thinking mode for synthesis (slower, higher quality)")
    parser.add_argument("--clear-checkpoint", action="store_true",
                        help="Ignore existing checkpoint and start fresh")
    args = parser.parse_args()

    if not args.dataset.exists():
        log.error("Dataset not found: %s — run generate_ground_truth.py first", args.dataset)
        sys.exit(1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    setup_file_logging(run_id)

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if args.limit:
        dataset = dataset[:args.limit]
    log.info("Loaded %d eval items | think=%s | ablation=%s",
             len(dataset), args.think, not args.no_ablation)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Device: %s", device)

    checkpoint = {} if args.clear_checkpoint else load_checkpoint()

    # ── Phase 1: retrieve + synthesize (shared RRF pool per question) ─────────
    embed_tok, embed_mod   = load_embed_model(device)
    rerank_tok, rerank_mod = load_rerank_model(device)
    sudachi_tok            = build_sudachi()

    log.info("=== Phase 1: retrieve+synthesize (shared RRF, both configs) ===")
    records_a, records_b = retrieval_phase(
        items=dataset, ablation=not args.no_ablation,
        embed_tok=embed_tok, embed_mod=embed_mod,
        rerank_tok=rerank_tok, rerank_mod=rerank_mod,
        sudachi_tok=sudachi_tok, device=device,
        think=args.think, checkpoint=checkpoint,
    )

    # ── Free retrieval VRAM before loading judge ───────────────────────────────
    unload_ollama()
    free_retrieval_vram(embed_mod, rerank_mod)
    del embed_tok, embed_mod, rerank_tok, rerank_mod, sudachi_tok

    # ── Phase 2: scoring (Qwen3-8B judge only in VRAM) ────────────────────────
    judge = Qwen3Judge(device)

    log.info("=== Phase 2A: scoring RRF+reranker ===")
    records_a = scoring_phase(records_a, judge)

    if records_b:
        log.info("=== Phase 2B: scoring RRF-only ===")
        records_b = scoring_phase(records_b, judge)

    all_results = records_a + records_b

    out_path = RESULTS_DIR / f"eval_results_{run_id}.json"
    out_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Full results → %s", out_path)

    # also write stable "latest" symlink for convenience
    latest = RESULTS_DIR / "eval_results.json"
    latest.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = aggregate_summary(all_results)
    summary_path = RESULTS_DIR / "eval_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Summary → %s", summary_path)

    print_summary(summary)


def aggregate_summary(results: list[dict]) -> dict:
    from collections import defaultdict
    import statistics

    def avg(vals):
        clean = [v for v in vals if v is not None]
        return round(statistics.mean(clean), 4) if clean else None

    grouped = defaultdict(list)
    for r in results:
        grouped[r["config"]].append(r)

    summary = {}
    ragas_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]

    for config, items in grouped.items():
        cats = defaultdict(list)
        for it in items:
            cats[it["category"]].append(it)

        summary[config] = {
            "n": len(items),
            "ragas": {k: avg([it["ragas"].get(k) for it in items]) for k in ragas_keys},
            "deepeval": {
                metric: avg([
                    it["deepeval"].get(metric, {}).get("score")
                    for it in items
                ])
                for metric in ["HallucinationMetric", "AnswerRelevancyMetric"]
            },
            "by_category": {
                cat: {
                    "n": len(citems),
                    "ragas": {k: avg([it["ragas"].get(k) for it in citems]) for k in ragas_keys},
                }
                for cat, citems in cats.items()
            },
        }

    return summary


def print_summary(summary: dict):
    sep = "=" * 70
    print(f"\n{sep}")
    print("EVALUATION SUMMARY")
    print(sep)

    ragas_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    deval_keys = ["HallucinationMetric", "AnswerRelevancyMetric"]

    for config, data in summary.items():
        print(f"\n[{config.upper()}]  n={data['n']}")
        print("  RAGAS:")
        for k in ragas_keys:
            v = data["ragas"].get(k)
            print(f"    {k:<25} {v:.4f}" if v is not None else f"    {k:<25} N/A")
        print("  DeepEval:")
        for k in deval_keys:
            v = data["deepeval"].get(k)
            print(f"    {k:<25} {v:.4f}" if v is not None else f"    {k:<25} N/A")

        print("  By category:")
        for cat, cdata in data.get("by_category", {}).items():
            faithfulness = cdata["ragas"].get("faithfulness")
            print(f"    {cat:<20} faithfulness={faithfulness:.4f}" if faithfulness else f"    {cat}")

    print(f"\n{sep}")

    # Ablation delta
    if "rrf+reranker" in summary and "rrf_only" in summary:
        print("\nABLATION DELTA (rrf+reranker − rrf_only):")
        for k in ragas_keys:
            a = summary["rrf+reranker"]["ragas"].get(k)
            b = summary["rrf_only"]["ragas"].get(k)
            if a is not None and b is not None:
                print(f"  {k:<25} {a-b:+.4f}")
        print(sep)


if __name__ == "__main__":
    main()
