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

# System deps for Manim's 2D backend + video muxing. Kept in their own layer so the large
# TeX layer below is a separate, independently-pushable blob (a single multi-GB blob is
# what GHCR rejected with a 400 during publish).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config \
        libcairo2-dev libpango1.0-dev \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Full TeX Live so no LaTeX package is ever fetched on demand (specs/render: "full LaTeX",
# offline). We install the COMPLETE package + font set, then strip the documentation and
# source trees — never inputs to *compiling* a scene — in the same layer. That roughly
# halves the image and, as importantly, shrinks the blob GHCR must accept in one push,
# without weakening the "any LaTeX package works offline" guarantee. mktexlsr refreshes the
# kpathsea filename DB after the removal.
RUN apt-get update && apt-get install -y --no-install-recommends texlive-full \
    && rm -rf \
        /usr/share/texlive/texmf-dist/doc \
        /usr/share/texlive/texmf-dist/source \
        /usr/share/texmf/doc \
        /usr/share/doc \
        /usr/share/man \
        /usr/share/info \
    && mktexlsr \
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
