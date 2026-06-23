"""
meshctx — Spreadsheet Tool (对标 Tencent WorkBuddy)

分析 Excel/CSV 表格数据：查找趋势、创建图表、生成摘要。
依赖 pandas + openpyxl + matplotlib（可选，优雅降级）。

Tool name: spreadsheet
"""

import csv
import io
import os
import warnings
from typing import Any

warnings.filterwarnings("ignore", category=UserWarning)


def _ensure_pandas():
    """Ensure pandas is available; raise helpful error if not."""
    try:
        import pandas as pd  # noqa: F401
        return pd
    except ImportError:
        raise RuntimeError(
            "spreadsheet tool requires pandas. Install: pip install pandas openpyxl"
        )


def _df_to_dicts(df) -> list[dict]:
    """Convert DataFrame to list-of-dicts, handling NaN/NaT."""
    import numpy as np
    out = []
    for _, row in df.iterrows():
        d = {}
        for k, v in row.items():
            if isinstance(v, float) and np.isnan(v):
                d[str(k)] = None
            elif hasattr(v, 'isoformat'):
                d[str(k)] = v.isoformat()
            elif isinstance(v, (np.integer,)):
                d[str(k)] = int(v)
            elif isinstance(v, (np.floating,)):
                d[str(k)] = float(v)
            else:
                d[str(k)] = v
        out.append(d)
    return out


def spreadsheet_read(file_path: str, sheet_name: str | int = 0, nrows: int = 100) -> dict:
    """Read spreadsheet file (.xlsx/.xls/.csv/.ods) and return contents as table.

    Args:
        file_path: Path to spreadsheet file.
        sheet_name: Sheet name or index (for Excel/ODS).
        nrows: Max rows to return.

    Returns:
        {"ok": True, "file": ..., "sheet": ..., "shape": [rows, cols],
         "columns": [...], "data": [...], "dtypes": {...}}
    """
    file_path = os.path.expanduser(file_path)
    if not os.path.exists(file_path):
        return {"ok": False, "error": f"File not found: {file_path}"}

    pd = _ensure_pandas()
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.csv':
            df = pd.read_csv(file_path, nrows=nrows)
        elif ext == '.tsv':
            df = pd.read_csv(file_path, sep='\t', nrows=nrows)
        elif ext in ('.xlsx', '.xls', '.xlsm'):
            df = pd.read_excel(file_path, sheet_name=sheet_name, nrows=nrows)
        elif ext == '.ods':
            df = pd.read_excel(file_path, engine='odf', sheet_name=sheet_name, nrows=nrows)
        else:
            return {"ok": False, "error": f"Unsupported format: {ext}"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to read {file_path}: {e}"}

    df = df.head(nrows)
    return {
        "ok": True,
        "file": file_path,
        "sheet": str(sheet_name),
        "shape": [len(df), len(df.columns)],
        "columns": list(df.columns.astype(str)),
        "data": _df_to_dicts(df),
        "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
    }


def spreadsheet_stats(file_path: str, sheet_name: str | int = 0) -> dict:
    """Calculate descriptive statistics for numeric columns.

    Returns:
        {"ok": True, "stats": {column: {min, max, mean, median, std, count, sum, nulls}}, ...}
    """
    file_path = os.path.expanduser(file_path)
    if not os.path.exists(file_path):
        return {"ok": False, "error": f"File not found: {file_path}"}

    pd = _ensure_pandas()
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.csv':
            df = pd.read_csv(file_path)
        elif ext in ('.xlsx', '.xls', '.xlsm'):
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        elif ext == '.ods':
            df = pd.read_excel(file_path, engine='odf', sheet_name=sheet_name)
        else:
            return {"ok": False, "error": f"Unsupported format: {ext}"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to read {file_path}: {e}"}

    numeric_cols = df.select_dtypes(include=['number']).columns
    stats = {}
    for col in numeric_cols:
        s = df[col]
        stats[str(col)] = {
            "min": float(s.min()) if not s.isna().all() else None,
            "max": float(s.max()) if not s.isna().all() else None,
            "mean": round(float(s.mean()), 4) if not s.isna().all() else None,
            "median": round(float(s.median()), 4) if not s.isna().all() else None,
            "std": round(float(s.std()), 4) if not s.isna().all() else None,
            "count": int(s.count()),
            "sum": float(s.sum()) if not s.isna().all() else None,
            "nulls": int(s.isna().sum()),
        }
    return {"ok": True, "file": file_path, "sheet": str(sheet_name), "stats": stats}


def spreadsheet_chart(file_path: str, x_col: str, y_col: str,
                      chart_type: str = "line", sheet_name: str | int = 0,
                      save_path: str | None = None) -> dict:
    """Generate a chart from spreadsheet columns.

    Args:
        file_path: Path to spreadsheet.
        x_col: Column name for X axis.
        y_col: Column name for Y axis.
        chart_type: 'line', 'bar', 'scatter', 'pie', 'hist'.
        sheet_name: Sheet name/index.
        save_path: Path to save chart PNG. Auto-generated if None.

    Returns:
        {"ok": True, "chart_path": "/tmp/...", "chart_base64": "..."}
    """
    file_path = os.path.expanduser(file_path)
    if not os.path.exists(file_path):
        return {"ok": False, "error": f"File not found: {file_path}"}

    pd = _ensure_pandas()
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return {"ok": False, "error": "Chart requires matplotlib. Install: pip install matplotlib"}

    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.csv':
            df = pd.read_csv(file_path)
        elif ext in ('.xlsx', '.xls', '.xlsm'):
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        elif ext == '.ods':
            df = pd.read_excel(file_path, engine='odf', sheet_name=sheet_name)
        else:
            return {"ok": False, "error": f"Unsupported format: {ext}"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to read: {e}"}

    if x_col not in df.columns:
        return {"ok": False, "error": f"Column not found: '{x_col}'. Available: {list(df.columns)}"}
    if y_col not in df.columns:
        return {"ok": False, "error": f"Column not found: '{y_col}'. Available: {list(df.columns)}"}

    fig, ax = plt.subplots(figsize=(10, 6))
    x_data = df[x_col]
    y_data = df[y_col]

    chart_type = chart_type.lower()
    if chart_type == 'line':
        ax.plot(x_data, y_data, marker='o')
    elif chart_type == 'bar':
        ax.bar(x_data.astype(str), y_data)
        plt.xticks(rotation=45, ha='right')
    elif chart_type == 'scatter':
        ax.scatter(x_data, y_data, alpha=0.6)
    elif chart_type == 'pie':
        ax.pie(y_data, labels=x_data.astype(str), autopct='%1.1f%%')
    elif chart_type == 'hist':
        ax.hist(y_data.dropna(), bins=20, edgecolor='black')
        ax.set_xlabel(y_col)
        ax.set_ylabel('Frequency')
    else:
        plt.close(fig)
        return {"ok": False, "error": f"Unknown chart_type: {chart_type}. Use: line/bar/scatter/pie/hist"}

    ax.set_title(f"{y_col} by {x_col}")
    if chart_type != 'hist':
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
    ax.grid(chart_type not in ('pie', 'hist'))

    if save_path is None:
        import tempfile
        fd, save_path = tempfile.mkstemp(suffix='.png', prefix='meshctx_chart_')
        os.close(fd)

    fig.tight_layout()
    fig.savefig(save_path, dpi=100)
    plt.close(fig)

    import base64
    with open(save_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()

    return {
        "ok": True,
        "chart_path": save_path,
        "chart_base64": b64,
        "chart_type": chart_type,
        "x_col": x_col,
        "y_col": y_col,
    }


def spreadsheet_trend(file_path: str, y_col: str,
                      date_col: str | None = None,
                      sheet_name: str | int = 0) -> dict:
    """Detect trends in a numeric column (increasing/decreasing/stable).

    Returns:
        {"ok": True, "trend": "increasing"|"decreasing"|"stable",
         "slope": ..., "r_squared": ..., "change_pct": ...}
    """
    file_path = os.path.expanduser(file_path)
    if not os.path.exists(file_path):
        return {"ok": False, "error": f"File not found: {file_path}"}

    pd = _ensure_pandas()
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.csv':
            df = pd.read_csv(file_path)
        elif ext in ('.xlsx', '.xls', '.xlsm'):
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        elif ext == '.ods':
            df = pd.read_excel(file_path, engine='odf', sheet_name=sheet_name)
        else:
            return {"ok": False, "error": f"Unsupported format: {ext}"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to read: {e}"}

    if y_col not in df.columns:
        return {"ok": False, "error": f"Column '{y_col}' not found. Available: {list(df.columns)}"}

    import numpy as np
    y_vals = df[y_col].dropna().values
    if len(y_vals) < 3:
        return {"ok": False, "error": "Need at least 3 data points for trend detection"}

    x_vals = np.arange(len(y_vals))
    slope, intercept = np.polyfit(x_vals, y_vals, 1)
    y_pred = slope * x_vals + intercept
    ss_res = np.sum((y_vals - y_pred) ** 2)
    ss_tot = np.sum((y_vals - np.mean(y_vals)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    if abs(slope) < 0.01 * abs(np.mean(y_vals)):
        trend = "stable"
    elif slope > 0:
        trend = "increasing"
    else:
        trend = "decreasing"

    change_pct = ((y_vals[-1] - y_vals[0]) / abs(y_vals[0]) * 100) if y_vals[0] != 0 else 0

    return {
        "ok": True,
        "file": file_path,
        "column": y_col,
        "trend": trend,
        "slope": round(float(slope), 6),
        "r_squared": round(float(r_squared), 4),
        "change_pct": round(float(change_pct), 2),
        "data_points": len(y_vals),
        "first_value": float(y_vals[0]),
        "last_value": float(y_vals[-1]),
    }


# ── Tool-callable entry point ──

def spreadsheet_analyze(file_path: str, action: str = "read",
                        sheet_name: str | int = 0,
                        x_col: str = "", y_col: str = "",
                        chart_type: str = "line",
                        save_path: str | None = None,
                        nrows: int = 100) -> dict:
    """Main entry point for the spreadsheet tool.

    Actions:
        - 'read': Read spreadsheet contents.
        - 'stats': Descriptive stats for numeric columns.
        - 'chart': Generate a chart.
        - 'trend': Detect trend in a column.
    """
    action = action.lower()
    if action == 'read':
        return spreadsheet_read(file_path, sheet_name=sheet_name, nrows=nrows)
    elif action == 'stats':
        return spreadsheet_stats(file_path, sheet_name=sheet_name)
    elif action == 'chart':
        return spreadsheet_chart(
            file_path, x_col=x_col, y_col=y_col,
            chart_type=chart_type, sheet_name=sheet_name,
            save_path=save_path,
        )
    elif action == 'trend':
        return spreadsheet_trend(file_path, y_col=y_col, sheet_name=sheet_name)
    else:
        return {"ok": False, "error": f"Unknown action: {action}. Use: read/stats/chart/trend"}
