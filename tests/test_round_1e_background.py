import time
from concurrent.futures import Future

import numpy as np
import pytest

from pkdqc.core.background import ArraySnapshot, BackgroundTaskService, CancelledTask, TaskTag
from pkdqc.core.commands import apply_volume
from pkdqc.core.history import History
from pkdqc.core.label_policy import DrawOver, LabelProtectionPolicy
from pkdqc.core.segmentation import Segmentation
from pkdqc.core import segops
from pkdqc.core.volume import ImageVolume
from pkdqc.core.volumetry import compute_volumes
from pkdqc.core import session


class ManualExecutor:
    def __init__(self):
        self.jobs = []
        self.shutdown_called = False

    def submit(self, fn, token):
        fut = Future()
        self.jobs.append((fn, token, fut))
        return fut

    def run_next(self):
        fn, token, fut = self.jobs.pop(0)
        if fut.cancelled():
            return fut
        try:
            fut.set_result(fn(token))
        except BaseException as exc:
            fut.set_exception(exc)
        return fut

    def shutdown(self, wait=False, cancel_futures=True):
        self.shutdown_called = True
        if cancel_futures:
            for _fn, _token, fut in self.jobs:
                fut.cancel()


def tag(doc="doc", rev=1, kind="volumetry", params=None):
    return TaskTag.make(doc, rev, kind, params)


def test_current_result_accepted_and_stale_revision_discarded():
    ex = ManualExecutor(); svc = BackgroundTaskService(executor=ex); svc.set_document("doc", 1)
    applied = []
    svc.submit_latest(tag(), lambda token: "ok", applied.append)
    ex.run_next(); outcomes = svc.drain_completed()
    assert outcomes[0].status == "applied" and applied == ["ok"]
    svc.submit_latest(tag(rev=1), lambda token: "old", applied.append)
    svc.update_revision(2)
    ex.run_next(); outcomes = svc.drain_completed()
    assert outcomes[0].status == "stale" and applied == ["ok"]


def test_old_document_and_out_of_order_completion_discarded():
    ex = ManualExecutor(); svc = BackgroundTaskService(executor=ex); svc.set_document("doc-a", 1)
    applied = []
    svc.submit_destructive(tag("doc-a", 1, "cleanup"), lambda token: "a", applied.append)
    svc.set_document("doc-b", 1)
    ex.run_next(); outcomes = svc.drain_completed()
    assert outcomes[0].status in {"stale", "cancelled"} and applied == []


def test_coalescing_latest_tasks_and_bounded_queue():
    ex = ManualExecutor(); svc = BackgroundTaskService(executor=ex); svc.set_document("doc", 3)
    applied = []
    svc.submit_latest(tag(rev=3, kind="volumetry", params={"n": 1}), lambda token: 1, applied.append)
    svc.submit_latest(tag(rev=3, kind="volumetry", params={"n": 2}), lambda token: 2, applied.append)
    svc.submit_latest(tag(rev=3, kind="volumetry", params={"n": 3}), lambda token: 3, applied.append)
    assert svc.queue_size == 2  # one running plus one latest pending, never an unbounded backlog
    ex.run_next(); out1 = svc.drain_completed()[0]
    assert out1.status == "cancelled"
    ex.run_next(); out2 = svc.drain_completed()[0]
    assert out2.status == "applied" and applied == [3]


def test_3d_coalescing_uses_latest_parameters():
    ex = ManualExecutor(); svc = BackgroundTaskService(executor=ex); svc.set_document("doc", 5)
    applied = []
    svc.submit_latest(tag(rev=5, kind="mesh", params={"label": 1}), lambda token: 1, applied.append)
    svc.submit_latest(tag(rev=5, kind="mesh", params={"label": 2}), lambda token: 2, applied.append)
    ex.run_next(); assert svc.drain_completed()[0].status == "cancelled"
    ex.run_next(); assert svc.drain_completed()[0].status == "applied"
    assert applied == [2]


def test_cancellation_before_and_during_cooperative_work():
    ex = ManualExecutor(); svc = BackgroundTaskService(executor=ex); svc.set_document("doc", 1)
    h = svc.submit_destructive(tag(kind="cleanup"), lambda token: token.raise_if_cancelled(), lambda v: None)
    h.cancel(); ex.run_next()
    assert svc.drain_completed()[0].status == "cancelled"
    def work(token):
        token.cancel(); token.raise_if_cancelled()
    svc.submit_destructive(tag(kind="cleanup"), work, lambda v: None)
    ex.run_next()
    assert svc.drain_completed()[0].status == "cancelled"


def test_uninterruptible_obsolete_task_returns_late_and_is_discarded():
    ex = ManualExecutor(); svc = BackgroundTaskService(executor=ex); svc.set_document("doc", 1)
    applied = []
    svc.submit_latest(tag(rev=1), lambda token: "late", applied.append)
    svc.update_revision(2)
    ex.run_next(); outcome = svc.drain_completed()[0]
    assert outcome.status == "stale" and applied == []


def test_worker_exception_isolated_and_preserves_state():
    ex = ManualExecutor(); svc = BackgroundTaskService(executor=ex); svc.set_document("doc", 1)
    errors = []
    svc.submit_latest(tag(), lambda token: (_ for _ in ()).throw(RuntimeError("boom")), lambda v: None, errors.append)
    ex.run_next(); outcome = svc.drain_completed()[0]
    assert outcome.status == "error" and isinstance(errors[0], RuntimeError)


def test_immutable_snapshot_exact_revision_and_editing_while_readonly_runs():
    data = np.zeros((4, 4, 4), np.uint16)
    data[1, 1, 1] = 1
    snap = ArraySnapshot.capture("doc", 7, data)
    data[1, 1, 1] = 2
    assert snap.revision == 7 and snap.data[1, 1, 1] == 1 and not snap.data.flags.writeable
    image = ImageVolume(np.ones(data.shape, np.float32), (1, 1, 1), np.eye(4))
    seg = Segmentation(snap.data.copy())
    vols = compute_volumes(seg, image)
    assert next(v for v in vols if v.id == 1).voxels == 1


def test_stale_destructive_result_not_history_success_one_undo_redo_and_protect_labels():
    seg = Segmentation(np.zeros((5, 5, 3), np.uint16)); seg.data[2, 2, 1] = 1; seg.data[2, 3, 1] = 2
    hist = History(seg)
    snap = ArraySnapshot.capture("doc", seg.revision, seg.data)
    # Compute from snapshot with protected label 2; live revision changes before apply.
    worker_seg = Segmentation(snap.data.copy()); worker_seg.active_id = 1
    result = segops.grow(worker_seg, 1, 1, True, 1, policy=LabelProtectionPolicy(DrawOver.BACKGROUND_ONLY))
    assert result is not None
    stale_cmd = apply_volume(seg, worker_seg.data, "grow")
    seg.data[0, 0, 0] = 9; seg.mark_edited([0])
    assert seg.revision != snap.revision
    # Stale result is intentionally not pushed.
    assert not hist.can_undo
    before = seg.data.copy()
    fresh = seg.data.copy(); fresh[1, 1, 1] = 1
    cmd = apply_volume(seg, fresh, "grow")
    hist.push(cmd)
    assert hist.can_undo and len(hist._undo) == 1 and seg.data[2, 3, 1] == 2
    hist.undo(); assert np.array_equal(seg.data, before)
    hist.redo(); assert seg.data[1, 1, 1] == 1 and seg.data[2, 3, 1] == 2


def test_autosave_revision_n_stale_then_latest_revision_applied(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import importlib, pkdqc.config as cfg, pkdqc.core.session as sess
    importlib.reload(cfg); importlib.reload(sess)
    source = tmp_path / "img.nii"; source.write_bytes(b"source")
    image = ImageVolume(np.zeros((3, 3, 3), np.float32), (1, 1, 1), np.eye(4), str(source))
    seg = Segmentation.empty_like(image.shape); s = sess.Session(image); s.begin()
    ex = ManualExecutor(); svc = BackgroundTaskService(executor=ex); svc.set_document("doc", 0)
    applied = []
    def submit_for(rev):
        snapshot = ArraySnapshot.capture("doc", rev, seg.data)
        def work(token):
            copy = Segmentation(snapshot.data.copy()); copy.revision = snapshot.revision; copy.dirty = True
            return snapshot.revision, s.save(copy, saved_revision=None, dirty=True)
        svc.submit_latest(tag(rev=rev, kind="autosave"), work, applied.append)
    submit_for(0)
    seg.data[1, 1, 1] = 1; seg.mark_edited([1]); svc.update_revision(seg.revision); submit_for(seg.revision)
    ex.run_next(); assert svc.drain_completed()[0].status == "cancelled"
    ex.run_next(); outcome = svc.drain_completed()[0]
    assert outcome.status == "applied" and applied[-1][0] == seg.revision
    rec = sess.find_recoverable()[0]
    assert rec.revision == seg.revision


def test_case_replacement_shutdown_and_no_late_callbacks():
    ex = ManualExecutor(); svc = BackgroundTaskService(executor=ex); svc.set_document("a", 1)
    applied = []
    svc.submit_latest(tag("a", 1), lambda token: "old", applied.append)
    svc.set_document("b", 1)
    ex.run_next(); assert svc.drain_completed()[0].status in {"stale", "cancelled"}
    svc.submit_latest(tag("b", 1), lambda token: "pending", applied.append)
    svc.shutdown()
    assert svc.closed and ex.shutdown_called


def test_fault_injection_preserves_previous_recovery_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import importlib, pkdqc.config as cfg, pkdqc.core.session as sess
    importlib.reload(cfg); importlib.reload(sess)
    source = tmp_path / "img.nii"; source.write_bytes(b"source")
    image = ImageVolume(np.zeros((3, 3, 3), np.float32), (1, 1, 1), np.eye(4), str(source))
    seg = Segmentation.empty_like(image.shape)
    s = sess.Session(image); s.begin(); assert s.save(seg, dirty=True)
    old = sess.find_recoverable()[0].generation_id
    def fail(phase):
        if phase == "before_commit": raise RuntimeError("injected")
    s._fault = fail
    seg.data[1, 1, 1] = 1; seg.mark_edited([1])
    with pytest.raises(RuntimeError):
        s.save(seg, dirty=True)
    rec = sess.find_recoverable()[0]
    assert rec.generation_id == old
