"""Reproduce free local reports from a prepared Graduation CSV; no data bundled."""
import argparse
from pathlib import Path

from app.analysis import analyze
from app.ingest import read_dataset
from app.report import save_reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/graduation-case"))
    args = parser.parse_args()
    for key, target, goal in [
        ("academic", "gpa_rank", "哪些课程成绩与GPA排名更相关？这些关系能说明什么，不能说明什么？"),
        ("employability", "employment_ability_scale", "就业能力自评与实习成绩、主动学习及课程成绩有什么关系？请解释实际含义。"),
    ]:
        df, source = read_dataset(args.input, args.input.name, args.input.name)
        if target not in df:
            parser.error(f"Missing required prepared column: {target}")
        source["notes"].append("数据来源：Wang, Dongxuan (2025), Graduation, Mendeley Data V1, DOI 10.17632/c8ypkyswv3.1，CC BY 4.0；本例使用76列预处理版本。")
        result, _ = analyze(df, source, goal, target, lambda *args:None)
        save_reports(args.output_dir / key, result, goal)
        print(f"{key}: {result['brief']['headline']}")
        for finding in result["brief"]["findings"]:
            print(f"  {finding['title']} — {finding['evidence']}")


if __name__ == "__main__":
    main()
