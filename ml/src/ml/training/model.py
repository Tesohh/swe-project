"""Multi-task audio model: shared transformer trunk, four output heads.

Heads:
- music vs non-music detection (binary, BCE)
- genre multi-label (BCE over the genre vocab)
- mood multi-label (BCE over the mood vocab)
- energy regression (sigmoid scalar 0..1, MSE)
"""

import torch
from torch import nn
from transformers import AutoModel

from ml.features import BACKBONE

AUDIOSETS_BACKBONE = BACKBONE  # kept for old imports
ENERGY_WEIGHT = 0.5  # energy is a loudness proxy, so it should not steer the trunk much


class MultiTaskAST(nn.Module):
    """Shared audio transformer trunk with four heads and per-head loss masks."""

    def __init__(self, backbone: str = BACKBONE, n_genre: int = 22, n_mood: int = 11):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(backbone)
        hidden = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(0.1)
        self.music_head = nn.Linear(hidden, 1)  # music vs speech/noise/bad_upload
        self.genre_head = nn.Linear(hidden, n_genre)
        self.mood_head = nn.Linear(hidden, n_mood)
        self.energy_head = nn.Linear(hidden, 1)  # sigmoid after pooling

    def forward(self, spec: torch.Tensor) -> dict[str, torch.Tensor]:
        """spec: [batch, 1024, 128] AST-normalized fbank; returns per-head outputs.

        "embedding" is the [batch, 768] pooled trunk vector the heads read (pre-dropout),
        usable for similarity search.
        """
        # pooler_output is the mean of the CLS and distillation tokens, what AST pretrained with
        embedding = self.encoder(spec).pooler_output
        pooled = self.dropout(embedding)
        return {
            "embedding": embedding,
            "music": self.music_head(pooled).squeeze(-1),
            "genre": self.genre_head(pooled),
            "mood": self.mood_head(pooled),
            "energy": torch.sigmoid(self.energy_head(pooled)).squeeze(-1),
        }

    def loss(
        self, outputs: dict[str, torch.Tensor], batch: dict[str, torch.Tensor]
    ) -> dict[str, torch.Tensor]:
        """Masked losses per head; batch carries targets and per-row masks."""
        losses = {
            "music": nn.functional.binary_cross_entropy_with_logits(
                outputs["music"].float(), batch["music_labels"].float()
            ),
            "genre": self._masked_bce(outputs["genre"], batch["genre_labels"], batch["genre_mask"]),
            "mood": self._masked_bce(outputs["mood"], batch["mood_labels"], batch["mood_mask"]),
        }
        energy_mask = batch["energy_mask"].float()
        squared = (outputs["energy"].float() - batch["energy"].float()) ** 2
        losses["energy"] = ENERGY_WEIGHT * (squared * energy_mask).sum() / energy_mask.sum().clamp(
            min=1.0
        )
        return losses

    @staticmethod
    def _masked_bce(
        logits: torch.Tensor, targets: torch.Tensor, mask: torch.Tensor
    ) -> torch.Tensor:
        """Mean BCE over the labelled rows only (mask is [batch, 1]; expanded per element)."""
        elementwise = nn.functional.binary_cross_entropy_with_logits(
            logits.float(), targets.float(), reduction="none"
        )
        mask = mask.float().expand_as(elementwise)
        return (elementwise * mask).sum() / mask.sum().clamp(min=1.0)
