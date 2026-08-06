"""Qt-free case model for independent segmentation layers.

Numeric label ids intentionally have no meaning outside their owning layer.
The model never combines arrays or rewrites ids; consumers render each
``RenderingLayer`` independently in the returned order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional
import uuid

import numpy as np

from .document import Disposition
from .history import History
from .segmentation import Segmentation
from .volume import ImageVolume


@dataclass
class SegmentationLayer:
    name: str
    segmentation: Segmentation
    opacity: float = 0.5
    visible: bool = True
    locked: bool = False
    history: History | None = None
    layer_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    path: str | None = None
    saved_revision: int | None = None
    never_saved: bool = False
    recovery_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        self.opacity = float(self.opacity)
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("Layer opacity must be between 0 and 1")
        if self.history is None:
            self.history = History(self.segmentation)
        if self.saved_revision is None:
            self.saved_revision = self.segmentation.revision

    @property
    def labels(self):
        return self.segmentation.labels

    @property
    def dirty(self) -> bool:
        return self.segmentation.revision != self.saved_revision

    @property
    def display_path(self) -> str:
        return self.path or "Not yet saved."

    def mark_saved(self, path: str) -> None:
        self.path = str(path)
        self.saved_revision = self.segmentation.revision
        self.never_saved = False
        self.segmentation.clear_dirty()


@dataclass(frozen=True)
class RenderingLayer:
    layer_id: str
    segmentation: Segmentation
    opacity: float
    visible: bool
    active: bool


Writer = Callable[[Segmentation, ImageVolume, str], None]
PathChooser = Callable[[SegmentationLayer], Optional[str]]


class SegmentationLayers:
    """Ordered authoritative layer collection for one reference image."""

    def __init__(self, image: ImageVolume | None = None, *, case_id: str | None = None):
        self.image = image
        self.case_id = case_id or uuid.uuid4().hex
        self._layers: list[SegmentationLayer] = []
        self.active_layer_id: str | None = None
        self.global_overlay_visible = True

    def __iter__(self): return iter(self._layers)
    def __len__(self): return len(self._layers)
    def __getitem__(self, index): return self._layers[index]

    @property
    def active_index(self) -> int | None:
        if self.active_layer_id is None:
            return None
        return next((i for i, x in enumerate(self._layers) if x.layer_id == self.active_layer_id), None)

    @active_index.setter
    def active_index(self, value: int | None) -> None:
        if value is None:
            self.active_layer_id = None
        else:
            self.set_active(value)

    @property
    def active(self) -> SegmentationLayer | None:
        return self.get(self.active_layer_id) if self.active_layer_id else None

    @property
    def dirty(self) -> bool:
        return any(layer.dirty for layer in self._layers)

    @property
    def dirty_layers(self) -> tuple[SegmentationLayer, ...]:
        return tuple(x for x in self._layers if x.dirty)

    def get(self, layer_id: str | None) -> SegmentationLayer | None:
        return next((x for x in self._layers if x.layer_id == layer_id), None)

    def _validate(self, segmentation: Segmentation, affine=None) -> None:
        if self.image is None:
            return
        if tuple(segmentation.data.shape) != tuple(self.image.shape):
            raise ValueError(f"Segmentation shape {segmentation.data.shape} does not match image {self.image.shape}")
        if affine is not None and not np.allclose(np.asarray(affine), self.image.affine, rtol=1e-5, atol=1e-5):
            raise ValueError("Segmentation affine does not match the reference image")

    def add(self, name: str, segmentation: Segmentation, *, visible=True, opacity=.5,
            locked=False, make_active=False, path: str | None = None, affine=None,
            layer_id: str | None = None) -> SegmentationLayer:
        self._validate(segmentation, affine)
        layer = SegmentationLayer(name=name, segmentation=segmentation, opacity=opacity,
                                  visible=visible, locked=locked,
                                  layer_id=layer_id or uuid.uuid4().hex, path=path,
                                  never_saved=path is None,
                                  saved_revision=segmentation.revision)
        self._layers.append(layer)
        if make_active or self.active_layer_id is None:
            self.set_active(layer.layer_id)
        return layer

    def add_blank(self, name: str = "Untitled segmentation", **kwargs) -> SegmentationLayer:
        if self.image is None:
            raise ValueError("Open a reference image before adding a blank layer")
        return self.add(name, Segmentation.empty_like(self.image.shape), path=None, **kwargs)

    def set_active(self, layer: int | str) -> None:
        candidate = self._layers[int(layer)] if isinstance(layer, int) else self.get(layer)
        if candidate is None:
            raise KeyError(f"Unknown segmentation layer {layer}")
        if candidate.locked:
            raise ValueError("A locked segmentation layer cannot be active for editing")
        self.active_layer_id = candidate.layer_id

    def rename(self, layer_id: str, name: str) -> None:
        layer = self._require(layer_id)
        if not str(name).strip():
            raise ValueError("Layer name cannot be empty")
        layer.name = str(name).strip()

    def set_opacity(self, layer_id: str, opacity: float) -> None:
        value = float(opacity)
        if not 0 <= value <= 1: raise ValueError("Layer opacity must be between 0 and 1")
        self._require(layer_id).opacity = value

    def set_visible(self, layer_id: str, visible: bool) -> None:
        self._require(layer_id).visible = bool(visible)

    def move(self, layer_id: str, new_index: int) -> None:
        layer = self._require(layer_id)
        old = self._layers.index(layer)
        target = max(0, min(int(new_index), len(self._layers) - 1))
        self._layers.insert(target, self._layers.pop(old))

    def move_up(self, layer_id: str) -> None:
        layer = self._require(layer_id); self.move(layer_id, self._layers.index(layer) + 1)

    def move_down(self, layer_id: str) -> None:
        layer = self._require(layer_id); self.move(layer_id, self._layers.index(layer) - 1)

    def remove(self, layer: int | str) -> SegmentationLayer:
        target = self._layers[int(layer)] if isinstance(layer, int) else self._require(layer)
        index = self._layers.index(target); self._layers.pop(index)
        if target.layer_id == self.active_layer_id:
            self.active_layer_id = (self._layers[min(index, len(self._layers)-1)].layer_id
                                    if self._layers else None)
        return target

    def replace_active(self, name: str, segmentation: Segmentation, *, path=None, affine=None) -> SegmentationLayer:
        self._validate(segmentation, affine)  # validation is transactional
        old = self.active
        if old is None: return self.add(name, segmentation, path=path, make_active=True)
        index = self._layers.index(old)
        new = SegmentationLayer(name=name, segmentation=segmentation, path=path,
                                never_saved=path is None, opacity=old.opacity,
                                visible=old.visible)
        self._layers[index] = new; self.active_layer_id = new.layer_id
        return new

    def visible_layers(self):
        return tuple(x for x in self._layers if self.global_overlay_visible and x.visible)

    def rendering_layers(self) -> tuple[RenderingLayer, ...]:
        return tuple(RenderingLayer(x.layer_id, x.segmentation, x.opacity,
                                    self.global_overlay_visible and x.visible,
                                    x.layer_id == self.active_layer_id) for x in self._layers)

    def toggle_overlays(self) -> bool:
        self.global_overlay_visible = not self.global_overlay_visible
        return self.global_overlay_visible

    def save_layer(self, layer_id: str, writer: Writer, choose_path: PathChooser | None = None,
                   confirm_overwrite: Callable[[str], bool] | None = None, *, save_as=False) -> bool:
        if self.image is None: return False
        layer = self._require(layer_id)
        destination = None if save_as else layer.path
        if destination is None:
            if choose_path is None: return False
            destination = choose_path(layer)
            if not destination: return False
        destination = str(Path(destination))
        if Path(destination).exists() and destination != layer.path and confirm_overwrite and not confirm_overwrite(destination):
            return False
        writer(layer.segmentation, self.image, destination)
        layer.mark_saved(destination)  # state commits only after atomic writer succeeds
        return True

    def save_all(self, writer: Writer, choose_path: PathChooser | None = None,
                 confirm_overwrite: Callable[[str], bool] | None = None) -> bool:
        for layer in tuple(self.dirty_layers):
            if not self.save_layer(layer.layer_id, writer, choose_path, confirm_overwrite):
                return False
        return True

    def guard_layer(self, layer_id: str, decision: Callable[[SegmentationLayer], Disposition],
                    save: Callable[[SegmentationLayer], bool], discard: Callable[[SegmentationLayer], None]) -> bool:
        layer = self._require(layer_id)
        if not layer.dirty: return True
        choice = decision(layer)
        if choice is Disposition.SAVE: return bool(save(layer))
        if choice is Disposition.DISCARD: discard(layer); return True
        return False

    def guard_all(self, decision: Callable[[tuple[SegmentationLayer, ...]], Disposition],
                  save_all: Callable[[], bool], discard: Callable[[SegmentationLayer], None]) -> bool:
        dirty = self.dirty_layers
        if not dirty: return True
        choice = decision(dirty)
        if choice is Disposition.SAVE: return bool(save_all())
        if choice is Disposition.DISCARD:
            for layer in dirty: discard(layer)
            return True
        return False

    def accepts_task(self, case_id: str, layer_id: str, revision: int) -> bool:
        layer = self.get(layer_id)
        return bool(case_id == self.case_id and layer is not None and layer.segmentation.revision == revision)

    def _require(self, layer_id: str) -> SegmentationLayer:
        layer = self.get(layer_id)
        if layer is None: raise KeyError(f"Unknown segmentation layer {layer_id}")
        return layer


LayeredCase = SegmentationLayers
