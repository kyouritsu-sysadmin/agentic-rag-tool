"""Lazy model owner. One bounded executor; cancellation does not free a running GPU slot."""

import asyncio
import hashlib
import math
import re
from concurrent.futures import ThreadPoolExecutor
from kyoritsu_backend.core.errors import ApplicationError


class ModelProvider:
    def __init__(self, settings):
        self.settings = settings
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-model")
        self.pending = 0
        self.loaded = False

    async def call(self, function, *args):
        if self.pending >= self.settings.max_model_queue:
            raise ApplicationError(503, "Model queue is full; retry later")
        self.pending += 1
        future = asyncio.get_running_loop().run_in_executor(self.executor, function, *args)
        future.add_done_callback(lambda _: setattr(self, "pending", self.pending - 1))
        return await asyncio.shield(future)

    def _load(self):
        if self.loaded:
            return
        if self.settings.model_backend != "test":
            self.settings.validate_model_revisions()
            import torch
            from transformers import AutoTokenizer, AutoModel, AutoModelForSequenceClassification
            from sudachipy import dictionary, tokenizer

            self.torch = torch
            self.tok = AutoTokenizer.from_pretrained(
                self.settings.embed_model, revision=self.settings.embed_revision
            )
            self.model = (
                AutoModel.from_pretrained(
                    self.settings.embed_model, revision=self.settings.embed_revision
                )
                .to(self.settings.device)
                .eval()
            )
            if self.model.config.hidden_size != 768:
                raise RuntimeError("Embedding dimension does not match database")
            self.sudachi = dictionary.Dictionary().create()
            self.split_mode = tokenizer.Tokenizer.SplitMode.B
            if self.settings.enable_rerank:
                self.rtok = AutoTokenizer.from_pretrained(
                    self.settings.rerank_model, revision=self.settings.rerank_revision
                )
                self.rmodel = (
                    AutoModelForSequenceClassification.from_pretrained(
                        self.settings.rerank_model, revision=self.settings.rerank_revision
                    )
                    .to(self.settings.device)
                    .eval()
                )
        self.loaded = True

    def _tokens(self, text):
        self._load()
        if self.settings.model_backend == "test":
            return re.findall(r"[\w]+", text.lower())
        return [
            m.surface()
            for m in self.sudachi.tokenize(text, self.split_mode)
            if m.part_of_speech()[0] not in {"助詞", "助動詞", "補助記号", "空白"}
        ]

    def _encode(self, text, document):
        self._load()
        if self.settings.model_backend == "test":
            vec = [0.0] * 768
            for token in self._tokens(text):
                vec[int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % 768] += 1
            norm = math.sqrt(sum(v * v for v in vec)) or 1
            return [v / norm for v in vec]
        prefix = "検索文書: " if document else "検索クエリ: "
        encoded = self.tok(
            [prefix + text], return_tensors="pt", truncation=True, max_length=8192
        ).to(self.settings.device)
        with self.torch.no_grad():
            out = self.model(**encoded)
        mask = encoded["attention_mask"].unsqueeze(-1).float()
        pooled = (out.last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        return self.torch.nn.functional.normalize(pooled, p=2, dim=1)[0].cpu().tolist()

    async def embed(self, text, document=False):
        return await self.call(self._encode, text, document)

    async def tokens(self, text):
        return await self.call(self._tokens, text)

    def _rerank(self, query, chunks):
        self._load()
        if not self.settings.enable_rerank:
            raise ApplicationError(422, "Reranking is not enabled on this server")
        if self.settings.model_backend == "test":
            return chunks
        scores = []
        for i in range(0, len(chunks), 4):
            batch = [(query, c["chunk"]) for c in chunks[i : i + 4]]
            encoded = self.rtok(
                batch, padding=True, truncation=True, max_length=8192, return_tensors="pt"
            ).to(self.settings.device)
            with self.torch.no_grad():
                scores.extend(self.rmodel(**encoded).logits.view(-1).float().cpu().tolist())
        for chunk, score in zip(chunks, scores):
            chunk["rerank_score"] = score
        return sorted(chunks, key=lambda c: (-c["rerank_score"], c["doc_chunk_id"]))

    async def rerank(self, query, chunks):
        return await self.call(self._rerank, query, chunks)

    async def token_count(self, text):
        def count():
            self._load()
            return (
                len(text) if self.settings.model_backend == "test" else len(self.tok.encode(text))
            )

        return await self.call(count)

    async def close(self):
        await asyncio.to_thread(self.executor.shutdown, wait=True, cancel_futures=True)
