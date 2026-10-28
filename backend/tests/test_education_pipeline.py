"""Outcome selection must remain consistent from local statistics to model evidence."""
import time

import pandas as pd
from fastapi.testclient import TestClient

from app.analysis import analyze
from app.config import Settings
from app.main import create_app


def test_invalid_explicit_focus_is_not_described_as_an_automatic_replacement():
    df = pd.DataFrame({"gpa_rank": [1, 2, 3, 4, 5], "score": [90, 70, 85, 60, 80]})
    source = {"filename": "grades.csv", "sampled": False, "is_demo": False, "notes": []}
    result, _ = analyze(df, source, "解释学业排名", "missing_score", lambda *args: None)
    notes = " ".join(result["source"]["notes"])
    assert "不自动换成其他指标" in notes
    assert "本次使用自动字段选择" not in notes
    assert result["brief"]["focus"]["column"] is None


def test_optional_model_receives_the_same_resolved_outcome_as_the_brief(tmp_path, monkeypatch):
    captured = []

    def fake_enrich(result, aggregates, goal, target, *args):
        captured.append((target, result["brief"]["focus"]["column"], aggregates["explanation_evidence"]["focus"]["column"]))

    monkeypatch.setattr("app.main.enrich", fake_enrich)
    settings = Settings(data_dir=tmp_path, admin_username="admin", admin_password="test password",
                        session_secret="x" * 40, cookie_secure=False)
    content = "student_id,gpa_rank,internship\n" + "\n".join(f"S{i},{i},{100-i}" for i in range(1, 31))
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/login", json={"username": "admin", "password": "test password"}).status_code == 200
        item = client.post("/api/uploads", files={"file": ("grades.csv", content.encode(), "text/csv")}).json()
        job = client.post("/api/jobs", json={"upload_id": item["upload_id"], "selected_file": item["files"][0]["name"],
                                             "goal": "解释学业排名", "use_llm": True}).json()
        for _ in range(200):
            status = client.get("/api/jobs/" + job["id"]).json()
            if status["status"] in {"completed", "failed"}:
                break
            time.sleep(.05)
        assert status["status"] == "completed"
        assert captured == [("gpa_rank", "gpa_rank", "gpa_rank")]
        assert client.get("/api/usage").json()["request_count"] == 0
