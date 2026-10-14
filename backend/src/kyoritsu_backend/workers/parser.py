"""Isolated parser process; diagnostics go to stderr, JSON pages to stdout."""


def parse(path, parser):
    if path.suffix != ".pdf":
        return [(1, path.read_text(encoding="utf-8"))]
    if parser == "marker":
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered

        converter = PdfConverter(artifact_dict=create_model_dict())
        text, _, _ = text_from_rendered(converter(str(path)))
        return [(None, text)]
    from pypdf import PdfReader

    return [(i + 1, page.extract_text() or "") for i, page in enumerate(PdfReader(path).pages)]


if __name__ == "__main__":
    import contextlib
    import json
    import sys
    from pathlib import Path

    with contextlib.redirect_stdout(sys.stderr):
        pages = parse(Path(sys.argv[1]), sys.argv[2])
    print(json.dumps(pages, ensure_ascii=False))
