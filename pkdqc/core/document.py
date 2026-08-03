"""Segmentation document lifecycle, independent of Qt dialogs.

The document is the single authority for the user's current output path and
saved-state marker.  Callers inject path selection and overwrite decisions so
all cancellation and failure branches are testable without a native dialog.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .segmentation import Segmentation
from .volume import ImageVolume


class Disposition(Enum):
    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


Writer = Callable[[Segmentation, ImageVolume, str], None]
PathChooser = Callable[[], Optional[str]]
OverwriteConfirm = Callable[[str], bool]


@dataclass
class SegmentationDocument:
    image: Optional[ImageVolume] = None
    segmentation: Optional[Segmentation] = None
    segmentation_path: Optional[str] = None
    saved_revision: Optional[int] = None
    never_saved: bool = False

    @classmethod
    def loaded(cls, image: ImageVolume, segmentation: Segmentation,
               path: str) -> "SegmentationDocument":
        segmentation.clear_dirty()
        return cls(image, segmentation, str(path), segmentation.revision, False)

    @classmethod
    def blank(cls, image: ImageVolume) -> "SegmentationDocument":
        segmentation = Segmentation.empty_like(image.shape)
        return cls(image, segmentation, None, segmentation.revision, True)

    @property
    def has_image(self) -> bool:
        return self.image is not None

    @property
    def has_segmentation(self) -> bool:
        return self.segmentation is not None

    @property
    def dirty(self) -> bool:
        return bool(self.segmentation is not None and
                    self.segmentation.revision != self.saved_revision)

    def _saved(self, path: str) -> None:
        assert self.segmentation is not None
        self.segmentation_path = str(path)
        self.saved_revision = self.segmentation.revision
        self.never_saved = False
        self.segmentation.clear_dirty()

    def save(self, writer: Writer, choose_path: Optional[PathChooser] = None,
             confirm_overwrite: Optional[OverwriteConfirm] = None) -> bool:
        """Save to the current path, or delegate to Save As when pathless."""
        if self.image is None or self.segmentation is None:
            return False
        if self.segmentation_path is None:
            return self.save_as(writer, choose_path, confirm_overwrite)
        writer(self.segmentation, self.image, self.segmentation_path)
        self._saved(self.segmentation_path)
        return True

    def save_as(self, writer: Writer, choose_path: Optional[PathChooser],
                confirm_overwrite: Optional[OverwriteConfirm] = None) -> bool:
        if self.image is None or self.segmentation is None or choose_path is None:
            return False
        selected = choose_path()
        if not selected:
            return False
        destination = str(Path(selected))
        if Path(destination).exists() and confirm_overwrite is not None:
            if not confirm_overwrite(destination):
                return False
        # Commit document state only after the atomic writer completes.
        writer(self.segmentation, self.image, destination)
        self._saved(destination)
        return True

    def guard(self, decision: Callable[[], Disposition], save: Callable[[], bool],
              discard_checkpoint: Callable[[], None]) -> bool:
        """Return whether a destructive transition may continue."""
        if not self.dirty:
            return True
        choice = decision()
        if choice is Disposition.SAVE:
            return bool(save())
        if choice is Disposition.DISCARD:
            discard_checkpoint()
            return True
        return False
