"""WO-32 §3 / WO-33 §1 — 表格式输入（CSV/TSV/XLSX）的唯一解析合同。

**为什么单独一个模块**：WO-32 指出旧实现 ``line.split(delimiter)`` 会把
``S1,"contains, comma",12`` 拆成 4 列、用 ``splitlines()`` 截断有引号换行、
``errors="replace"`` 把编码损坏伪装成合法来源。这里用标准 :mod:`csv`
解析器，并且**与 SteelData 自己的解释保持一致**（``steeldata/adapters.py``
按后缀决定分隔符、按 UTF-8-BOM 严格解码、拒绝坏编码、按 ``profile.sheet``
与 ``profile.header_row`` 取表），使预览、映射与后续处理看到的是同一份数据。

WO-33 §1 补的是 XLSX 与「解释一致」：

* **工作表遍历按 worksheet**，不是 ``Workbook.iter_rows``（那个方法不存在，
  之前直接 500）；错误转成具体可行动的 :class:`TableError`，不吞成空数据；
* **显式 sheet 选择**：多工作表时 SteelData 会要求 profile 写明 sheet，
  网页也必须能选，且预览/映射/preview/run 读的是**同一张表**；
* **header_row 一致**：表头不在第一行时按 ``header_row`` 取表头，
  与 ``steeldata/adapters.matches``/``parse`` 的取法一致；
* **公式如实**：SteelData 用 ``data_only=False`` 且遇到公式直接拒绝，
  所以这里也按同一视图读，并把缓存值单独列出，绝不假装公式已被计算。

规则：

* 分隔符由**后缀**决定（``.tsv`` = TAB，``.csv`` = 逗号），不猜、不做第二套
  规则——这与 SteelData ``read_document`` 的解释一致，映射字面因此不会被误导；
* 记录数按 **csv.reader 的逻辑记录** 计数，物理行数只作信息展示，绝不用来
  截断含引号换行的字段；
* 编码损坏/坏引号**直接报错**，不做 ``errors="replace"`` 静默替换；
* 不齐列**如实报告**行号与列数，不补空、不截短。
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
MAX_CELLS = 2_000_000
MAX_XLSX_EXPANDED_BYTES = 100 * 1024 * 1024
# SteelData 只接受这三个后缀做表格式输入；其余类型在服务端明确挡住。
SUPPORTED_SUFFIXES = (".csv", ".tsv", ".xlsx")

# 仅在**信息展示**里用：表头行没有后缀默认分隔符时，提示用户可能导错了。
_CANDIDATE_DELIMITERS = (",", ";", "\t", "|")
_DELIMITER_LABEL = {",": "逗号", "\t": "制表符", ";": "分号", "|": "竖线"}


class TableError(ValueError):
    """Raised when a tabular file cannot be read under the contract above."""


@dataclass
class TableView:
    kind: str                      # "table" | "error"
    file_id: str
    size: int
    suffix: str
    delimiter: str
    delimiter_source: str          # "suffix" | "sheet"
    encoding: str
    sheet: str | None = None
    sheets: list[str] = field(default_factory=list)
    sheet_required: bool = False   # 多工作表且未显式指定 → SteelData 会拒绝
    header_row: int = 1
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    cached_rows: list[list[str]] = field(default_factory=list)
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


def _delimiter_for(suffix: str) -> str:
    """The one delimiter SteelData itself would use for this suffix."""
    return "\t" if suffix == ".tsv" else ","


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
    """Per-row bound check (called while streaming, so it stays O(1) per row)."""
    if len(rows) > MAX_ROWS:
        raise TableError(f"超过 {MAX_ROWS} 行上限：{path.name}")
    if len(rows[-1]) > MAX_COLUMNS:
        raise TableError(f"超过 {MAX_COLUMNS} 列上限：{path.name}")


def _check_cells(rows: list[list[str]], path: Path) -> None:
    """Cell-count bound, checked once after the rows are read."""
    if not rows:
        return
    widest = max(len(row) for row in rows)
    if len(rows) * max(1, widest) > MAX_CELLS:
        raise TableError(f"超过 {MAX_CELLS} 单元格上限：{path.name}")


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


def _frame(rows: list[list[str]], *, header_row: int, preview_records: int,
           label: str) -> tuple[list[str], list[list[str]], list[int], int]:
    """Split ``rows`` into (header, data rows, ragged indexes, header position)."""
    if not rows:
        raise TableError(f"{label}是空的（没有任何行）")
    if header_row < 1:
        raise TableError(f"header_row 必须 ≥ 1，收到 {header_row}")
    if header_row > len(rows):
        raise TableError(
            f"header_row={header_row} 超出{label}行数（共 {len(rows)} 行）。"
            "请把表头所在行号填对，或确认导出时没有丢掉表头。")
    header = rows[header_row - 1]
    if not any(str(name).strip() for name in header):
        raise TableError(
            f"{label}第 {header_row} 行没有可用的表头（整行为空）。"
            "请把表头行号指到真正写着列名的那一行，或确认导出时没有丢掉表头。")
    data = rows[header_row:]
    ragged = [index for index, row in enumerate(data, start=1) if len(row) != len(header)]
    return header, data, ragged, header_row


def _read_xlsx(path: Path, payload: bytes, *, sheet: str | None,
               header_row: int, preview_records: int) -> TableView:
    """Read one worksheet with the same view SteelData uses.

    SteelData loads with ``data_only=False`` and refuses formula cells, so this
    reader does the same: the columns/rows shown are exactly what a run would
    see. When formulas are present the cached values are listed *separately*
    (``cached_rows``) and the caller is told the run will be refused until a
    values-only export is provided — never silently substituted.
    """
    import zipfile

    try:
        import openpyxl
        from openpyxl.utils.exceptions import InvalidFileException
    except ImportError as exc:  # pragma: no cover - openpyxl is a declared dependency
        raise TableError(f"读取 XLSX 需要 openpyxl（未安装）：{exc}") from exc

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            expanded = sum(item.file_size for item in archive.infolist())
            if expanded > MAX_XLSX_EXPANDED_BYTES:
                raise TableError(
                    f"XLSX 展开后超过 {MAX_XLSX_EXPANDED_BYTES // (1024 * 1024)} MiB 上限：{path.name}")
            if any("vbaproject" in item.filename.lower() for item in archive.infolist()):
                raise TableError(f"含宏的 XLSX 不受支持（SteelData 同样拒绝）：{path.name}")
    except zipfile.BadZipFile as exc:
        raise TableError(
            f"不是有效的 XLSX（zip 结构损坏）：{path.name}。"
            "请用 Excel/WPS 重新另存为 .xlsx；改名成 .xlsx 的 CSV 不会被接受。") from exc

    def _load(*, data_only: bool):
        try:
            return openpyxl.load_workbook(io.BytesIO(payload), read_only=True,
                                          data_only=data_only, keep_links=False)
        except InvalidFileException as exc:
            raise TableError(f"openpyxl 不认这个文件：{path.name}（{exc}）") from exc
        except (OSError, ValueError, KeyError) as exc:
            raise TableError(f"XLSX 无法打开：{path.name}（{type(exc).__name__}: {exc}）") from exc

    # ---- 1) 工作表清单 + 公式探测（按 worksheet 遍历，不是 Workbook.iter_rows）----
    probe = _load(data_only=False)
    try:
        sheets = list(probe.sheetnames)
        if not sheets:
            raise TableError(f"工作簿没有工作表：{path.name}")
        if sheet:
            if sheet not in sheets:
                raise TableError(
                    f"工作簿里没有工作表 {sheet!r}；实际有：{', '.join(sheets)}")
            chosen = sheet
            sheet_required = False
        elif len(sheets) == 1:
            chosen = sheets[0]
            sheet_required = False
        else:
            chosen = sheets[0]
            sheet_required = True
        worksheet = probe[chosen]
        has_formulas = False
        for cells in worksheet.iter_rows():
            for cell in cells:
                if cell is not None and cell.data_type == "f":
                    has_formulas = True
                    break
            if has_formulas:
                break
        rows = _worksheet_rows(worksheet, path)
    finally:
        probe.close()

    header, data, ragged, used_header = _frame(rows, header_row=header_row,
                                               preview_records=preview_records,
                                               label=f"工作表 {chosen!r} ")
    duplicates, empties, columns = _scan_headers(header)

    cached_rows: list[list[str]] = []
    if has_formulas:
        cache = _load(data_only=True)
        try:
            cache_rows = _worksheet_rows(cache[chosen], path)
            cached_rows = cache_rows[used_header:used_header + preview_records]
        finally:
            cache.close()

    notes: list[str] = []
    if has_formulas:
        notes.append("检测到公式单元格：SteelData 会拒绝这种文件（要求显式复核过的「仅值」导出）。"
                     "下面另列的缓存值是 Excel 上次算出的结果，仅供辨认，不是本次运行会读到的内容。")
    if sheet_required:
        notes.append(f"该工作簿有 {len(sheets)} 个工作表（{', '.join(sheets)}）；"
                     "SteelData 要求 profile 显式写明 sheet，映射时必须先选定，否则运行会被拒绝。")
    if duplicates:
        notes.append(f"重复表头：{', '.join(duplicates)}（无法在映射里二选一，需改名）")
    if empties:
        notes.append(f"空表头列：{', '.join(str(item + 1) for item in empties)}")

    preview = data[:preview_records]
    return TableView(
        kind="table", file_id=path.name, size=len(payload), suffix=path.suffix.lower(),
        delimiter="", delimiter_source="sheet", encoding="utf-8",
        sheet=chosen, sheets=sheets, sheet_required=sheet_required, header_row=used_header,
        columns=columns, rows=preview, cached_rows=cached_rows,
        records=len(rows), physical_lines=len(rows), preview_rows=len(preview),
        truncated=len(data) > preview_records, ragged_rows=ragged,
        duplicate_headers=duplicates, empty_headers=empties, has_formulas=has_formulas,
        notes=notes,
    )


def _worksheet_rows(worksheet, path: Path) -> list[list[str]]:
    """Materialise one worksheet as text rows, bounded like SteelData does.

    openpyxl pads **every** row to ``worksheet.max_column`` with empty cells, so
    a genuinely ragged sheet (a row with fewer values, or a value beyond the
    header width) would otherwise look perfectly rectangular — and a trailing
    empty cell would masquerade as a phantom extra column. Trailing empties are
    therefore stripped per row, which restores the true field count without
    touching leading/interior empties (those are meaningful empty values).
    """
    max_row = getattr(worksheet, "max_row", None)
    max_column = getattr(worksheet, "max_column", None)
    if max_row and max_row > MAX_ROWS:
        raise TableError(f"工作表超过 {MAX_ROWS} 行上限：{path.name}")
    if max_column and max_column > MAX_COLUMNS:
        raise TableError(f"工作表超过 {MAX_COLUMNS} 列上限：{path.name}")
    rows: list[list[str]] = []
    for row in worksheet.iter_rows(values_only=True):
        values = ["" if cell is None else str(cell) for cell in row]
        while values and not values[-1].strip():
            values.pop()
        rows.append(values)
        _bbox(rows, path)
    _check_cells(rows, path)
    return rows


def read_table(path: Path, *, sheet: str | None = None, header_row: int = 1,
               preview_records: int = 25) -> TableView:
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
        return _read_xlsx(path, payload, sheet=sheet, header_row=header_row,
                          preview_records=preview_records)
    if sheet:
        raise TableError(f"sheet 只能用于 XLSX；{path.name} 是 {suffix} 文本文件。")

    text = _read_text(path, payload)
    delimiter = _delimiter_for(suffix)
    notes: list[str] = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        rows = []
        for row in reader:
            rows.append(row)
            _bbox(rows, path)
        _check_cells(rows, path)
    except csv.Error as exc:
        raise TableError(f"CSV 语法错误（引号未闭合或分隔符不合法）：{exc}") from exc

    header, data, ragged, used_header = _frame(rows, header_row=header_row,
                                               preview_records=preview_records,
                                               label="文件")
    duplicates, empties, columns = _scan_headers(header)
    physical = text.count("\n") + (0 if not text or text.endswith("\n") else 1)
    if physical != len(rows):
        notes.append(f"物理行 {physical} 与逻辑记录 {len(rows)} 不一致：字段内含引号换行，"
                     "按 csv 逻辑记录计数。")
    # 分隔符只有后缀这一套规则（与 SteelData 一致）；表头里看不到该分隔符时
    # 只如实提示，不另换一套规则去解析。
    header_text = text.splitlines()[used_header - 1] if text.splitlines() else ""
    if header_text and delimiter not in header_text:
        others = [item for item in _CANDIDATE_DELIMITERS
                  if item != delimiter and item in header_text]
        if others:
            shown = "、".join(_DELIMITER_LABEL.get(item, repr(item)) for item in others)
            notes.append(f"后缀是 {suffix}，但表头行里没有{_DELIMITER_LABEL[delimiter]}；"
                         f"检测到{shown}。按 SteelData 合同仍以 {_DELIMITER_LABEL[delimiter]}"
                         "解析，请确认导出格式是否正确。")
    if duplicates:
        notes.append(f"重复表头：{', '.join(duplicates)}（无法在映射里二选一，需改名）")
    if empties:
        notes.append(f"空表头列：{', '.join(str(item + 1) for item in empties)}")
    preview = data[:preview_records]
    return TableView(
        kind="table", file_id=path.name, size=len(payload), suffix=suffix,
        delimiter=delimiter, delimiter_source="suffix",
        encoding="utf-8-sig" if payload.startswith(b"\xef\xbb\xbf") else "utf-8",
        sheet=None, sheets=[], sheet_required=False, header_row=used_header,
        columns=columns, rows=preview, records=len(rows),
        physical_lines=physical, preview_rows=len(preview),
        truncated=len(data) > preview_records, ragged_rows=ragged,
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
