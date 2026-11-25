"""Multi-task audio model: shared transformer trunk, five output heads.

Heads:
- music/speech/noise/bad_upload detection (4-way, BCE)
- genre multi-label (BPCE over the genre vocab)
- mood multi-label (BCE over the mood vocab)
- energy regression (sigmoid scalar 0..1, MSE)
"""

import torch
from torch import nn
from transformers import AutoModel

AUDIOSETS_BACKBONE = "MIT/ast-finetuned-audioset-10-10-0.4593"


class MultiTaskAST(nn.Module):
    """Shared audio transformer trunk with five heads and per-head loss masks."""

    def __init__(self, backbone: str = AUDIOSETS_BACKBONE, n_genre: int = 22, n_mood: int = 11):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(backbone)
        hidden = self.encoder.config.hidden_size
        self.music_head = nn.Linear(hidden, 1)  # music vs speech/noise/bad_upload
        self.genre_head = nn.Linear(hidden, n_genre)
        self.mood_head = nn.Linear(hidden, n_mood)
        self.energy_head = nn.Linear(hidden, 1)  # sigmoid after pooling

    def forward(self, spec: torch.Tensor) -> dict[str, torch.Tensor]:
        """spec: [batch, frames, mels] float32 in AST layout; returns per-head logits."""
        encoded = self.encoder(spec)
        pooled = encoded.last_hidden_state.mean(dim=1)  # mean over tiles/frame axis
        return {
            "music": self.music_head(pooled).squeeze(-1),
            "genre": self.genre_head(pooled),
            "mood": self.mood_head(pooled),
            "energy": torch.sigmoid(self.energy_head(pooled)).squeeze(-1),
        }

    def loss(
        self, outputs: dict[str, torch.Tensor], batch: dict[str, torch.Tensor]
    ) -> dict[str, torch.Tensor]:
        """Masked BCE per head plus energy MSE; batch carries targets and masks."""
        losses = {}
        # music vs not-music
        losses["music"] = nn.functional.binary_cross_entropy_with_logits(
            outputs["music"], batch["music_labels"].float()
        )
        # multi-label genre, masked where no label is known
        losses["genre"] = self._masked_bce(
            outputs["genre"], batch["genre_labels"], batch["genre_mask"]
        )
        losses["mood"] = self._masked_bce(outputs["mood"], batch["mood_labels"], batch["mood_mask"])
        losses["energy"] = nn.functional.mse_loss(outputs["energy"], batch["energy"].float())
        return losses

    @staticmethod
    def _masked_bce(
        logits: torch.Tensor, targets: torch.Tensor, mask: torch.Tensor
    ) -> torch.Tensor:
        elementwise = nn.functional.binary_cross_entropy_with_logits(
            logits, targets.float(), reduction="none"
        )
        mask = mask.float()
        return (elementwise * mask).sum() / mask.sum().clamp(min=1.0)
