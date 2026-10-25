import os
import tempfile

from app.storage.db import Database


def test_db_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        db = Database(os.path.join(d, "t.db"))
        db.upsert_video({"video_id": "v1", "platform": "youtube", "url": "u",
                         "title": "t", "duration": 100, "author": "", "description": ""})
        assert db.get_video("v1")["title"] == "t"
        db.save_report("r1", "v1", "# hi", [], [])
        assert db.get_report("r1")["report_md"] == "# hi"
        db.create_job("j1", "v1")
        db.update_job("j1", status="done", progress=1.0)
        assert db.get_job("j1")["status"] == "done"