#!/usr/bin/env bash
# MANIMA bring-up sequence (task 12.1, design Migration Plan).
#
# Run inside WSL2. Order matters: the render image and Docker come first (the render path
# depends only on them), then the generate-path services. render_animation is usable after
# step 2 alone; generate_animation needs steps 3-4 as well.
set -euo pipefail

MANIM_CE_VERSION="${MANIM_CE_VERSION:-0.18.1}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION="${COLLECTION:-manim-ce}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> 1/5  Build the pinned render image (Manim CE ${MANIM_CE_VERSION} + full TeX Live)"
docker build --build-arg "MANIM_CE_VERSION=${MANIM_CE_VERSION}" \
    -t manima-render:pinned "${HERE}/docker"

echo "==> 2/5  Verify the Docker daemon is reachable (the server refuses to start otherwise)"
docker info >/dev/null
echo "    Docker OK. render_animation is now serviceable."

echo "==> 3/5  Start vLLM serving Apertus 8B int4 (OpenAI-compatible endpoint)"
echo "    Expected reachable at: ${MANIMA_VLLM_URL:-http://localhost:8000/v1}"
echo "    (start your vLLM process here; left manual — checkpoint/quant are deployment-specific)"

echo "==> 4/5  Start Qdrant and build the grounding corpus from the pinned version"
echo "    Qdrant expected at: ${QDRANT_URL}"
python "${HERE}/scripts/build_corpus.py" --qdrant "${QDRANT_URL}" --collection "${COLLECTION}"

echo "==> 5/5  Start the MANIMA MCP server (stdio)"
echo "    Launch via your MCP client, or: python -m manima_server.server"
echo "    Render-only? set MANIMA_RENDER_ONLY=1 to skip the generate path entirely."

echo "Bring-up complete."
