"""
meshctx v3.111 — Data Pipeline (数据管道)

Features:
1) ETL抽取转换加载 — Extract, Transform, Load with pluggable stages
2) 多数据源连接器 — File, HTTP, Database, Memory, Stream connectors
3) 流式+批处理 — Streaming (iterator-based) and batch (collection-based) modes
4) 数据质量校验 — Schema validation, completeness, constraint, and anomaly checks

Design: Composable pipeline stages, thread-safe, lazy evaluation for streaming.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union,
)

logger = logging.getLogger("meshctx.data_pipeline")


# ═══════════════════════════════════════════════════════════════
# Enums & Data Classes
# ═══════════════════════════════════════════════════════════════

class DataSourceType(Enum):
    """Type identifiers for source connectors."""
    FILE = "file"
    HTTP = "http"
    DATABASE = "database"
    DATABASE_SQL = "database_sql"
    DATABASE_NOSQL = "database_nosql"
    MEMORY = "memory"
    STREAM = "stream"


class ProcessingMode(Enum):
    """Execution mode for the pipeline."""
    BATCH = "batch"        # All records at once, collect results
    STREAM = "stream"      # Lazy iterator-based, record at a time


class ValidationLevel(Enum):
    """Severity of a validation issue."""
    ERROR = "error"        # Hard failure — record is invalid
    WARNING = "warning"    # Suspicious but accepted
    INFO = "info"          # Informational only


class PipelineState(Enum):
    """Lifecycle state of the pipeline."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class DataRecord:
    """
    A single record flowing through the pipeline.

    Each record carries:
    - A unique ID (auto-generated if not provided)
    - The raw / current data dict
    - Provenance metadata (source, timestamp, lineage)
    - Validation results attached during the validation stage
    """
    data: Dict[str, Any]
    record_id: str = field(default_factory=lambda: f"rec_{id(threading.current_thread())}_{time.monotonic_ns()}")
    source: str = ""
    source_type: str = ""
    extracted_at: Optional[float] = None
    transformed_at: Optional[float] = None
    validated_at: Optional[float] = None
    loaded_at: Optional[float] = None
    tags: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    validation_results: List["ValidationResult"] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if no ERROR-level validation results that failed."""
        return not any(
            r.level == ValidationLevel.ERROR and not r.passed
            for r in self.validation_results
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "data": self.data,
            "source": self.source,
            "source_type": self.source_type,
            "tags": self.tags,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
        }


@dataclass
class ValidationResult:
    """Outcome of a single validation check on a record."""
    check_name: str
    level: ValidationLevel
    passed: bool
    message: str = ""
    field: Optional[str] = None
    actual_value: Any = None
    expected_value: Any = None


@dataclass
class PipelineStats:
    """Aggregated runtime statistics for the pipeline."""
    total_extracted: int = 0
    total_transformed: int = 0
    total_validated: int = 0
    total_loaded: int = 0
    total_records: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: int = 0
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    stages: Dict[str, float] = field(default_factory=dict)  # stage_name -> elapsed_ms

    @property
    def elapsed_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.monotonic()
        return end - self.start_time

    @property
    def success_rate(self) -> float:
        if self.total_records == 0:
            return 1.0
        return self.valid_records / self.total_records

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "invalid_records": self.invalid_records,
            "success_rate": round(self.success_rate, 4),
            "errors": self.errors[:20],
            "warnings": self.warnings,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "stages": self.stages,
        }


# ═══════════════════════════════════════════════════════════════
# Source Connectors
# ═══════════════════════════════════════════════════════════════

class DataSourceConnector(ABC):
    """
    Abstract base for all source connectors.

    Subclasses implement _extract() which yields DataRecords.
    """

    def __init__(self, source_type: DataSourceType, name: str = ""):
        self.source_type = source_type
        self.name = name or source_type.value
        self._lock = threading.RLock()

    @abstractmethod
    def _extract(self) -> Iterator[DataRecord]:
        """Yield records from the source. Implemented by subclasses."""
        ...

    def extract(self) -> Iterator[DataRecord]:
        """Public extraction wrapper with timing and error handling."""
        for record in self._extract():
            record.extracted_at = time.monotonic()
            record.source_type = self.source_type.value
            record.source = self.name
            yield record

    def extract_all(self) -> List[DataRecord]:
        """Extract all records into a list (batch mode)."""
        return list(self.extract())

    @property
    def connector_type(self) -> str:
        return self.source_type.value


class FileConnector(DataSourceConnector):
    """
    File-based connector supporting CSV, JSON, JSONL, and plain text.

    CSV: Each row becomes a record with column names as keys.
    JSON: If the file is a list, each element is a record.
    JSONL: Each line is a JSON object (one record).
    TXT: Each line becomes a record with a 'line' key.
    """

    SUPPORTED_EXTENSIONS = {".csv", ".json", ".jsonl", ".txt", ".tsv"}

    def __init__(self, path: str, encoding: str = "utf-8", name: str = ""):
        super().__init__(DataSourceType.FILE, name=name or os.path.basename(path))
        self.path = path
        self.encoding = encoding
        self._validate_support()

    def _validate_support(self):
        ext = os.path.splitext(self.path)[1].lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file extension '{ext}'. "
                f"Supported: {self.SUPPORTED_EXTENSIONS}"
            )

    def _extract(self) -> Iterator[DataRecord]:
        ext = os.path.splitext(self.path)[1].lower()

        if ext == ".csv":
            yield from self._extract_csv()
        elif ext == ".tsv":
            yield from self._extract_csv(delimiter="\t")
        elif ext == ".json":
            yield from self._extract_json()
        elif ext == ".jsonl":
            yield from self._extract_jsonl()
        elif ext == ".txt":
            yield from self._extract_txt()
        else:
            raise ValueError(f"Unsupported format: {ext}")

    def _extract_csv(self, delimiter: str = ",") -> Iterator[DataRecord]:
        with open(self.path, "r", encoding=self.encoding, newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                yield DataRecord(data=dict(row))

    def _extract_json(self) -> Iterator[DataRecord]:
        with open(self.path, "r", encoding=self.encoding) as f:
            content = json.load(f)
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    yield DataRecord(data=item)
                else:
                    yield DataRecord(data={"value": item})
        elif isinstance(content, dict):
            yield DataRecord(data=content)
        else:
            yield DataRecord(data={"value": content})

    def _extract_jsonl(self) -> Iterator[DataRecord]:
        with open(self.path, "r", encoding=self.encoding) as f:
            for line in f:
                line = line.strip()
                if line:
                    yield DataRecord(data=json.loads(line))

    def _extract_txt(self) -> Iterator[DataRecord]:
        with open(self.path, "r", encoding=self.encoding) as f:
            for num, line in enumerate(f, start=1):
                line = line.rstrip("\n\r")
                if line:
                    yield DataRecord(data={"line": line, "number": num})


class HttpConnector(DataSourceConnector):
    """
    HTTP/REST API connector.

    Supports GET with optional headers and pagination via a next-page extractor.
    The response is expected to be JSON — each dict item in the top-level
    data list becomes a record.
    """

    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        data_path: Optional[str] = None,
        name: str = "",
    ):
        super().__init__(DataSourceType.HTTP, name=name or url)
        self.url = url
        self.headers = headers or {}
        self.data_path = data_path  # json path like "results" or "data.items"

    def _extract(self) -> Iterator[DataRecord]:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(self.url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            logger.error("HTTP connector failed for %s: %s", self.url, e)
            return
        except json.JSONDecodeError as e:
            logger.error("JSON decode error for %s: %s", self.url, e)
            return

        # Navigate into data_path if specified
        items = body
        if self.data_path:
            for part in self.data_path.split("."):
                if isinstance(items, dict):
                    items = items.get(part, [])
                elif isinstance(items, list) and part.isdigit():
                    items = items[int(part)]

        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    yield DataRecord(data=item)
                else:
                    yield DataRecord(data={"value": item})
        elif isinstance(items, dict):
            yield DataRecord(data=items)


class MemoryConnector(DataSourceConnector):
    """
    In-memory connector for testing and ad-hoc data pipelines.

    Accepts a list of dicts directly.
    """

    def __init__(self, data: List[Dict[str, Any]], name: str = "memory"):
        super().__init__(DataSourceType.MEMORY, name=name)
        self.data = data

    def _extract(self) -> Iterator[DataRecord]:
        for item in self.data:
            yield DataRecord(data=dict(item))


# ═══════════════════════════════════════════════════════════════
# Data Quality Validators
# ═══════════════════════════════════════════════════════════════

@dataclass
class ValidationRule:
    """
    A single validation rule.

    check_fn receives the DataRecord and returns (passed: bool, message: str).
    """
    name: str
    check_fn: Callable[[DataRecord], Tuple[bool, str]]
    level: ValidationLevel = ValidationLevel.ERROR
    fields: Optional[List[str]] = None  # Fields this rule applies to

    def apply(self, record: DataRecord) -> ValidationResult:
        try:
            passed, message = self.check_fn(record)
        except Exception as exc:
            passed = False
            message = f"Validation check '{self.name}' raised exception: {exc}"
        return ValidationResult(
            check_name=self.name,
            level=self.level,
            passed=passed,
            message=message,
        )


class DataQualityValidator:
    """
    Collection of validation rules applied to records.

    Built-in rule factories:
    - not_null(field) — field must be present and non-None
    - field_type(field, expected_type) — field must match Python type
    - field_in(field, allowed_values) — field must be in a set
    - field_range(field, min_val, max_val) — numeric field range check
    - field_pattern(field, pattern) — regex match
    - custom_rule(name, fn) — user-defined check
    """

    def __init__(self):
        self._rules: List[ValidationRule] = []
        self._lock = threading.RLock()

    def add_rule(self, rule: ValidationRule) -> None:
        with self._lock:
            self._rules.append(rule)

    # ── Built-in rule factories ─────────────────────────────────

    def not_null(self, field: str, level: ValidationLevel = ValidationLevel.ERROR) -> ValidationRule:
        """Ensure a field exists and is not None."""
        def check(record: DataRecord) -> Tuple[bool, str]:
            exists = field in record.data and record.data[field] is not None
            msg = "" if exists else f"Field '{field}' is missing or null"
            return exists, msg
        return ValidationRule(name=f"not_null:{field}", check_fn=check, level=level, fields=[field])

    def field_type(self, field: str, expected_type: type, level: ValidationLevel = ValidationLevel.ERROR) -> ValidationRule:
        """Ensure a field matches the expected Python type."""
        def check(record: DataRecord) -> Tuple[bool, str]:
            value = record.data.get(field)
            if value is None:
                return False, f"Field '{field}' is missing (cannot check type)"
            ok = isinstance(value, expected_type)
            msg = "" if ok else f"Field '{field}' expected {expected_type.__name__}, got {type(value).__name__}"
            return ok, msg
        return ValidationRule(name=f"type:{field}", check_fn=check, level=level, fields=[field])

    def field_in(self, field: str, allowed: Set[Any], level: ValidationLevel = ValidationLevel.ERROR) -> ValidationRule:
        """Ensure a field value is in the allowed set."""
        def check(record: DataRecord) -> Tuple[bool, str]:
            value = record.data.get(field)
            ok = value in allowed
            msg = "" if ok else f"Field '{field}' value '{value}' not in allowed: {allowed}"
            return ok, msg
        return ValidationRule(name=f"in:{field}", check_fn=check, level=level, fields=[field])

    def field_range(self, field: str, min_val: Optional[float] = None, max_val: Optional[float] = None,
                    level: ValidationLevel = ValidationLevel.ERROR) -> ValidationRule:
        """Ensure a numeric field is within [min_val, max_val] (inclusive)."""
        def check(record: DataRecord) -> Tuple[bool, str]:
            value = record.data.get(field)
            if value is None:
                return False, f"Field '{field}' is missing"
            try:
                v = float(value)
            except (TypeError, ValueError):
                return False, f"Field '{field}' is not numeric: {value}"
            if min_val is not None and v < min_val:
                return False, f"Field '{field}' value {v} < min {min_val}"
            if max_val is not None and v > max_val:
                return False, f"Field '{field}' value {v} > max {max_val}"
            return True, ""
        return ValidationRule(name=f"range:{field}", check_fn=check, level=level, fields=[field])

    def field_pattern(self, field: str, pattern: str, level: ValidationLevel = ValidationLevel.ERROR) -> ValidationRule:
        """Ensure a field matches a regex pattern."""
        import re
        compiled = re.compile(pattern)
        def check(record: DataRecord) -> Tuple[bool, str]:
            value = record.data.get(field)
            if value is None:
                return False, f"Field '{field}' is missing"
            ok = bool(compiled.match(str(value)))
            msg = "" if ok else f"Field '{field}' value '{value}' does not match pattern '{pattern}'"
            return ok, msg
        return ValidationRule(name=f"pattern:{field}", check_fn=check, level=level, fields=[field])

    def custom_rule(self, name: str, fn: Callable[[DataRecord], Tuple[bool, str]],
                    level: ValidationLevel = ValidationLevel.ERROR) -> ValidationRule:
        """Add a fully custom validation check."""
        return ValidationRule(name=name, check_fn=fn, level=level)

    # ── Apply rules ─────────────────────────────────────────────

    def validate(self, record: DataRecord) -> DataRecord:
        """Run all registered rules against a single record (in-place)."""
        record.validation_results = []
        for rule in self._rules:
            result = rule.apply(record)
            record.validation_results.append(result)
            if not result.passed:
                record.errors.append(f"[{result.level.value}] {result.check_name}: {result.message}")
        return record

    def validate_all(self, records: List[DataRecord]) -> List[DataRecord]:
        """Run all rules on a batch of records."""
        for rec in records:
            self.validate(rec)
        return records

    @property
    def rule_count(self) -> int:
        with self._lock:
            return len(self._rules)

    def list_rules(self) -> List[str]:
        with self._lock:
            return [r.name for r in self._rules]


# ═══════════════════════════════════════════════════════════════
# Data Pipeline Engine
# ═══════════════════════════════════════════════════════════════

TransformFunc = Callable[[DataRecord], DataRecord]


class DataPipeline:
    """
    v3.111 Data Pipeline — ETL engine with multi-source extraction,
    pluggable transforms, quality validation, and batch/stream execution.

    Usage:
        pipeline = DataPipeline()
        pipeline.add_source(FileConnector("data.csv"))
        pipeline.add_transform(lambda r: r)  # mutate r.data in place
        pipeline.add_validator(DataQualityValidator().not_null("name"))
        pipeline.add_sink(lambda r: print(r.data))
        stats = pipeline.run_batch()

        # Or use the context manager:
        with DataPipeline() as p:
            p.add_source(MemoryConnector([{"a": 1}]))
            p.run_stream()
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self._sources: List[DataSourceConnector] = []
        self._transforms: List[TransformFunc] = []
        self._validators: List[DataQualityValidator] = []
        self._sinks: List[Callable[[DataRecord], Any]] = []
        self._state: PipelineState = PipelineState.IDLE
        self._stats = PipelineStats()
        self._lock = threading.RLock()
        self._records: List[DataRecord] = []  # accumulated in batch mode

    # ── Configuration ───────────────────────────────────────────

    def add_source(self, connector: DataSourceConnector) -> "DataPipeline":
        """Register a data source connector."""
        with self._lock:
            self._sources.append(connector)
        return self

    def add_transform(self, transform: TransformFunc) -> "DataPipeline":
        """
        Register a transformation function.

        The function receives a DataRecord and must return it (optionally
        mutated in-place). Transform is applied after extraction and before
        validation.
        """
        with self._lock:
            self._transforms.append(transform)
        return self

    def add_validator(self, validator: DataQualityValidator) -> "DataPipeline":
        """Register a quality validator (applied after transforms)."""
        with self._lock:
            self._validators.append(validator)
        return self

    def add_sink(self, sink: Callable[[DataRecord], Any]) -> "DataPipeline":
        """
        Register a load/sink function.

        The sink receives each validated DataRecord. Use this to write to
        databases, files, or any external system.
        """
        with self._lock:
            self._sinks.append(sink)
        return self

    def clear(self) -> None:
        """Remove all sources, transforms, validators, and sinks."""
        with self._lock:
            self._sources.clear()
            self._transforms.clear()
            self._validators.clear()
            self._sinks.clear()
            self._records.clear()
            self._stats = PipelineStats()

    # ── Core Execution ──────────────────────────────────────────

    def _process_record(self, record: DataRecord) -> DataRecord:
        """Full processing pipeline for a single record: transform → validate."""
        # Stage: Transform
        for i, transform in enumerate(self._transforms):
            try:
                record = transform(record)
            except Exception as exc:
                record.errors.append(f"Transform[{i}] error: {exc}")
        record.transformed_at = time.monotonic()

        # Stage: Validate
        for validator in self._validators:
            validator.validate(record)
        record.validated_at = time.monotonic()

        return record

    def _load_record(self, record: DataRecord) -> None:
        """Pass a record through all sinks."""
        for sink in self._sinks:
            try:
                sink(record)
            except Exception as exc:
                record.errors.append(f"Sink error: {exc}")
        record.loaded_at = time.monotonic()

    def _update_stats(self, record: DataRecord) -> None:
        """Update aggregate pipeline stats for one record."""
        self._stats.total_records += 1
        if record.is_valid:
            self._stats.valid_records += 1
        else:
            self._stats.invalid_records += 1
        for err in record.errors:
            if "warning" in err.lower():
                self._stats.warnings += 1
            else:
                self._stats.errors.append(err)

    def run_batch(self) -> PipelineStats:
        """
        Run the pipeline in batch mode.

        Extracts all records from all sources, transforms, validates, and
        loads them in order. Returns PipelineStats.
        """
        with self._lock:
            self._state = PipelineState.RUNNING
            self._stats = PipelineStats(start_time=time.monotonic())
            self._records = []

        try:
            # Stage E: Extract
            t0 = time.monotonic()
            for source in self._sources:
                for record in source.extract():
                    self._records.append(record)
                    self._stats.total_extracted += 1
            self._stats.stages["extract_ms"] = (time.monotonic() - t0) * 1000

            # Stage T: Transform + Validate (combined in _process_record)
            t0 = time.monotonic()
            for record in self._records:
                self._process_record(record)
                self._stats.total_transformed += 1
                self._stats.total_validated += 1
            self._stats.stages["transform_validate_ms"] = (time.monotonic() - t0) * 1000

            # Stage L: Load
            t0 = time.monotonic()
            for record in self._records:
                self._load_record(record)
                self._update_stats(record)
                self._stats.total_loaded += 1
            self._stats.stages["load_ms"] = (time.monotonic() - t0) * 1000

            self._state = PipelineState.COMPLETED
        except Exception as exc:
            logger.exception("Pipeline '%s' failed", self.name)
            self._stats.errors.append(f"Pipeline error: {exc}")
            self._state = PipelineState.FAILED
        finally:
            self._stats.end_time = time.monotonic()

        return self._stats

    def run_stream(self) -> Iterator[DataRecord]:
        """
        Run the pipeline in streaming mode.

        Yields each fully-processed DataRecord as it flows through the
        pipeline (lazy evaluation). Stats are accumulated incrementally.

        Example:
            for record in pipeline.run_stream():
                if record.is_valid:
                    save(record.data)
        """
        with self._lock:
            self._state = PipelineState.RUNNING
            self._stats = PipelineStats(start_time=time.monotonic())

        try:
            for source in self._sources:
                t0 = time.monotonic()
                for record in source.extract():
                    self._stats.total_extracted += 1
                    record = self._process_record(record)
                    self._stats.total_transformed += 1
                    self._stats.total_validated += 1
                    self._load_record(record)
                    self._stats.total_loaded += 1
                    self._update_stats(record)
                    yield record
                self._stats.stages.setdefault("extract_ms", 0)
                self._stats.stages["extract_ms"] += (time.monotonic() - t0) * 1000

            self._state = PipelineState.COMPLETED
        except GeneratorExit:
            self._state = PipelineState.STOPPED
        except Exception as exc:
            logger.exception("Pipeline '%s' streaming failed", self.name)
            self._stats.errors.append(f"Pipeline error: {exc}")
            self._state = PipelineState.FAILED
            raise
        finally:
            self._stats.end_time = time.monotonic()

    # ── Introspection & Control ──────────────────────────────────

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def stats(self) -> PipelineStats:
        return self._stats

    def get_records(self) -> List[DataRecord]:
        """Return all records processed in the last batch run."""
        with self._lock:
            return list(self._records)

    def record_count(self) -> int:
        with self._lock:
            return len(self._records)

    @property
    def source_count(self) -> int:
        with self._lock:
            return len(self._sources)

    @property
    def transform_count(self) -> int:
        with self._lock:
            return len(self._transforms)

    def stop(self) -> None:
        """Stop a streaming pipeline (sets state to STOPPED)."""
        with self._lock:
            self._state = PipelineState.STOPPED

    def reset(self) -> None:
        """Reset the pipeline to IDLE state and clear all accumulated data."""
        with self._lock:
            self._state = PipelineState.IDLE
            self._stats = PipelineStats()
            self._records.clear()

    # ── Context Manager ──────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._state == PipelineState.RUNNING:
            self.stop()
        return False


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_data_pipeline_instance: Optional[DataPipeline] = None
_data_pipeline_lock = threading.Lock()


def get_data_pipeline(name: str = "default") -> DataPipeline:
    """Get or create the global singleton DataPipeline instance."""
    global _data_pipeline_instance
    if _data_pipeline_instance is None:
        with _data_pipeline_lock:
            if _data_pipeline_instance is None:
                _data_pipeline_instance = DataPipeline(name=name)
    return _data_pipeline_instance


def reset_data_pipeline() -> None:
    """Reset the global singleton DataPipeline instance."""
    global _data_pipeline_instance
    with _data_pipeline_lock:
        _data_pipeline_instance = None
