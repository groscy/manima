"""Build the grounding corpus (task 6.1, specs/generate).

Introspects the *installed* Manim CE package and upserts one snippet per public API symbol
(name, signature, first docstring line) into a Qdrant collection, tagged with the version.
Because it reads the installed package, the corpus is guaranteed to describe the exact
version in the render image (task 6.3) — the script asserts that installed == pinned and
refuses to build a mismatched corpus, which is the drift grounding exists to prevent.

Run inside WSL2 with Manim CE installed and Qdrant reachable:
    python scripts/build_corpus.py --qdrant http://localhost:6333 --collection manim-ce
"""

from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manima_server.version import MANIM_CE_VERSION  # noqa: E402


def build_snippets() -> list[dict]:
    import manim

    installed = getattr(manim, "__version__", "unknown")
    if installed != MANIM_CE_VERSION:
        raise SystemExit(
            f"installed Manim CE {installed} != pinned {MANIM_CE_VERSION}. Rebuild the "
            "render image first, or update version.MANIM_CE_VERSION — image, corpus, and "
            "artifact hash must agree (design D8)."
        )

    snippets: list[dict] = []
    for name in sorted(getattr(manim, "__all__", dir(manim))):
        if name.startswith("_"):
            continue
        obj = getattr(manim, name, None)
        if not (inspect.isclass(obj) or inspect.isfunction(obj)):
            continue
        try:
            sig = str(inspect.signature(obj))
        except (ValueError, TypeError):
            sig = "(...)"
        doc = (inspect.getdoc(obj) or "").strip().splitlines()
        summary = doc[0] if doc else ""
        kind = "class" if inspect.isclass(obj) else "function"
        text = f"manim.{name}{sig}  # {kind} (CE {MANIM_CE_VERSION}). {summary}".strip()
        snippets.append({"name": name, "text": text})
    return snippets


def upsert(snippets: list[dict], qdrant_url: str, collection: str) -> None:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=qdrant_url)
    # fastembed-backed add: documents are embedded locally (sovereign), metadata carries
    # the version so retrieval can filter to the pinned corpus.
    client.add(
        collection_name=collection,
        documents=[s["text"] for s in snippets],
        metadata=[{"manim_version": MANIM_CE_VERSION, "name": s["name"]} for s in snippets],
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--qdrant", default="http://localhost:6333")
    ap.add_argument("--collection", default="manim-ce")
    ap.add_argument("--dry-run", action="store_true", help="print snippet count, don't upsert")
    args = ap.parse_args()

    snippets = build_snippets()
    print(f"built {len(snippets)} snippets for Manim CE {MANIM_CE_VERSION}")
    if args.dry_run:
        for s in snippets[:5]:
            print("  ", s["text"][:100])
        return 0
    upsert(snippets, args.qdrant, args.collection)
    print(f"upserted into '{args.collection}' at {args.qdrant}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
