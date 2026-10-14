"""Token-bounded chunks with heading and table context on every fragment."""

import re

SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")


async def split_content(text, token_count, max_tokens=600):
    heading = ""
    chunks = []

    async def emit(lines, table=False):
        if not lines or not any(line.strip() for line in lines):
            return
        prefix = heading + "\n" if heading else ""
        body = "\n".join(lines)
        if table and len(lines) >= 2 and SEPARATOR.match(lines[1]):
            header = "\n".join(lines[:2])
            body = "\n".join(lines[2:])
            if not body.strip():
                body = header
            else:
                prefix += header + "\n"
        # Never silently discard a header or truncate its column names.
        if await token_count(prefix) >= max_tokens:
            raise ValueError("Heading/table header exceeds chunk token budget")
        while body:
            lo, hi = 0, len(body)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if await token_count(prefix + body[:mid]) <= max_tokens:
                    lo = mid
                else:
                    hi = mid - 1
            take = lo
            if not take:
                raise ValueError("Unable to split content within token budget")
            if take < len(body):
                boundary = max(body.rfind("\n", 0, take), body.rfind("。", 0, take))
                if boundary > take // 2:
                    take = boundary + 1
            chunk = prefix + body[:take]
            if await token_count(chunk) > max_tokens:
                raise ValueError("Unable to split content within token budget")
            chunks.append(
                dict(text=chunk, chunk_type="table" if table else "text", heading=heading)
            )
            body = body[take:]

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if re.match(r"^#{1,6}\s", lines[index]):
            heading = lines[index]
            index += 1
            continue
        table = lines[index].lstrip().startswith("|")
        block = []
        while index < len(lines):
            line = lines[index]
            if re.match(r"^#{1,6}\s", line) or line.lstrip().startswith("|") != table:
                break
            # A new header/separator pair starts another table, even without a blank line.
            if table and block and index + 1 < len(lines) and SEPARATOR.match(lines[index + 1]):
                break
            block.append(line)
            index += 1
        await emit(block, table)
    return chunks
