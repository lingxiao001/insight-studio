"""Public snapshots must never expose an account's data or start paid work."""
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.public_examples import EXAMPLE_IDS, load_example, summarize_example


def test_anonymous_examples_are_read_only_and_private_routes_stay_protected(tmp_path):
    settings = Settings(data_dir=tmp_path, admin_username="admin", admin_password="test password",
                        session_secret="x" * 40, cookie_secure=False)
    with TestClient(create_app(settings)) as client:
        catalog = client.get("/api/examples")
        assert catalog.status_code == 200
        assert {item["slug"] for item in catalog.json()["examples"]} == set(EXAMPLE_IDS)
        for item in catalog.json()["examples"]:
            snapshot = load_example(item["slug"])
            assert item["records"] == snapshot["result"]["overview"]["rows"]
            assert item["fields"] == snapshot["result"]["overview"]["columns"]
            assert item["domain"]
            assert item["finding"]
        for slug in EXAMPLE_IDS:
            assert client.get(f"/api/examples/{slug}").status_code == 200
            assert client.get(f"/api/examples/{slug}/report.md").status_code == 200
            assert client.get(f"/api/examples/{slug}/report.html").status_code == 200
            assert client.post(f"/api/examples/{slug}", json={}).status_code == 401
            assert client.delete(f"/api/examples/{slug}").status_code == 401
        assert client.get("/api/examples/private-job-id").status_code == 401
        assert client.get("/api/jobs").status_code == 401
        assert client.get("/api/uploads/private-id/schema").status_code == 401
        assert client.post("/api/demo").status_code == 401
        assert client.post("/api/login", json={"username": "admin", "password": "test password"}).status_code == 200
        assert client.get("/api/jobs").json()["jobs"] == []
        assert client.get("/api/usage").json()["request_count"] == 0
        assert client.get("/api/examples/private-job-id").status_code == 404


def test_snapshots_publish_aggregates_with_attribution_and_consistent_evidence():
    for slug in EXAMPLE_IDS:
        item = load_example(slug)
        result = item["result"]
        assert item["provenance"]["citation"]
        assert item["provenance"]["license"]
        assert item["provenance"]["url"].startswith("https://")
        assert result["preview"] == {"columns": [], "rows": []}
        assert result["columns"] == []
        assert "eda" not in result
        chart_ids = {chart["id"] for chart in result["charts"]}
        for finding in result["brief"]["findings"]:
            assert set(finding["chart_ids"]) <= chart_ids
    for slug in ("graduation-employability", "graduation-academic"):
        item = load_example(slug)
        result = item["result"]
        assert item["provenance"]["doi"] == "10.17632/c8ypkyswv3.1"
        assert item["provenance"]["license"] == "CC BY 4.0"
        assert result["overview"]["rows"] == 253
        assert result["overview"]["columns"] == 76
        for chart in result["charts"]:
            assert "student_id" not in chart["fields"]
            for trace in chart["figure"]["data"]:
                assert trace["type"] == "bar"
                assert len(trace["x"]) <= 8 and len(trace["y"]) <= 8
                assert "customdata" not in trace and "text" not in trace
        histogram = result["charts"][0]["figure"]["data"][0]
        assert sum(histogram["y"]) == 253
    employment = load_example("graduation-employability")["result"]
    contrast = next(chart for chart in employment["charts"] if chart["id"] == "public-contrast")
    assert contrast["figure"]["data"][0]["y"] == [10, 66]
    assert "13.2%" in employment["brief"]["findings"][1]["takeaway"]
    relationships = next(chart for chart in employment["charts"] if chart["id"] == "public-relationships")
    assert relationships["figure"]["data"][0]["x"][:2] == [0.3005, 0.7644]


def test_catalog_accepts_non_doi_sources_without_inventing_education_metadata():
    item = {"slug": "business-example", "title": "一个公开问题", "description": "描述",
            "topic": "零售", "domain": "商业", "finding": "有明确样本范围的发现",
            "provenance": {"url": "https://www.kaggle.com/datasets/example/data", "license": "CC0"},
            "result": {"overview": {"rows": 100, "columns": 6}}}
    assert summarize_example(item) == {"slug": "business-example", "title": "一个公开问题",
                                       "description": "描述", "topic": "零售", "domain": "商业",
                                       "finding": "有明确样本范围的发现", "records": 100, "fields": 6}


def test_public_exports_include_limits_and_license(tmp_path):
    settings = Settings(data_dir=tmp_path, admin_username="admin", admin_password="test password",
                        session_secret="x" * 40, cookie_secure=False)
    with TestClient(create_app(settings)) as client:
        for extension in ("md", "html"):
            response = client.get(f"/api/examples/graduation-employability/report.{extension}")
            assert response.status_code == 200
            assert "attachment" in response.headers["content-disposition"]
            assert "CC BY 4.0" in response.text
            assert "10.17632/c8ypkyswv3.1" in response.text
            assert "10/76" in response.text
            assert "不是实际就业率" in response.text
            assert '"type": "scatter"' not in response.text
