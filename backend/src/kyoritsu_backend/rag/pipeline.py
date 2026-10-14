"""The indexing contract shared by API submission and worker publication."""


def indexing_configuration(settings):
    settings.validate_model_revisions()
    return {
        "embedding_model": settings.embed_model,
        "embedding_revision": settings.embed_revision,
        "backend": settings.model_backend,
        "parser": settings.parser,
        "chunker": "heading-table-token-v2",
        "tokenizer": "fixture" if settings.model_backend == "test" else "sudachi-B",
        "summary_model": settings.summary_model if settings.enable_summary else None,
        "summary_prompt": "chunk-summary-v1" if settings.enable_summary else None,
    }
