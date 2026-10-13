"""WO-32 §3 — 表格式输入（CSV/TSV/XLSX）的唯一解析合同。

**为什么单独一个模块**：WO-32 指出旧实现 ``line.split(delimiter)`` 会把
``S1,"contains, comma",12`` 拆成 4 列、用 ``splitlines()`` 截断有引号换行、
``errors="replace"`` 把编码损坏伪装成合法来源。这里用标准 :mod:`csv`
解析器，并且**与 SteelData 自己的解释保持一致**（``steeldata/adapters.py``
按后缀决定分隔符、按 UTF-8-BOM 严格解码、拒绝坏编码），使预览、映射与后续
处理看到的是同一份数据。

规则：

* 分隔符由**后缀**决定（``.tsv`` = TAB，``.csv`` = 逗号），不猜——这与
  SteelData ``read_document`` 的解释一致，映射字面因此不会被误导；
* 记录数按 **csv.reader 的逻辑记录** 计数，物理行数只作信息展示，绝不用来
  截断含引号换行的字段；
* 编码损坏/坏引号**直接报错**，不做 ``errors="replace"`` 静默替换；
* 不齐列**如实报告**行号与列数，不补空、不截短；
* XLSX 只读工作表清单与表头；含公式时明确说明 SteelData 运行会拒绝。
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

# 与 SteelData `steeldata/adapters.py` 相同的上限，避免两套解释漂移。
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 256
# SteelData 只接受这三个后缀做表格式输入；其余类型在服务端明确挡住。
SUPPORTED_SUFFIXES = (".csv", ".tsv", ".xlsx")

# 字符摸不到上限时的兜底分隔符（.csv）。只在与 SteelData 一致的前提下生效。
_FALLBACK_DELIMITER = ","
# 仅在**信息展示**里用：把表头行按几个常见候选分隔符分别数一次。
_CANDIDATE_DELIMITERS = (",", ";", "\t", "|")


class TableError(ValueError):
    """Raised when a tabular file cannot be read under the contract above."""


@dataclass
class TableView:
    kind: str                      # "table" | "error"
    file_id: str
    size: int
    suffix: str
    delimiter: str
    delimiter_source: str          # "suffix" | "fallback"
    encoding: str
    sheet: str | None = None
    sheets: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    records: int = 0               # 逻辑记录数（含表头）
    physical_lines: int = 0        # 信息展示用，不参与截断
    preview_rows: int = 0
    truncated: bool = False
    ragged_rows: list[int] = field(default_factory=list)
    duplicate_headers: list[str] = field(default_factory=list)
    empty_headers: list[int] = field(default_factory=list)
    has_formulas: bool = False
    problem: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)


def _delimiter_for(suffix: str, text: str) -> tuple[str, str]:
    """Return ``(delimiter, source)`` consistent with SteelData's own reader."""
    if suffix == ".tsv":
        return "\t", "suffix"
    header = text.splitlines()[0] if text.splitlines() else ""
    counts = {item: header.count(item) for item in _CANDIDATE_DELIMITERS}
    if max(counts.values(), default=0) > 0:
        # .csv 在后缀上就是逗号；这里只在逗号数为 0 时退回信息性候选，
        # 并把实际使用的分隔符如实报给前端，避免把内容当成对齐的列。
        best = max(counts, key=counts.get)
        return best, "suffix" if best == _FALLBACK_DELIMITER else "fallback"
    return _FALLBACK_DELIMITER, "fallback"


def _read_text(path: Path, payload: bytes) -> str:
    """Decode as UTF-8 (BOM tolerated). Anything else is an explicit error."""
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TableError(
            f"编码不是 UTF-8（SteelData 只接受 UTF-8 表格式文本）：{exc.reason} "
            f"位于字节 {exc.start}。请另存为 UTF-8 CSV/TSV 或 XLSX，"
            "不要用「替换损坏字符」的导出。"
        ) from exc


def _bbox(rows: list[list[str]], path: Path) -> None:
    if len(rows) > MAX_ROWS:
        raise TableError(f"超过 {MAX_ROWS} 行上限：{path.name}")
    for row in rows:
        if len(row) > MAX_COLUMNS:
            raise TableError(f"超过 {MAX_COLUMNS} 列上限：{path.name}")


def _scan_headers(columns: list[str]) -> tuple[list[str], list[int], list[str]]:
    empties = [index for index, name in enumerate(columns) if not name.strip()]
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in columns:
        key = name.strip()
        if not key:
            continue
        if key in seen and key not in duplicates:
            duplicates.append(key)
        seen.add(key)
    return duplicates, empties, [name.strip() for name in columns]


def _read_xlsx(path: Path, payload: bytes, *, preview_records: int = 25) -> TableView:
    import openpyxl
    import zipfile

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
            raise TableError("展开后超过 100 MiB 上限")
        if any("vbaproject" in item.filename.lower() for item in archive.infolist()):
            raise TableError("含宏的 XLSX 不受支持")
    # 先按公式视图扫一遍：含公式就如实说明， SteelData 运行会拒绝。
    probe = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=False,
                                  keep_links=False)
    try:
        sheets = list(probe.sheetnames)
        has_formulas = any(
            cell.data_type == "f"
            for cells in probe.iter_rows()
            for cell in cells
            if cell is not None
        )
    finally:
        probe.close()

    workbook = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    try:
        candidates: list[tuple[str, list[list[str]], list[str], list[int], list[int]]] = []
        for name in sheets:
            sheet = workbook[name]
            rows = [["" if cell is None else str(cell) for cell in row]
                    for row in sheet.iter_rows(values_only=True)]
            _bbox(rows, path)
            duplicates, empties, columns = _scan_headers(rows[0]) if rows else ([], [], [])
            ragged = [index for index, row in enumerate(rows[1:], start=1) if len(row) != len(columns)]
            candidates.append((name, rows, columns, ragged, empties))
        if not candidates:
            raise TableError("工作簿没有工作表")
        name, rows, columns, ragged, empties = candidates[0]
        duplicates, _, _ = _scan_headers(columns)
        notes: list[str] = []
        if has_formulas:
            notes.append("检测到公式单元格：SteelData 运行会要求另存为「仅值」导出；"
                         "这里显示的是缓存计算结果，二者可能不同。")
        if len(sheets) > 1:
            notes.append(f"该工作簿有 {len(sheets)} 个工作表（{', '.join(sheets)}）；"
                         "映射时需要显式选择 sheet，否则 SteelData 会拒绝运行。")
        preview = rows[1:preview_records + 1]
        return TableView(
            kind="table", file_id=path.name, size=len(payload), suffix=path.suffix.lower(),
            delimiter="", delimiter_source="sheet", encoding="utf-8", sheet=name, sheets=sheets,
            columns=columns, rows=preview, records=len(rows),
            physical_lines=len(rows), preview_rows=len(preview),
            truncated=len(rows) - 1 > preview_records, ragged_rows=ragged,
            duplicate_headers=duplicates, empty_headers=empties, has_formulas=has_formulas,
            notes=notes,
        )
    finally:
        workbook.close()


def read_table(path: Path, *, preview_records: int = 25) -> TableView:
    """Read a bounded, read-only view of one tabular input.

    The file is never written. Ragged rows, duplicate/empty headers, formula
    cells and encoding damage are reported instead of being repaired, so the
    mapping UI can stop with a truthful ``needs_human`` reason.
    """
    path = Path(path)
    if not path.is_file():
        raise TableError("文件不存在")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise TableError(
            f"网页映射只支持 {', '.join(SUPPORTED_SUFFIXES)}（与 SteelData 输入合同一致）；"
            f"收到 {suffix or '（无扩展名）'}。其它类型可以上传、预览或直接下载，"
            "但映射/运行需要先导出为 CSV/TSV/XLSX。")
    payload = path.read_bytes()
    if len(payload) > MAX_BYTES:
        raise TableError(f"超过 {MAX_BYTES // (1024 * 1024)} MiB 输入上限")
    if suffix == ".xlsx":
        return _read_xlsx(path, payload, preview_records=preview_records)

    text = _read_text(path, payload)
    delimiter, source = _delimiter_for(suffix, text)
    notes: list[str] = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        rows = []
        for row in reader:
            rows.append(row)
            _bbox(rows, path)
    except csv.Error as exc:
        raise TableError(f"CSV 语法错误（引号未闭合或分隔符不合法）：{exc}") from exc

    if not rows:
        raise TableError("文件为空")
    duplicates, empties, columns = _scan_headers(rows[0])
    ragged = [index for index, row in enumerate(rows[1:], start=1) if len(row) != len(columns)]
    physical = text.count("\n") + (0 if not text or text.endswith("\n") else 1)
    if physical != len(rows):
        notes.append(f"物理行 {physical} 与逻辑记录 {len(rows)} 不一致：字段内含引号换行，"
                     "按 csv 逻辑记录计数。")
    if source != "suffix":
        notes.append(f"后缀为 {suffix} 但表头行没有该后缀的默认分隔符；"
                     f"实际按 {delimiter!r} 解析（与 SteelData 的解释一致）。")
    if duplicates:
        notes.append(f"重复表头：{', '.join(duplicates)}（无法在映射里二选一，需改名）")
    if empties:
        notes.append(f"空表头列：{', '.join(str(item + 1) for item in empties)}")
    preview = rows[1:preview_records + 1]
    return TableView(
        kind="table", file_id=path.name, size=len(payload), suffix=suffix,
        delimiter=delimiter, delimiter_source=source,
        encoding="utf-8-sig" if payload.startswith(b"\xef\xbb\xbf") else "utf-8",
        sheet=None, sheets=[], columns=columns, rows=preview, records=len(rows),
        physical_lines=physical, preview_rows=len(preview),
        truncated=len(rows) - 1 > preview_records, ragged_rows=ragged,
        duplicate_headers=duplicates, empty_headers=empties, has_formulas=False, notes=notes,
    )


def header_cells(view: TableView) -> list[str]:
    """The mapped column names a profile may reference (verbatim, not cleaned)."""
    return [item for item in view.columns]


_SAMPLE_LIMIT = 64


def sample_values(view: TableView, column_index: int, limit: int = _SAMPLE_LIMIT) -> list[str]:
    """First non-empty values of one column, for the mapping UI's unit evidence."""
    if column_index < 0 or column_index >= len(view.columns):
        return []
    out: list[str] = []
    for row in view.rows:
        if column_index < len(row) and row[column_index].strip():
            out.append(row[column_index].strip())
            if len(out) >= limit:
                break
    return out


_HEADER_UNIT = re.compile(r"[\[(]([^\])]{1,24})[\])]")


def header_unit_hint(column: str) -> str | None:
    """Unit written in the header, e.g. ``屈服强度 (MPa)`` -> ``MPa``."""
    match = _HEADER_UNIT.search(column or "")
    return match.group(1).strip() if match else None
