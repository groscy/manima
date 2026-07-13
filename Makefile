# MANIMA — one-command deployment entrypoint (tasks 3.3–3.4, design D1).
#
# Run inside WSL2 (project.md: the whole server side lives in WSL2). The default path is
# RENDER-ONLY — the sovereign surface that needs only Docker (invariant 6). The generate
# path is opt-in (`make generate-up`) and never a prerequisite for render.
#
# Quick start:
#   cp .env.example .env      # edit if needed
#   make install              # pip install -e the server (render path)
#   make deploy               # build image → preflight → smoke a render
#
# `make help` lists everything.

PYTHON       ?= python3
COMPOSE      ?= docker compose
# Single source of truth for the pinned Manim CE version (design D6): version.py.
MANIM_CE_VERSION := $(shell cd manima_server && $(PYTHON) -c "from manima_server.version import MANIM_CE_VERSION; print(MANIM_CE_VERSION)")

# The published render image, and the image name the server actually uses. A local build
# tags `manima-render:pinned`; a pull deploy overrides RENDER_IMAGE to the GHCR ref.
REGISTRY_IMAGE ?= ghcr.io/groscy/manima-render:pinned
RENDER_IMAGE   ?= manima-render:pinned

export MANIM_CE_VERSION

.DEFAULT_GOAL := help
.PHONY: help install image pull preflight deploy deploy-pull smoke generate-up generate-down lint test lock clean

help: ## Show this help
	@echo "MANIMA deployment targets (default = render-only):"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo "  Pinned Manim CE version: $(MANIM_CE_VERSION)"

install: ## Install the server (render path only — no generate deps)
	$(PYTHON) -m pip install -e manima_server

image: ## Build the pinned render image (manima-render:pinned)
	$(COMPOSE) --profile image build

pull: ## Pull the published render image from GHCR instead of building it
	MANIMA_RENDER_IMAGE=$(REGISTRY_IMAGE) $(COMPOSE) --profile image pull render-image

preflight: ## Fail loudly unless the Docker daemon is reachable
	@docker info >/dev/null 2>&1 || { echo "ERROR: Docker daemon unreachable — the server refuses to start without it (invariant 1)."; exit 1; }
	@echo "Docker OK — render_animation is serviceable."

deploy: image preflight smoke ## Render-only deploy: build image, verify Docker, prove a render
	@echo ""
	@echo "Render-only deployment is healthy. Launch the server from your MCP client as:"
	@echo "    MANIMA_RENDER_ONLY=1 $(PYTHON) -m manima_server.server   (cwd: manima_server/)"

deploy-pull: RENDER_IMAGE = $(REGISTRY_IMAGE)
deploy-pull: pull preflight smoke ## Render-only deploy from the PUBLISHED image (no local build)
	@echo ""
	@echo "Render-only deployment (pulled $(REGISTRY_IMAGE)) is healthy. Launch the server as:"
	@echo "    MANIMA_RENDER_ONLY=1 MANIMA_RENDER_IMAGE=$(REGISTRY_IMAGE) $(PYTHON) -m manima_server.server"

smoke: ## Render a trivial scene end-to-end and assert SUCCEEDED (invariant 3)
	MANIMA_RENDER_ONLY=1 MANIMA_RENDER_IMAGE=$(RENDER_IMAGE) $(PYTHON) manima_server/scripts/smoke_render.py

generate-up: ## Opt in to the generate path: start Qdrant (vLLM stays external)
	$(COMPOSE) --profile generate up -d
	@echo "Qdrant is up. vLLM is NOT started here — point MANIMA_VLLM_URL at your GPU instance,"
	@echo "then build the corpus:  python manima_server/scripts/build_corpus.py"

generate-down: ## Stop the generate-path services
	$(COMPOSE) --profile generate down

lint: ## Lint the Python sources (mirrors CI)
	ruff check manima_server harness

test: ## Run the offline test suite (mirrors CI; no Docker/GPU needed)
	cd manima_server && $(PYTHON) -m pytest -q

lock: ## Regenerate the dependency locks (needs pip-tools + network)
	cd manima_server && pip-compile --extra dev --output-file requirements.lock pyproject.toml
	cd harness && pip-compile --extra dev --output-file requirements.lock pyproject.toml

clean: ## Remove build/test caches
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true
