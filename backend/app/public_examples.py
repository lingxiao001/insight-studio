"""Curated, aggregate-only public examples, independent of account job storage."""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from .report import render_html, render_markdown

EXAMPLE_IDS = (
    "hotel-city-cancellations", "hotel-resort-cancellations",
    "credit-card-default", "heart-failure-followup", "netflix-catalog", "netflix-movie-length",
    "graduation-employability", "graduation-academic",
)
DATA_DIR = Path(__file__).with_name("example_data")
PUBLIC_PATHS = {"/api/examples"} | {
    f"/api/examples/{slug}{suffix}"
    for slug in EXAMPLE_IDS for suffix in ("", "/report.md", "/report.html")
}
router = APIRouter(prefix="/api/examples")


def load_example(slug):
    # Never resolve a client-supplied filename or read from private job storage.
    if slug not in EXAMPLE_IDS:
        raise HTTPException(404, "没有找到这个公开示例。")
    return json.loads((DATA_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def summarize_example(item):
    """Keep the catalog small and derive its scale from the published snapshot."""
    summary = {key: item[key] for key in ("slug", "title", "description", "topic")}
    summary.update({
        "domain": item.get("domain", "教育" if item["slug"].startswith("graduation-") else "其他"),
        "finding": item.get("finding", item["description"]),
        "records": item["result"]["overview"]["rows"],
        "fields": item["result"]["overview"]["columns"],
    })
    return summary


@router.get("")
def examples():
    return {"examples": [summarize_example(item) for item in map(load_example, EXAMPLE_IDS)]}


@router.get("/{slug}")
def example(slug: str):
    return load_example(slug)


@router.get("/{slug}/report.{extension}")
def example_report(slug: str, extension: str):
    if extension not in {"md", "html"}:
        raise HTTPException(404, "不支持此报告格式。")
    item = load_example(slug)
    result = item["result"]
    goal = result["brief"]["goal"]
    markdown = render_markdown(result, goal)
    content = markdown if extension == "md" else render_html(result, markdown, goal)
    media = "text/markdown" if extension == "md" else "text/html"
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{slug}.{extension}"'})
