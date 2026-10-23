"""Which diagram-layer models the emitters render.

A family model replaces its generated base in dispatch (docs/grammar-guide.md, "Diagram
dispatch"), so only the top model of each ``factory`` may reach a grammar; a base that
leaked into the output would still accept what the family narrowed or removed. A diagram
model with no ``factory`` is nobody's base and is always emitted.
"""

from __future__ import annotations

from tools.model import ResolvedModel, ResolvedModels
from tools.model.resolve import top_models

DIAGRAM_LAYER = "diagram"


def emitted_diagrams(resolved: ResolvedModels) -> list[ResolvedModel]:
    """Diagram-layer models with a ``diagram`` type that are tops (or factory-less), by id."""
    tops = set(top_models(resolved).values())
    return [
        model
        for _, model in sorted(resolved.items())
        if model.layer == DIAGRAM_LAYER
        and model.diagram
        and (model.factory is None or model.id in tops)
    ]
