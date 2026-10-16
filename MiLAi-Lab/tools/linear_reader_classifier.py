"""Simple linear action classifier on the same encoder inputs as native Laya.

One state is encoded once. A shared scalar linear layer reads each option's
marker, without Laya's additional Transformer head, type embedding or MLP.
This avoids penalizing the ordinary baseline with full-state encoding per action.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evaluate_bounded_laya import NativeDecision
from milai_lab.harness.artifact_io import read_json, write_json
from ordinary_reader_reranker import save_model


def build_linear_model(encoder: Any) -> Any:
    import torch

    class LinearOptions(torch.nn.Module):
        def __init__(self, backbone: Any) -> None:
            super().__init__()
            self.encoder = backbone
            self.scorer = torch.nn.Linear(backbone.config.hidden_size, 1)

        def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype,
                    detach_encoder=False, position_ids=None, option_ids=None):
            output = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
            hidden = output.last_hidden_state
            if detach_encoder:
                hidden = hidden.detach()
            markers = hidden.gather(1, marker_pos.unsqueeze(-1).expand(-1, -1, hidden.shape[-1]))
            scores = self.scorer(markers).squeeze(-1).masked_fill(~marker_mask, -1e9)
            return scores, None

    return LinearOptions(encoder)


class LinearDecision(NativeDecision):
    def __init__(self, base: Path, max_len: int, head_max_len: int) -> None:
        super().__init__(base, max_len, head_max_len)
        self.model = build_linear_model(self.model.encoder).float().eval()
        self.config = {**self.config, "architecture": "linear_action_markers_v1"}

    @classmethod
    def load(cls, checkpoint: Path, max_len: int, head_max_len: int) -> LinearDecision:
        import torch
        from safetensors.torch import load_file
        from transformers import AutoModel, AutoTokenizer

        result = cls.__new__(cls)
        result.config = read_json(checkpoint / "linear_config.json")
        encoder = AutoModel.from_pretrained(checkpoint / "encoder", local_files_only=True)
        result.model = build_linear_model(encoder)
        result.model.scorer.load_state_dict(load_file(str(checkpoint / "scorer.safetensors")))
        result.model.float().eval()
        result.tokenizer = AutoTokenizer.from_pretrained(checkpoint / "tokenizer",
                                                         local_files_only=True)
        result.device = torch.device("cpu")
        result.max_len, result.head_max_len = max_len, head_max_len
        result.counters = dict(forwards=0, sequence_rows=0, input_tokens=0,
                               state_tokenizations=0, state_tokens=0)
        return result


def save_linear_checkpoint(model: Any, tokenizer: Any, config: dict, path: str) -> None:
    save_model(model, tokenizer, Path(path))
    write_json(Path(path) / "linear_config.json", config)
