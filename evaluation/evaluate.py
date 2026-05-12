# pyrefly: ignore [missing-import]
"""
evaluate.py — RAGAS + DeepEval evaluation with Qwen3-8B as judge.

Runs each ground-truth question through two pipeline configs:
  Config A: BM25 + Vector → RRF  (no reranker)
  Config B: BM25 + Vector → RRF → bge-reranker  (full pipeline)

RAGAS metrics  (no overlap): Faithfulness, ResponseRelevancy,
                              ContextPrecision, ContextRecall
DeepEval metrics (no overlap): ContextualRelevancy, Hallucination,
                                AnswerRelevancy

Judge LLM: Qwen/Qwen3-8B via HuggingFace transformers

Usage:
    python evaluate.py                          # uses evaluation/ground_truth.json
    python evaluate.py --gt custom.json         # custom ground truth file
    python evaluate.py --config a               # run only Config A
    python evaluate.py --limit 5                # first 5 questions only (smoke)
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# pyrefly: ignore [missing-import]
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM  # pyrefly: ignore

# ─── Path setup ───────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "retrieval"))

from retrieve import (   # pyrefly: ignore
    retrieve, load_embed_model, load_rerank_model, build_sudachi,
)
from synthesize import synthesize, build_prompt, call_ollama  # pyrefly: ignore

# ─── Config ───────────────────────────────────────────────────────────────────
JUDGE_MODEL    = "Qwen/Qwen3-8B"
DEFAULT_GT     = Path(__file__).parent / "ground_truth.json"
RESULTS_DIR    = Path(__file__).parent / "results"
TOP_K          = 5

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ─── Qwen3-8B judge — shared wrapper ──────────────────────────────────────────

class Qwen3JudgeLLM:
    """Loads Qwen3-8B once; provides generate() for both RAGAS and DeepEval."""

    def __init__(self, device: str):
        log.info("Loading judge model %s ...", JUDGE_MODEL)
        self.tokenizer = AutoTokenizer.from_pretrained(JUDGE_MODEL)
        self.model     = AutoModelForCausalLM.from_pretrained(
            JUDGE_MODEL, torch_dtype=torch.bfloat16
        ).to(device).eval()
        self.device    = device
        log.info("Judge model ready.")

    def generate(self, prompt: str, max_new_tokens: int = 1024) -> str:
        messages = [{"role": "user", "content": "/no_think\n\n" + prompt}]
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = self.tokenizer([text], return_tensors="pt").to(self.device)
        with torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=0.1,
                do_sample=False,
            )
        new_tokens = out[0][inputs["input_ids"].shape[1]:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


# ─── RAGAS wrapper ────────────────────────────────────────────────────────────

def make_ragas_llm(judge: Qwen3JudgeLLM):
    """Wrap Qwen3JudgeLLM as a LangChain-compatible LLM for RAGAS."""
    from langchain_core.language_models.llms import BaseLLM  # pyrefly: ignore
    from langchain_core.outputs import LLMResult, Generation  # pyrefly: ignore

    class _RagasLLM(BaseLLM):
        _judge: object = None

        def __init__(self, judge_instance):
            super().__init__()
            object.__setattr__(self, "_judge", judge_instance)

        def _generate(self, prompts, stop=None, run_manager=None, **kwargs):
            results = []
            for p in prompts:
                text = self._judge.generate(p)
                results.append([Generation(text=text)])
            return LLMResult(generations=results)

        async def _agenerate(self, prompts, stop=None, run_manager=None, **kwargs):
            return self._generate(prompts, stop, run_manager, **kwargs)

        @property
        def _llm_type(self):
            return "qwen3-8b-judge"

    return _RagasLLM(judge)


def run_ragas(questions, answers_a, answers_b, contexts_a, contexts_b, ground_truths):
    """Run RAGAS on both configs; return (result_a, result_b)."""
    from ragas import EvaluationDataset, SingleTurnSample, evaluate  # pyrefly: ignore
    from ragas.metrics import Faithfulness, ResponseRelevancy, ContextPrecision, ContextRecall  # pyrefly: ignore
    from ragas.llms import LangchainLLMWrapper  # pyrefly: ignore
    from langchain_huggingface import HuggingFaceEmbeddings  # pyrefly: ignore

    # Use a lightweight embedding for RAGAS answer_relevancy scoring
    ragas_embeddings = HuggingFaceEmbeddings(
        model_name="intfloat/multilingual-e5-small",
        model_kwargs={"device": "cuda" if torch.cuda.is_available() else "cpu"},
    )

    metrics = [Faithfulness(), ResponseRelevancy(), ContextPrecision(), ContextRecall()]

    results = {}
    for config_name, answers, contexts in [
        ("config_a", answers_a, contexts_a),
        ("config_b", answers_b, contexts_b),
    ]:
        samples = [
            SingleTurnSample(
                user_input    = q,
                response      = a,
                retrieved_contexts = c,
                reference     = gt,
            )
            for q, a, c, gt in zip(questions, answers, contexts, ground_truths)
        ]
        dataset = EvaluationDataset(samples=samples)
        log.info("Running RAGAS for %s (%d samples) ...", config_name, len(samples))
        result = evaluate(dataset, metrics=metrics)
        results[config_name] = result
        log.info("RAGAS %s done.", config_name)

    return results["config_a"], results["config_b"]


# ─── DeepEval wrapper ─────────────────────────────────────────────────────────

def make_deepeval_llm(judge: Qwen3JudgeLLM):
    from deepeval.models import DeepEvalBaseLLM  # pyrefly: ignore

    class _DeepEvalJudge(DeepEvalBaseLLM):
        def __init__(self, judge_instance):
            self._judge = judge_instance

        def load_model(self):
            return self._judge.model

        def generate(self, prompt: str, schema=None):
            response = self._judge.generate(prompt)
            if schema is not None:
                # attempt JSON parse for structured output
                import re, json as _json
                match = re.search(r"\{.*\}", response, re.DOTALL)
                if match:
                    try:
                        return schema(**_json.loads(match.group())), 0.0
                    except Exception:
                        pass
            return response, 0.0

        async def a_generate(self, prompt: str, schema=None):
            return self.generate(prompt, schema)

        def get_model_name(self) -> str:
            return "Qwen3-8B"

    return _DeepEvalJudge(judge)


def run_deepeval(questions, answers_a, answers_b, contexts_a, contexts_b,
                 ground_truths, deepeval_llm):
    from deepeval.metrics import (  # pyrefly: ignore
        ContextualRelevancyMetric, HallucinationMetric, AnswerRelevancyMetric,
    )
    from deepeval.test_case import LLMTestCase  # pyrefly: ignore
    from deepeval import evaluate as de_evaluate  # pyrefly: ignore

    metrics = [
        ContextualRelevancyMetric(model=deepeval_llm, include_reason=True),
        HallucinationMetric(model=deepeval_llm,       include_reason=True),
        AnswerRelevancyMetric(model=deepeval_llm,     include_reason=True),
    ]

    results = {}
    for config_name, answers, contexts in [
        ("config_a", answers_a, contexts_a),
        ("config_b", answers_b, contexts_b),
    ]:
        test_cases = [
            LLMTestCase(
                input            = q,
                actual_output    = a,
                retrieval_context= c,
                expected_output  = gt,
            )
            for q, a, c, gt in zip(questions, answers, contexts, ground_truths)
        ]
        log.info("Running DeepEval for %s (%d cases) ...", config_name, len(test_cases))
        result = de_evaluate(test_cases, metrics, print_results=False)
        results[config_name] = result
        log.info("DeepEval %s done.", config_name)

    return results["config_a"], results["config_b"]


# ─── Comparison printer ───────────────────────────────────────────────────────

def print_comparison(ragas_a, ragas_b, de_a, de_b):
    sep = "=" * 70
    print(f"\n{sep}")
    print("EVALUATION RESULTS — Config A (RRF only) vs Config B (RRF+Reranker)")
    print(sep)

    print("\n── RAGAS metrics ────────────────────────────────────────────────")
    ragas_a_scores = ragas_a.to_pandas().mean(numeric_only=True)
    ragas_b_scores = ragas_b.to_pandas().mean(numeric_only=True)
    print(f"{'Metric':<30} {'Config A':>10} {'Config B':>10} {'Delta':>10}")
    print("-" * 62)
    for col in ragas_a_scores.index:
        a_val = ragas_a_scores[col]
        b_val = ragas_b_scores.get(col, float("nan"))
        delta = b_val - a_val
        print(f"{col:<30} {a_val:>10.4f} {b_val:>10.4f} {delta:>+10.4f}")

    print("\n── DeepEval metrics ─────────────────────────────────────────────")
    def de_avg(de_result, metric_name):
        scores = [
            tc.metrics_data[i].score
            for tc in de_result.test_results
            for i, m in enumerate(tc.metrics_data)
            if metric_name.lower() in m.name.lower()
        ]
        return sum(scores) / len(scores) if scores else float("nan")

    de_metrics = ["ContextualRelevancy", "Hallucination", "AnswerRelevancy"]
    print(f"{'Metric':<30} {'Config A':>10} {'Config B':>10} {'Delta':>10}")
    print("-" * 62)
    for m in de_metrics:
        a_val = de_avg(de_a, m)
        b_val = de_avg(de_b, m)
        delta = b_val - a_val
        print(f"{m:<30} {a_val:>10.4f} {b_val:>10.4f} {delta:>+10.4f}")

    print(f"\n{sep}")
    print("Positive delta = Config B (reranker) better")
    print(sep)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gt",     type=Path, default=DEFAULT_GT,
                        help="Ground truth JSON (default: evaluation/ground_truth.json)")
    parser.add_argument("--config", choices=["a", "b", "both"], default="both")
    parser.add_argument("--limit",  type=int, default=None,
                        help="Limit to first N questions (smoke test)")
    args = parser.parse_args()

    if not args.gt.exists():
        log.error("Ground truth not found: %s — run generate_ground_truth.py first", args.gt)
        sys.exit(1)

    ground_truth_data = json.loads(args.gt.read_text(encoding="utf-8"))
    if args.limit:
        ground_truth_data = ground_truth_data[:args.limit]

    log.info("Loaded %d Q&A pairs from %s", len(ground_truth_data), args.gt)

    questions     = [d["question"]     for d in ground_truth_data]
    ground_truths = [d["ground_truth"] for d in ground_truth_data]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Device: %s", device)

    # Load retrieval models
    embed_tok, embed_mod   = load_embed_model(device)
    rerank_tok, rerank_mod = load_rerank_model(device)
    sudachi_tok            = build_sudachi()

    # Load judge
    judge        = Qwen3JudgeLLM(device)
    deepeval_llm = make_deepeval_llm(judge)

    answers_a, contexts_a = [], []
    answers_b, contexts_b = [], []

    for i, (q, gt_item) in enumerate(zip(questions, ground_truth_data), 1):
        log.info("[%d/%d] %s", i, len(questions), q[:80])
        year    = gt_item.get("year")
        company = gt_item.get("company")

        # Config A — no reranker
        chunks_a = retrieve(
            query=q, embed_tok=embed_tok, embed_mod=embed_mod,
            rerank_tok=None, rerank_mod=None,
            sudachi_tok=sudachi_tok, device=device,
            year=year, company=company, top_k=TOP_K, no_rerank=True,
        )
        result_a = synthesize(q, chunks_a, think=True)
        answers_a.append(result_a["answer"])
        contexts_a.append([c.chunk for c in chunks_a])

        # Config B — full pipeline
        chunks_b = retrieve(
            query=q, embed_tok=embed_tok, embed_mod=embed_mod,
            rerank_tok=rerank_tok, rerank_mod=rerank_mod,
            sudachi_tok=sudachi_tok, device=device,
            year=year, company=company, top_k=TOP_K, no_rerank=False,
        )
        result_b = synthesize(q, chunks_b, think=True)
        answers_b.append(result_b["answer"])
        contexts_b.append([c.chunk for c in chunks_b])

        log.info("  A tokens=%s  B tokens=%s",
                 result_a.get("eval_count","?"), result_b.get("eval_count","?"))

    # Save raw results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    raw = {
        "questions": questions, "ground_truths": ground_truths,
        "answers_a": answers_a, "contexts_a": contexts_a,
        "answers_b": answers_b, "contexts_b": contexts_b,
    }
    (RESULTS_DIR / "raw_answers.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Raw answers saved → %s", RESULTS_DIR / "raw_answers.json")

    # RAGAS
    ragas_llm = make_ragas_llm(judge)
    ragas_a, ragas_b = run_ragas(
        questions, answers_a, answers_b,
        contexts_a, contexts_b, ground_truths,
    )

    # DeepEval
    de_a, de_b = run_deepeval(
        questions, answers_a, answers_b,
        contexts_a, contexts_b, ground_truths,
        deepeval_llm,
    )

    # Save metric scores
    ra_df = ragas_a.to_pandas()
    rb_df = ragas_b.to_pandas()
    ra_df.to_json(RESULTS_DIR / "ragas_config_a.json", orient="records", force_ascii=False)
    rb_df.to_json(RESULTS_DIR / "ragas_config_b.json", orient="records", force_ascii=False)

    print_comparison(ragas_a, ragas_b, de_a, de_b)


if __name__ == "__main__":
    main()
