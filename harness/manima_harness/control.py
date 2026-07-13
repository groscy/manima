"""The control condition (tasks 3.2, 3.3).

Runs the *same prompt suite* through a frontier model and submits each result via
``render_animation`` — the same sandbox, the same 240p probe implicitly exercised by a
real render, the same mechanical oracle Apertus faces. Without this, an Apertus number
is uninterpretable (proposal.md): a low frontier score points at the prompt template or
grounding corpus, a high one isolates the finding to the local model.

Single-pass by construction: ``render_animation`` performs no repair (specs/render —
"the caller wrote this source"), so this measures the frontier model's *first-pass*
success, the fair comparison to Apertus's first pass. Reuses the ``Profile`` base for
the render/poll/persist/sample machinery; it is a run mode, not a load shape, so it is
kept out of the load-profile registry.
"""

from __future__ import annotations

from .client import ManimaClient
from .generators import SourceGenerator
from .profiles import Profile
from .record import RunRecord


class ControlCondition(Profile):
    name = "control"

    def __init__(self, *args, generator: SourceGenerator, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.generator = generator
        # Frontier token accounting (task 4.1's control-side analogue): the frontier
        # path is billed, so its token counts are recorded per prompt and written as a
        # sidecar, since render's RunRecord has no slot for generator-side usage.
        self.accounting: list[dict[str, object]] = []

    async def run(self, client: ManimaClient) -> list[RunRecord]:
        runs: list[RunRecord] = []
        async with self._sampling():
            for prompt in self.suite:
                generated = await self.generator.generate(prompt.prompt)
                self.accounting.append(
                    {
                        "prompt_id": prompt.id,
                        "model": generated.model,
                        "input_tokens": generated.input_tokens,
                        "output_tokens": generated.output_tokens,
                    }
                )
                runs.append(
                    await self._render_job(
                        client, prompt, generated.source, self.generator.identity
                    )
                )
        self._drain_calls(client)
        self.store.write_json("control_tokens.json", self.accounting)
        return runs
