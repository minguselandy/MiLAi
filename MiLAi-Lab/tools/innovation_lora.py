"""The same q/v low-rank parameterization used by the first CPU training pilot."""

from __future__ import annotations

from typing import Any


def install_lora(model: Any, *, rank: int, seed: int) -> dict[str, Any]:
    import torch  # type: ignore[import-not-found]

    model.requires_grad_(False)
    torch.manual_seed(seed)

    class LoRALinear(torch.nn.Module):
        def __init__(self, base: Any) -> None:
            super().__init__()
            self.base = base
            self.down = torch.nn.Linear(base.in_features, rank, bias=False)
            self.up = torch.nn.Linear(rank, base.out_features, bias=False)
            torch.nn.init.normal_(self.down.weight, std=0.01)
            torch.nn.init.zeros_(self.up.weight)

        def forward(self, value: Any) -> Any:
            return self.base(value) + 2.0 * self.up(self.down(value))

    for name, module in list(model.named_modules()):
        if name.endswith(("q_proj", "v_proj")):
            parent, attribute = name.rsplit(".", 1)
            setattr(model.get_submodule(parent), attribute, LoRALinear(module))
    return {name: value for name, value in model.named_parameters() if value.requires_grad}
