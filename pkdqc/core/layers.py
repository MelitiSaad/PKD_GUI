"""Segmentation-layer model for one reference image.

Layers deliberately own their editing state: exactly one editable layer is
active, and every layer has an independent bounded history.  Rendering/UI code
can consume the ordered visible layers without coupling this Qt-free model to a
particular dock or viewer implementation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .history import History
from .segmentation import Segmentation


@dataclass
class SegmentationLayer:
    name: str
    segmentation: Segmentation
    opacity: float = 0.5
    visible: bool = True
    locked: bool = False
    history: History | None = None

    def __post_init__(self):
        if self.history is None:
            self.history = History(self.segmentation)


class SegmentationLayers:
    """Ordered layer collection with one active, unlocked editable layer."""
    def __init__(self):
        self._layers: list[SegmentationLayer] = []
        self.active_index: int | None = None

    def __iter__(self):
        return iter(self._layers)

    def __len__(self):
        return len(self._layers)

    @property
    def active(self) -> SegmentationLayer | None:
        return None if self.active_index is None else self._layers[self.active_index]

    def add(self, name: str, segmentation: Segmentation, *, visible=True, opacity=.5,
            locked=False, make_active=False) -> SegmentationLayer:
        layer = SegmentationLayer(name, segmentation, float(opacity), bool(visible), bool(locked))
        self._layers.append(layer)
        if make_active or self.active_index is None:
            self.set_active(len(self._layers) - 1)
        return layer

    def set_active(self, index: int) -> None:
        if not 0 <= int(index) < len(self._layers):
            raise IndexError("Segmentation layer index out of range")
        if self._layers[index].locked:
            raise ValueError("A locked segmentation layer cannot be active for editing")
        self.active_index = int(index)

    def remove(self, index: int) -> SegmentationLayer:
        layer = self._layers.pop(index)
        if not self._layers:
            self.active_index = None
        elif self.active_index is not None:
            self.active_index = min(self.active_index, len(self._layers) - 1)
            if self._layers[self.active_index].locked:
                for i, candidate in enumerate(self._layers):
                    if not candidate.locked:
                        self.active_index = i; break
        return layer

    def visible_layers(self):
        return tuple(layer for layer in self._layers if layer.visible)
