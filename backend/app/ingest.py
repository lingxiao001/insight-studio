from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
import csv
import re
import stat
import zipfile

import numpy as np
import pandas as pd

TABULAR = {".csv", ".tsv", ".xlsx"}
MAX_EXPANDED = 150 * 1024 * 1024
MAX_MEMBER = 50 * 1024 * 1024


class DatasetError(ValueError):
    pass


def validate_archive(archive: zipfile.ZipFile, *, xlsx=False):
    infos = archive.infolist()
    if len(infos) > (2000 if xlsx else 100):
        raise DatasetError("压缩包内文件数量过多。")
    total = 0
    names = set()
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if ("\\" in name or "\x00" in name or path.is_absolute() or ".." in path.parts
                or re.match(r"^[A-Za-z]:", name) or name in names):
            raise DatasetError("压缩包包含不安全或重复的文件路径。")
        names.add(name)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise DatasetError("不支持包含符号链接的压缩包。")
        if info.flag_bits & 1:
            raise DatasetError("不支持加密压缩包。")
        total += info.file_size
        if info.file_size > MAX_MEMBER or total > MAX_EXPANDED:
            raise DatasetError("解压后的数据过大，请拆分后上传。")
        if info.file_size > 1024 * 1024 and info.file_size / max(info.compress_size, 1) > 1000:
            raise DatasetError("压缩比例异常，无法安全读取此压缩包。")
    return infos


def inspect_upload(path: Path, filename: str):
    suffix = Path(filename).suffix.lower()
    if suffix not in TABULAR | {".zip"}:
        raise DatasetError("支持 CSV、TSV、XLSX 或包含这些表格的 ZIP 文件。")
    if path.stat().st_size == 0:
        raise DatasetError("上传的文件为空。")
    if suffix == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                infos = validate_archive(archive)
                files = [{"name": item.filename, "size": item.file_size} for item in infos
                         if not item.is_dir() and not item.filename.startswith("__MACOSX/")
                         and Path(item.filename).suffix.lower() in TABULAR]
        except (zipfile.BadZipFile, NotImplementedError) as exc:
            raise DatasetError("ZIP 文件损坏或使用了不支持的压缩方式。") from exc
        if not files:
            raise DatasetError("ZIP 中未找到 CSV、TSV 或 XLSX 数据表。")
        return files
    if suffix == ".xlsx":
        try:
            with zipfile.ZipFile(path) as archive:
                validate_archive(archive, xlsx=True)
        except zipfile.BadZipFile as exc:
            raise DatasetError("XLSX 文件无效或已损坏。") from exc
    return [{"name": filename, "size": path.stat().st_size}]


def read_dataset(path: Path, filename: str, selected_file: str, max_rows=100_000, max_columns=80):
    suffix = Path(filename).suffix.lower()
    notes = []
    if suffix == ".zip":
        files = inspect_upload(path, filename)
        if selected_file not in {item["name"] for item in files}:
            raise DatasetError("请从压缩包列表中选择一个有效的数据表。")
        try:
            with zipfile.ZipFile(path) as archive:
                with archive.open(selected_file) as member:
                    data = member.read(MAX_MEMBER + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
            raise DatasetError("无法读取选中的压缩包文件。") from exc
        if len(data) > MAX_MEMBER:
            raise DatasetError("选中的数据表超过 50 MB。")
        table_name = selected_file
        notes.append("已读取 ZIP 中用户选定的数据表。")
    else:
        if selected_file != filename:
            raise DatasetError("请选择上传文件对应的数据表。")
        data = path.read_bytes()
        table_name = filename
    ext = Path(table_name).suffix.lower()
    sheet = None
    try:
        if ext == ".xlsx":
            with zipfile.ZipFile(BytesIO(data)) as archive:
                validate_archive(archive, xlsx=True)
            with pd.ExcelFile(BytesIO(data), engine="openpyxl") as workbook:
                sheet = workbook.sheet_names[0]
                df = pd.read_excel(workbook, sheet_name=sheet, nrows=max_rows + 1)
                if len(workbook.sheet_names) > 1:
                    notes.append(f"工作簿包含 {len(workbook.sheet_names)} 个工作表，本次分析首个工作表。")
        else:
            try:
                decoded = data.decode("utf-8-sig")
                encoding = "UTF-8"
            except UnicodeDecodeError:
                decoded = data.decode("gb18030")
                encoding = "GB18030"
            if "\x00" in decoded:
                raise DatasetError("文件包含二进制内容，请上传标准文本表格。")
            delimiter = "\t" if ext == ".tsv" else ","
            try:
                delimiter = csv.Sniffer().sniff(decoded[:65536], delimiters=",\t;|").delimiter
            except csv.Error:
                pass
            header = next((row for row in csv.reader(StringIO(decoded), delimiter=delimiter) if row), [])
            if len(header) > max_columns:
                raise DatasetError(f"数据表包含 {len(header)} 列，最多支持 {max_columns} 列。")
            if len(set(header)) != len(header):
                notes.append("存在重复列名，解析器已自动追加后缀以区分字段。")
            df = pd.read_csv(StringIO(decoded), sep=delimiter, nrows=max_rows + 1, low_memory=False)
            notes.append(f"文本编码：{encoding}。")
    except DatasetError:
        raise
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError, ValueError,
            zipfile.BadZipFile, KeyError, OSError, IndexError) as exc:
        raise DatasetError("无法解析数据表，请检查编码、分隔符、列结构或工作簿格式。") from exc
    if df.empty:
        raise DatasetError("数据表没有可分析的数据行。")
    if len(df.columns) > max_columns:
        raise DatasetError(f"数据表包含 {len(df.columns)} 列，最多支持 {max_columns} 列。")
    if any(len(str(name)) > 200 for name in df.columns):
        raise DatasetError("列名过长，请将各列名称缩短到 200 个字符以内。")
    normalized, seen = [], set()
    changed = False
    for index, name in enumerate(df.columns):
        base = str(name)
        if not base.strip() or base.startswith("Unnamed:"):
            base = f"未命名列_{index + 1}"
        candidate, counter = base, 2
        while candidate in seen:
            candidate = f"{base}_{counter}"
            counter += 1
        changed |= candidate != str(name)
        normalized.append(candidate)
        seen.add(candidate)
    df.columns = normalized
    if changed:
        notes.append("空列名和重名列已规范化为唯一名称，详情见字段画像。")
    sampled = len(df) > max_rows
    total_rows = None if sampled else len(df)
    df = df.iloc[:max_rows].copy()
    # Infinity is not JSON-compatible and is treated explicitly as missing data.
    nonfinite = int(df.select_dtypes(include=["number"]).isin([np.inf, -np.inf]).sum().sum())
    if nonfinite:
        df = df.replace([np.inf, -np.inf], np.nan)
        notes.append(f"{nonfinite} 个无穷值按缺失值处理。")
    if sampled:
        notes.append(f"为控制资源，仅分析前 {max_rows:,} 行；完整行数未知。所有指标均基于这些行。")
    return df, {"filename": table_name, "is_demo": False, "analyzed_rows": len(df),
                "total_rows": total_rows, "sampled": sampled, "sheet": sheet, "notes": notes}


def demo_dataset():
    rng = np.random.default_rng(20261026)
    rows = 4800
    category = rng.choice(["数码配件", "家居生活", "运动户外", "美妆护理", "食品饮料"], rows,
                          p=[.28, .23, .16, .14, .19])
    quantity = rng.integers(1, 7, rows)
    price_map = {"数码配件": 179, "家居生活": 129, "运动户外": 249, "美妆护理": 159, "食品饮料": 69}
    price = np.array([price_map[item] for item in category]) * rng.uniform(.65, 1.6, rows)
    discount = rng.choice([0, .05, .1, .2, .3], rows, p=[.4, .2, .2, .15, .05])
    revenue = quantity * price * (1 - discount)
    profit = revenue * (rng.uniform(.12, .38, rows) - discount * .25)
    df = pd.DataFrame({
        "订单编号": [f"ORD-{i + 100001}" for i in range(rows)],
        "下单日期": (pd.Timestamp("2025-01-01") + pd.to_timedelta(rng.integers(0, 365, rows), unit="D")),
        "地区": rng.choice(["华东", "华南", "华北", "西南", "华中"], rows, p=[.32, .24, .2, .13, .11]),
        "品类": category, "销售渠道": rng.choice(["线上商城", "线下门店", "合作平台"], rows),
        "件数": quantity, "单价": price.round(2), "折扣率": discount,
        "销售额": revenue.round(2), "利润": profit.round(2),
        "客户评分": rng.choice([1, 2, 3, 4, 5, np.nan], rows, p=[.025, .055, .15, .35, .35, .07]),
        "配送天数": rng.choice([1, 2, 3, 4, 5, 7, np.nan], rows, p=[.1, .23, .3, .18, .1, .05, .04]),
    })
    missing = rng.choice(rows, size=96, replace=False)
    df.loc[missing, "地区"] = None
    df.loc[rng.choice(rows, 16, replace=False), "销售额"] *= 5
    return df, {"filename": "合成零售演示数据.csv", "is_demo": True, "analyzed_rows": rows,
                "total_rows": rows, "sampled": False, "sheet": None,
                "notes": ["此数据由固定随机种子生成，共 4,800 行，仅用于产品演示；不代表真实企业或 Kaggle 数据。"]}
