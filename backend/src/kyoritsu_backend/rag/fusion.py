def fuse(lexical: list[str], vector: list[str]) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in (lexical, vector):
        for i, key in enumerate(dict.fromkeys(ranking), 1):
            scores[key] = scores.get(key, 0) + 1 / (60 + i)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def balanced(groups: list[list[dict]], limit: int) -> list[dict]:
    """Round-robin across requested scopes, deduplicating immutable chunks."""
    result, seen = [], set()
    for i in range(max((len(g) for g in groups), default=0)):
        for group in groups:
            if i < len(group) and group[i]["doc_chunk_id"] not in seen:
                seen.add(group[i]["doc_chunk_id"])
                result.append(group[i])
                if len(result) == limit:
                    return result
    return result
