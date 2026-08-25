"""meshctx data_pipeline — v3.111 stub"""
from __future__ import annotations
import csv
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class ProcessingMode(Enum):
    BATCH = "batch"
    STREAM = "stream"


class PipelineState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


class DataSourceType(Enum):
    MEMORY = "memory"
    FILE = "file"
    HTTP = "http"


class ValidationLevel(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationResult:
    check_name: str = ""
    level: ValidationLevel = ValidationLevel.ERROR
    passed: bool = True
    message: str = ""
    field: str = ""
    actual_value: Any = None
    expected_value: Any = None


@dataclass
class DataRecord:
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    source_type: str = ""
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    validation_results: list[ValidationResult] = field(default_factory=list)
    extracted_at: str | None = None


@dataclass
class PipelineStats:
    total_records: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    success_rate: float = 1.0
    total_extracted: int = 0
    total_transformed: int = 0
    total_loaded: int = 0
    elapsed_seconds: float = 0.0
    stages: dict[str, float] = field(default_factory=lambda: {"extract_ms": 0.0, "transform_ms": 0.0, "validate_ms": 0.0, "load_ms": 0.0})

    def to_dict(self, **kw) -> dict:
        return {
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "invalid_records": self.invalid_records,
            "success_rate": self.success_rate,
            "total_extracted": self.total_extracted,
            "total_transformed": self.total_transformed,
            "total_loaded": self.total_loaded,
            "elapsed_seconds": self.elapsed_seconds,
            "stages": self.stages,
        }


# ── Connectors ─────────────────────────────────────────────

class DataSourceConnector:
    def __init__(self, *args, **kwargs):
        pass

    def extract_all(self, **kw) -> list[DataRecord]:
        return []


class MemoryConnector(DataSourceConnector):
    def __init__(self, data: list[dict], name: str = "memory", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._data = data
        self._name = name

    def extract_all(self, **kw) -> list[DataRecord]:
        records = []
        for item in self._data:
            records.append(DataRecord(
                data=dict(item), source=self._name,
                source_type=DataSourceType.MEMORY.value,
                extracted_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            ))
        return records


class FileConnector(DataSourceConnector):
    SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl", ".txt"}

    def __init__(self, filepath: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._filepath = Path(filepath)
        ext = self._filepath.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {ext}")

    def extract_all(self, **kw) -> list[DataRecord]:
        ext = self._filepath.suffix.lower()
        fname = self._filepath.name
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if ext == ".csv":
            return self._read_delimited(",", fname, now)
        elif ext == ".tsv":
            return self._read_delimited("\t", fname, now)
        elif ext == ".json":
            return self._read_json(fname, now)
        elif ext == ".jsonl":
            return self._read_jsonl(fname, now)
        elif ext == ".txt":
            return self._read_txt(fname, now)
        return []

    def _read_delimited(self, delimiter: str, fname: str, timestamp: str, **kw) -> list[DataRecord]:
        records = []
        with open(self._filepath, "r", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                records.append(DataRecord(
                    data=dict(row), source=fname,
                    source_type=DataSourceType.FILE.value,
                    extracted_at=timestamp,
                ))
        return records

    def _read_json(self, fname: str, timestamp: str, **kw) -> list[DataRecord]:
        with open(self._filepath, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [DataRecord(data=dict(item), source=fname,
                              source_type=DataSourceType.FILE.value, extracted_at=timestamp)
                    for item in data]
        else:
            return [DataRecord(data=dict(data), source=fname,
                              source_type=DataSourceType.FILE.value, extracted_at=timestamp)]

    def _read_jsonl(self, fname: str, timestamp: str, **kw) -> list[DataRecord]:
        records = []
        with open(self._filepath, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(DataRecord(
                        data=dict(json.loads(line)), source=fname,
                        source_type=DataSourceType.FILE.value, extracted_at=timestamp,
                    ))
        return records

    def _read_txt(self, fname: str, timestamp: str, **kw) -> list[DataRecord]:
        records = []
        with open(self._filepath, "r") as f:
            for line in f:
                line = line.rstrip("\n")
                records.append(DataRecord(
                    data={"line": line}, source=fname,
                    source_type=DataSourceType.FILE.value, extracted_at=timestamp,
                ))
        return records


class HttpConnector(DataSourceConnector):
    def __init__(self, url: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._url = url

    def extract_all(self, **kw) -> list[DataRecord]:
        return []


# ── Data Quality Validator ─────────────────────────────────

class DataQualityValidator:
    def __init__(self, **kw):
        self._rules: list[Callable] = []

    def add_rule(self, rule: Callable, **kw):
        self._rules.append(rule)

    def validate(self, record: DataRecord, **kw):
        record.is_valid = True
        record.validation_results = []
        record.errors = []
        for rule in self._rules:
            try:
                result = rule(record)
                record.validation_results.append(result)
                if not result.passed:
                    record.is_valid = False
                    record.errors.append(result.message)
            except Exception as e:
                record.is_valid = False
                record.errors.append(str(e))

    @staticmethod
    def not_null(field: str, **kw) -> Callable:
        def _rule(rec: DataRecord, **kw) -> ValidationResult:
            if field not in rec.data or rec.data[field] is None:
                return ValidationResult(check_name=f"not_null:{field}", level=ValidationLevel.ERROR, passed=False,
                                       message=f"Field '{field}' is missing or null", field=field)
            return ValidationResult(check_name=f"not_null:{field}", level=ValidationLevel.ERROR, passed=True,
                                   message="OK", field=field)
        return _rule

    @staticmethod
    def field_type(field: str, expected_type: type, **kw) -> Callable:
        def _rule(rec: DataRecord, **kw) -> ValidationResult:
            val = rec.data.get(field)
            if val is None:
                return ValidationResult(check_name=f"type:{field}", level=ValidationLevel.ERROR, passed=False,
                                       message=f"Field '{field}' is missing", field=field)
            if not isinstance(val, expected_type):
                return ValidationResult(check_name=f"type:{field}", level=ValidationLevel.ERROR, passed=False,
                                       message=f"Field '{field}' expected {expected_type.__name__}, got {type(val).__name__}", field=field,
                                       actual_value=val)
            return ValidationResult(check_name=f"type:{field}", level=ValidationLevel.ERROR, passed=True,
                                   message="OK", field=field)
        return _rule

    @staticmethod
    def field_in(field: str, allowed: set, **kw) -> Callable:
        def _rule(rec: DataRecord, **kw) -> ValidationResult:
            val = rec.data.get(field)
            if val not in allowed:
                return ValidationResult(check_name=f"in:{field}", level=ValidationLevel.ERROR, passed=False,
                                       message=f"Field '{field}' value '{val}' not in allowed set",
                                       field=field, actual_value=val)
            return ValidationResult(check_name=f"in:{field}", level=ValidationLevel.ERROR, passed=True,
                                   message="OK", field=field)
        return _rule

    @staticmethod
    def field_range(field: str, min_val: float | None = None, max_val: float | None = None, **kw) -> Callable:
        def _rule(rec: DataRecord, **kw) -> ValidationResult:
            val = rec.data.get(field)
            if val is None:
                return ValidationResult(check_name=f"range:{field}", level=ValidationLevel.ERROR, passed=False,
                                       message=f"Field '{field}' is missing", field=field)
            try:
                num = float(val)
            except (TypeError, ValueError):
                return ValidationResult(check_name=f"range:{field}", level=ValidationLevel.ERROR, passed=False,
                                       message=f"Field '{field}' value '{val}' is not numeric", field=field, actual_value=val)
            if min_val is not None and num < min_val:
                return ValidationResult(check_name=f"range:{field}", level=ValidationLevel.ERROR, passed=False,
                                       message=f"Field '{field}' value {num} < min {min_val}", field=field, actual_value=num, expected_value=f">={min_val}")
            if max_val is not None and num > max_val:
                return ValidationResult(check_name=f"range:{field}", level=ValidationLevel.ERROR, passed=False,
                                       message=f"Field '{field}' value {num} > max {max_val}", field=field, actual_value=num, expected_value=f"<={max_val}")
            return ValidationResult(check_name=f"range:{field}", level=ValidationLevel.ERROR, passed=True,
                                   message="OK", field=field)
        return _rule

    @staticmethod
    def field_pattern(field: str, pattern: str, **kw) -> Callable:
        def _rule(rec: DataRecord, **kw) -> ValidationResult:
            val = rec.data.get(field)
            if val is None:
                return ValidationResult(check_name=f"pattern:{field}", level=ValidationLevel.ERROR, passed=False,
                                       message=f"Field '{field}' is missing", field=field)
            if not re.match(pattern, str(val)):
                return ValidationResult(check_name=f"pattern:{field}", level=ValidationLevel.ERROR, passed=False,
                                       message=f"Field '{field}' value '{val}' does not match pattern", field=field, actual_value=val)
            return ValidationResult(check_name=f"pattern:{field}", level=ValidationLevel.ERROR, passed=True,
                                   message="OK", field=field)
        return _rule

    @staticmethod
    def custom_rule(name: str, validator_fn: Callable, **kw) -> Callable:
        def _rule(rec: DataRecord, **kw) -> ValidationResult:
            passed, message = validator_fn(rec)
            return ValidationResult(check_name=name, level=ValidationLevel.ERROR, passed=passed,
                                   message=message)
        return _rule


# ── DataPipeline ───────────────────────────────────────────

class DataPipeline:
    def __init__(self, name: str = "", *args, **kwargs):
        self.name = name
        self._sources: list[DataSourceConnector] = []
        self._transforms: list[Callable[[DataRecord], DataRecord]] = []
        self._validators: list[DataQualityValidator] = []
        self._sinks: list[Callable[[DataRecord], None]] = []
        self._records: list[DataRecord] = []
        self.state: PipelineState = PipelineState.IDLE
        self._stats = PipelineStats()
        self._stop_flag = False

    @property
    def source_count(self, **kw) -> int:
        return len(self._sources)

    @property
    def transform_count(self, **kw) -> int:
        return len(self._transforms)

    @property
    def stats(self, **kw) -> PipelineStats:
        return self._stats

    def add_source(self, source: DataSourceConnector, **kw):
        self._sources.append(source)

    def add_transform(self, transform: Callable[[DataRecord], DataRecord], **kw):
        self._transforms.append(transform)

    def add_validator(self, validator: DataQualityValidator, **kw):
        self._validators.append(validator)

    def add_sink(self, sink: Callable[[DataRecord], None], **kw):
        self._sinks.append(sink)

    def run_batch(self, **kw) -> PipelineStats:
        return self._run_impl(stream=False)

    def run_stream(self, **kw):
        self.state = PipelineState.RUNNING
        self._records = []
        self._stats = PipelineStats()
        self._stop_flag = False
        t0 = time.time()
        t_extract_start = time.time()
        records = self._extract()
        self._stats.total_extracted = len(records)
        self._stats.stages["extract_ms"] = (time.time() - t_extract_start) * 1000
        t_transform_start = time.time()
        records = self._transform(records)
        self._stats.total_transformed = len(records)
        self._stats.stages["transform_ms"] = (time.time() - t_transform_start) * 1000
        t_validate_start = time.time()
        records = self._validate(records)
        self._stats.stages["validate_ms"] = (time.time() - t_validate_start) * 1000
        t_load_start = time.time()
        for rec in records:
            if self._stop_flag:
                break
            self._load_one(rec)
            self._records.append(rec)
            yield rec
        self._stats.stages["load_ms"] = (time.time() - t_load_start) * 1000
        self._stats.total_records = len(records)
        self._stats.valid_records = sum(1 for r in records if r.is_valid)
        self._stats.invalid_records = self._stats.total_records - self._stats.valid_records
        self._stats.success_rate = self._stats.valid_records / max(self._stats.total_records, 1) if self._stats.total_records > 0 else 1.0
        self._stats.total_loaded = len(records)
        self._stats.elapsed_seconds = time.time() - t0
        self.state = PipelineState.COMPLETED

    def _run_impl(self, stream: bool = False, **kw) -> PipelineStats:
        self.state = PipelineState.RUNNING
        self._records = []
        self._stats = PipelineStats()
        self._stop_flag = False
        t0 = time.time()
        t_extract_start = time.time()
        records = self._extract()
        self._stats.total_extracted = len(records)
        self._stats.stages["extract_ms"] = (time.time() - t_extract_start) * 1000
        t_transform_start = time.time()
        records = self._transform(records)
        self._stats.total_transformed = len(records)
        self._stats.stages["transform_ms"] = (time.time() - t_transform_start) * 1000
        t_validate_start = time.time()
        records = self._validate(records)
        self._stats.stages["validate_ms"] = (time.time() - t_validate_start) * 1000
        t_load_start = time.time()
        for rec in records:
            if self._stop_flag:
                break
            self._load_one(rec)
        self._records = records
        self._stats.stages["load_ms"] = (time.time() - t_load_start) * 1000
        self._stats.total_records = len(records)
        self._stats.valid_records = sum(1 for r in records if r.is_valid)
        self._stats.invalid_records = self._stats.total_records - self._stats.valid_records
        self._stats.success_rate = self._stats.valid_records / max(self._stats.total_records, 1) if self._stats.total_records > 0 else 1.0
        self._stats.total_loaded = len(records)
        self._stats.elapsed_seconds = time.time() - t0
        self.state = PipelineState.COMPLETED
        return self._stats

    def _extract(self, **kw) -> list[DataRecord]:
        records = []
        for source in self._sources:
            records.extend(source.extract_all())
        return records

    def _transform(self, records: list[DataRecord], **kw) -> list[DataRecord]:
        result = []
        for rec in records:
            try:
                r = rec
                for tf in self._transforms:
                    r = tf(r)
                result.append(r)
            except Exception as e:
                rec.errors.append(f"transform error: {e}")
                result.append(rec)
        return result

    def _validate(self, records: list[DataRecord], **kw) -> list[DataRecord]:
        for validator in self._validators:
            for rec in records:
                validator.validate(rec)
        return records

    def _load_one(self, record: DataRecord, **kw):
        for sink in self._sinks:
            try:
                sink(record)
            except Exception as e:
                record.errors.append(f"sink error: {e}")

    def get_records(self, **kw) -> list[DataRecord]:
        return list(self._records)

    def record_count(self, **kw) -> int:
        return len(self._records)

    def reset(self, **kw):
        self._records = []
        self._stats = PipelineStats()
        self.state = PipelineState.IDLE
        self._stop_flag = False

    def clear(self, **kw):
        self._sources.clear()
        self._transforms.clear()
        self._validators.clear()
        self._sinks.clear()
        self.reset()

    def stop(self, **kw):
        self._stop_flag = True

    def __enter__(self, **kw):
        return self

    def __exit__(self, *args, **kw):
        pass


# ── Singleton ──────────────────────────────────────────────

_data_pipeline_instance: DataPipeline | None = None


def get_data_pipeline(name: str = "") -> DataPipeline:
    global _data_pipeline_instance
    if _data_pipeline_instance is None:
        _data_pipeline_instance = DataPipeline(name=name)
    return _data_pipeline_instance


def reset_data_pipeline():
    global _data_pipeline_instance
    _data_pipeline_instance = None




# ── Legacy alias layer (2026-08-25 004meshctx 审计补齐) ──
# 兼容 _known 映射中声明的旧符号名, 保持 from src.core import X 契约不变
def __getattr__(name):
    if name == "PipelineStage":
        return PipelineState
    raise AttributeError(name)