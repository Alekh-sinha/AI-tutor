import os
import time

from ai_teacher_api.common.persist import DirBackend, Mirror


def make(tmp_path):
    local = tmp_path / "local"
    (local / "a").mkdir(parents=True)
    bucket = DirBackend(tmp_path / "bucket")
    return local, bucket, Mirror(bucket, [(local, "data")])


def age(p):  # make a file look old enough to be pushed
    t = time.time() - 10
    os.utime(p, (t, t))


def test_push_then_restore_on_an_empty_disk(tmp_path):
    local, bucket, m = make(tmp_path)
    (local / "a" / "x.json").write_text("hello")
    age(local / "a" / "x.json")
    m.restored = True
    assert m.push() == {"uploaded": 1, "deleted": 0}
    assert bucket.list() == {"data/a/x.json": 5}
    # a new instance with an empty disk gets everything back
    fresh = tmp_path / "fresh"
    m2 = Mirror(bucket, [(fresh, "data")])
    assert m2.restore() == 1
    assert (fresh / "a" / "x.json").read_text() == "hello"


def test_changed_and_deleted_files_follow(tmp_path):
    local, bucket, m = make(tmp_path)
    f = local / "a" / "x.json"
    f.write_text("one")
    age(f)
    m.restored = True
    m.push()
    f.write_text("two!!")
    age(f)
    assert m.push()["uploaded"] == 1
    assert bucket.list()["data/a/x.json"] == 5
    f.unlink()
    assert m.push()["deleted"] == 1 and bucket.list() == {}


def test_nothing_is_deleted_before_the_restore_finished(tmp_path):
    """If the restore failed, an empty local disk must never wipe the bucket."""
    local, bucket, m = make(tmp_path)
    (tmp_path / "bucket" / "data").mkdir(parents=True)
    (tmp_path / "bucket" / "data" / "precious.json").write_text("keep me")
    m.known["data/precious.json"] = (1, 7)  # known from an earlier push, but never restored this time
    assert m.restored is False
    assert m.push()["deleted"] == 0
    assert "data/precious.json" in bucket.list()


def test_a_file_still_being_written_waits_for_the_next_round(tmp_path):
    local, bucket, m = make(tmp_path)
    (local / "a" / "fresh.json").write_text("partial")  # just now
    m.restored = True
    assert m.push()["uploaded"] == 0
