import json
from io import BytesIO
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import pytest

from app.analysis import analyze, is_identifier
from app.ingest import DatasetError, demo_dataset, inspect_upload, read_dataset
from app.report import render_html, render_markdown


def run(df):
    source = {"filename": "test.csv", "is_demo": False, "analyzed_rows": len(df),
              "total_rows": len(df), "sampled": False, "sheet": None, "notes": []}
    return analyze(df, source, "理解收入", "收入", lambda *args: None)[0]


def test_demo_is_reproducible_and_has_charts():
    a, source = demo_dataset()
    b, _ = demo_dataset()
    pd.testing.assert_frame_equal(a, b)
    assert source["is_demo"] is True and len(a) == 4800
    result, aggregates = analyze(a, source, "理解销售额", "销售额", lambda *args: None)
    assert len(result["charts"]) >= 6
    assert {"heatmap", "histogram", "line", "scatter", "box", "bar"} <= {c["type"] for c in result["charts"]}
    assert result["overview"]["rows"] == 4800
    assert "preview" not in aggregates
    json.dumps(result, allow_nan=False)
    assert "基于聚合" not in result["summary"]


def test_missing_nonnumeric_and_constant_data():
    result = run(pd.DataFrame({"空列": [None] * 5, "名称": ["a", "a", "b", "c", "a"], "常量": [4] * 5}))
    assert result["overview"]["missing_cells"] == 5
    assert result["overview"]["duplicate_rows"] == 2
    assert not any(chart["type"] in {"heatmap", "scatter", "line"} for chart in result["charts"])
    json.dumps(result, allow_nan=False)
    empty = run(pd.DataFrame({"纯文本": ["x", "y", "z"]}))
    assert empty["overview"]["numeric_columns"] == 0
    assert len(empty["insights"]) >= 2


def test_ids_and_numbers_are_not_dates_or_correlations():
    result = run(pd.DataFrame({"user_id": range(30), "year": [2025] * 30, "收入": [i % 7 for i in range(30)],
                               "score": [i % 5 for i in range(30)]}))
    assert not any(chart["type"] == "line" for chart in result["charts"])
    heatmap = next(c for c in result["charts"] if c["type"] == "heatmap")
    assert "user_id" not in heatmap["figure"]["data"][0]["x"]
    assert any("标识符" in i["title"] for i in result["insights"])


def test_explicit_numeric_target_overrides_only_monotonic_id_heuristic():
    df = pd.DataFrame({"日期": pd.date_range("2026-01-01", periods=24),
                       "地区": ["华东", "华北", "华南"] * 8,
                       "销售额": [120 + day * 17 for day in range(24)],
                       "件数": [1 + day % 5 for day in range(24)],
                       "订单编号": list(range(24))})
    assert bool(is_identifier("销售额", df["销售额"]))
    source = {"filename": "train.csv", "is_demo": False, "analyzed_rows": 24,
              "total_rows": 24, "sampled": False, "sheet": None, "notes": []}
    result, _ = analyze(df, source, "探索销售额", "销售额", lambda *args: None)
    histogram = next(chart for chart in result["charts"] if chart["type"] == "histogram")
    assert "销售额" in histogram["title"]
    heatmap = next(chart for chart in result["charts"] if chart["type"] == "heatmap")
    assert "销售额" in heatmap["figure"]["data"][0]["x"]
    assert "订单编号" not in heatmap["figure"]["data"][0]["x"]
    assert any("用户明确选择" in note for note in result["source"]["notes"])
    assert bool(is_identifier("销售额", df["销售额"]))  # Global inference remains unchanged.


def test_named_identifier_target_remains_excluded_with_explanation():
    df = pd.DataFrame({"user_id": list(range(24)), "value": [day % 5 for day in range(24)]})
    source = {"filename": "train.csv", "is_demo": False, "analyzed_rows": 24,
              "total_rows": 24, "sampled": False, "sheet": None, "notes": []}
    result, _ = analyze(df, source, "关注编号", "user_id", lambda *args: None)
    assert not any("user_id" in chart["title"] for chart in result["charts"] if chart["type"] in {"histogram", "scatter", "box"})
    assert any("关注字段「user_id」名称疑似标识符" in note for note in result["source"]["notes"])


def test_correlation_requires_real_variation():
    result = run(pd.DataFrame({"a": [1, 2, 4, 3, 7, 5], "b": [2, 4, 8, 6, 14, 10], "constant": [1] * 6}))
    heatmap = next(c for c in result["charts"] if c["type"] == "heatmap")
    assert "constant" not in heatmap["figure"]["data"][0]["x"]
    assert any("r=1.000" in i["evidence"] for i in result["insights"])


def test_near_zero_correlation_has_no_direction_or_high_correlation_advice():
    result = run(pd.DataFrame({"revenue": [-1, 0, 1, -1, 0, 1], "quantity": [1, -2, 1, 1, -2, 1]}))
    insight = next(item for item in result["insights"] if item["title"] == "数值关系值得继续验证")
    assert "未见明显线性关联" in insight["body"]
    assert "接近零" in insight["body"]
    assert "正线性关联" not in insight["body"] and "负线性关联" not in insight["body"]
    assert "r=0.000" in insight["evidence"]
    assert not any("相关性较高" in item for item in result["recommendations"])
    assert any("非线性" in item for item in result["recommendations"])
    missing = next(chart for chart in result["charts"] if chart["type"] == "missingness")
    assert missing["figure"]["layout"]["yaxis"]["range"] == [0, 1]
    assert missing["figure"]["layout"]["yaxis"]["title"]["text"] == "缺失率（%）"
    box = next(chart for chart in result["charts"] if chart["type"] == "box")
    assert box["figure"]["data"][0]["x"] == ["revenue"]


def test_sparse_century_dates_do_not_overflow_or_expand_daily():
    result = run(pd.DataFrame({"date": ["1900-01-01", "2200-01-01"], "收入": [1, 3]}))
    line = next(c for c in result["charts"] if c["type"] == "line")
    trace = line["figure"]["data"][0]
    assert len(trace["x"]) <= 120
    assert sum(value is not None for value in trace["y"]) == 2
    assert any(value is None for value in trace["y"])
    study = result["eda"]["time"][0]
    assert study["frequency"] == "MS" and study["bucket_interval"] > 1
    assert study["total_buckets"] == len(trace["x"])
    assert study["empty_buckets"] == study["total_buckets"] - 2


def test_extreme_numeric_range_has_actionable_error():
    with pytest.raises(DatasetError, match="缩放计量单位"):
        run(pd.DataFrame({"收入": [1e308, -1e308, 0]}))


def test_one_row_has_valid_json():
    result = run(pd.DataFrame({"收入": [1]}))
    assert result["overview"]["rows"] == 1
    assert result["columns"][0]["std"] is None
    json.dumps(result, allow_nan=False)


def test_reports_escape_adversarial_dataset_text():
    malicious = '</script><script>alert("x")</script>'
    result = run(pd.DataFrame({malicious: ["one", "two", "one", "two"], "value": [3, 4, 2, 8]}))
    result["summary"] = "![bad](https://evil.example/tracker)"
    markdown = render_markdown(result, malicious)
    assert "![bad](" not in markdown
    document = render_html(result, markdown)
    assert malicious not in document
    assert "\\u003c/script\\u003e" in document
    assert '<script src="https://cdn.plot.ly' not in document
    assert "Plotly.newPlot" in document


def test_csv_encoding_truncation_infinity(tmp_path):
    path = tmp_path / "x.csv"
    path.write_bytes("名称,收入\n甲,1\n乙,inf\n丙,3\n丁,4\n".encode("gb18030"))
    df, source = read_dataset(path, "x.csv", "x.csv", max_rows=3)
    assert source["sampled"] is True and source["total_rows"] is None
    assert len(df) == 3 and df["收入"].isna().sum() == 1
    assert any("GB18030" in n for n in source["notes"])


def test_xlsx_uses_first_sheet_and_reports_its_name(tmp_path):
    path = tmp_path / "x.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(writer, sheet_name="Data", index=False)
        pd.DataFrame({"b": [4]}).to_excel(writer, sheet_name="Other", index=False)
    assert inspect_upload(path, "x.xlsx")[0]["name"] == "x.xlsx"
    df, source = read_dataset(path, "x.xlsx", "x.xlsx")
    assert list(df.columns) == ["a"] and source["sheet"] == "Data"
    assert any("首个" in n for n in source["notes"])


def test_header_normalization_resolves_blank_and_string_collisions(tmp_path):
    path = tmp_path / "names.xlsx"
    pd.DataFrame([[1, 2, 3], [4, 5, 6]], columns=[1, "1", ""]).to_excel(path, index=False)
    df, source = read_dataset(path, "names.xlsx", "names.xlsx")
    assert len(set(df.columns)) == 3
    assert any("规范化" in note for note in source["notes"])
    json.dumps(run(df), allow_nan=False)


def make_zip(tmp_path, entries):
    path = tmp_path / "data.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in entries:
            z.writestr(name, content)
    return path


def test_zip_requires_exact_selection_and_supports_nested_table(tmp_path):
    path = make_zip(tmp_path, [("train/data.csv", "a,b\n1,3\n2,4"), ("readme.txt", "notes")])
    assert inspect_upload(path, "data.zip") == [{"name": "train/data.csv", "size": 11}]
    with pytest.raises(DatasetError, match="选择"):
        read_dataset(path, "data.zip", "../data.csv")
    df, source = read_dataset(path, "data.zip", "train/data.csv")
    assert len(df) == 2 and source["filename"] == "train/data.csv"


@pytest.mark.parametrize("bad_name", ["../outside.csv", "/outside.csv", "a/../../outside.csv", "C:/file.csv", "a\\b.csv"])
def test_zip_path_traversal_rejected(tmp_path, bad_name):
    path = make_zip(tmp_path, [(bad_name, "a\n1")])
    with pytest.raises(DatasetError, match="不安全"):
        inspect_upload(path, "data.zip")


def test_zip_bomb_and_duplicate_members_rejected(tmp_path):
    path = make_zip(tmp_path, [("big.csv", b"a" * 2_000_000)])
    with pytest.raises(DatasetError, match="压缩比例"):
        inspect_upload(path, "data.zip")


def test_zip_encryption_and_symlinks_are_rejected(tmp_path):
    path = make_zip(tmp_path, [("a.csv", "a\n1")])
    raw = bytearray(path.read_bytes())
    local = raw.index(b"PK\x03\x04")
    central = raw.index(b"PK\x01\x02")
    raw[local + 6] |= 1
    raw[central + 8] |= 1
    path.write_bytes(raw)
    with pytest.raises(DatasetError, match="加密"):
        inspect_upload(path, "data.zip")
    with zipfile.ZipFile(path, "w") as archive:
        member = zipfile.ZipInfo("link.csv")
        member.create_system = 3
        member.external_attr = 0o120777 << 16
        archive.writestr(member, "../outside.csv")
    with pytest.raises(DatasetError, match="符号链接"):
        inspect_upload(path, "data.zip")
    with pytest.warns(UserWarning):
        path = make_zip(tmp_path, [("a.csv", "a\n1"), ("a.csv", "a\n2")])
    with pytest.raises(DatasetError, match="重复"):
        inspect_upload(path, "data.zip")


def test_invalid_empty_and_too_wide_csv(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(DatasetError, match="为空"):
        inspect_upload(empty, "empty.csv")
    wide = tmp_path / "wide.csv"
    wide.write_text(",".join(f"col{i}" for i in range(81)) + "\n" + ",".join("1" for _ in range(81)))
    with pytest.raises(DatasetError, match="最多支持"):
        read_dataset(wide, "wide.csv", "wide.csv")
