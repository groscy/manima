# MANIMA render image (task 2.1, specs/render + specs/sandbox).
#
# Pinned Manim CE + full TeX Live, non-root, TeX shell-escape disabled. This image is the
# execution environment for EVERY render — probe or full, generated or operator-supplied.
# It is deliberately offline: the sandbox runs it with --network=none, so everything a
# scene could need (including uncommon LaTeX packages) must already be inside.
#
# Build (version flows from manima_server.version.MANIM_CE_VERSION — keep in sync):
#   docker build --build-arg MANIM_CE_VERSION=0.18.1 -t manima-render:pinned docker/

FROM python:3.12-slim-bookworm

ARG MANIM_CE_VERSION=0.18.1

# System deps: Cairo/Pango for Manim's 2D backend, ffmpeg for video muxing, and full
# TeX Live so no LaTeX package is fetched on demand (specs/render).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config \
        libcairo2-dev libpango1.0-dev \
        ffmpeg \
        texlive-full \
    && rm -rf /var/lib/apt/lists/*

# Pin Manim CE to exactly the version the corpus and artifact hash assume (design D8).
RUN pip install --no-cache-dir "manim==${MANIM_CE_VERSION}"

# Defence in depth: disable TeX shell-escape at the engine config level. The sandbox is
# the real boundary (invariant 5); this just removes an obvious foot-gun.
RUN echo "shell_escape = f" >> /etc/texmf/texmf.cnf \
    && echo "openout_any = p" >> /etc/texmf/texmf.cnf \
    && echo "openin_any = p" >> /etc/texmf/texmf.cnf

# Non-root user; the sandbox also drops all capabilities and mounts the rootfs read-only.
RUN useradd --create-home --uid 1000 manim
USER manim
WORKDIR /work

# The sandbox supplies the full `manim ...` argument vector per render.
ENTRYPOINT ["manim"]
