"""v3.111 Data Pipeline 数据管道测试"""
import json
import os
import tempfile
import time

import pytest

from src.core.data_pipeline import (
    DataPipeline,
    DataRecord,
    DataSourceConnector,
    DataSourceType,
    DataQualityValidator,
    FileConnector,
    HttpConnector,
    MemoryConnector,
    PipelineState,
    PipelineStats,
    ProcessingMode,
    ValidationLevel,
    ValidationResult,
    get_data_pipeline,
    reset_data_pipeline,
)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _sample_data(n: int = 5) -> list:
    return [
        {"id": i, "name": f"item_{i}", "score": i * 10, "active": i % 2 == 0}
        for i in range(n)
    ]


# ═══════════════════════════════════════════════════════════
# 1) Memory Connector & Basic Extract
# ═══════════════════════════════════════════════════════════

class TestMemoryConnector:
    def test_extract_from_memory(self):
        """从内存数据源提取记录"""
        conn = MemoryConnector(_sample_data(3), name="test")
        records = conn.extract_all()
        assert len(records) == 3
        assert records[0].data["id"] == 0
        assert records[1].data["name"] == "item_1"
        assert records[0].source == "test"
        assert records[0].source_type == DataSourceType.MEMORY.value

    def test_extract_empty_memory(self):
        """空内存数据源"""
        conn = MemoryConnector([])
        assert conn.extract_all() == []


# ═══════════════════════════════════════════════════════════
# 2) FileConnector (CSV, JSON, JSONL, TXT)
# ═══════════════════════════════════════════════════════════

class TestFileConnector:
    def test_csv_extract(self):
        """CSV文件提取"""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
        tmp.write("id,name,score\n1,alpha,10\n2,beta,20\n")
        tmp.close()
        try:
            conn = FileConnector(tmp.name)
            records = conn.extract_all()
            assert len(records) == 2
            assert records[0].data == {"id": "1", "name": "alpha", "score": "10"}
            assert records[1].data == {"id": "2", "name": "beta", "score": "20"}
        finally:
            os.unlink(tmp.name)

    def test_json_extract_list(self):
        """JSON数组提取"""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump([{"a": 1}, {"b": 2}], tmp)
        tmp.close()
        try:
            conn = FileConnector(tmp.name)
            records = conn.extract_all()
            assert len(records) == 2
            assert records[0].data == {"a": 1}
            assert records[1].data == {"b": 2}
        finally:
            os.unlink(tmp.name)

    def test_json_extract_single_object(self):
        """JSON单对象提取"""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"key": "value"}, tmp)
        tmp.close()
        try:
            conn = FileConnector(tmp.name)
            records = conn.extract_all()
            assert len(records) == 1
            assert records[0].data == {"key": "value"}
        finally:
            os.unlink(tmp.name)

    def test_jsonl_extract(self):
        """JSONL行格式提取"""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.write('{"x": 1}\n{"y": 2}\n')
        tmp.close()
        try:
            conn = FileConnector(tmp.name)
            records = conn.extract_all()
            assert len(records) == 2
        finally:
            os.unlink(tmp.name)

    def test_txt_extract(self):
        """TXT文本行提取"""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        tmp.write("hello world\nfoo bar\n")
        tmp.close()
        try:
            conn = FileConnector(tmp.name)
            records = conn.extract_all()
            assert len(records) == 2
            assert records[0].data["line"] == "hello world"
        finally:
            os.unlink(tmp.name)

    def test_unsupported_extension(self):
        """不支持的扩展名应抛出ValueError"""
        with pytest.raises(ValueError, match="Unsupported"):
            FileConnector("/tmp/data.bin")


# ═══════════════════════════════════════════════════════════
# 3) DataQualityValidator Built-in Rules
# ═══════════════════════════════════════════════════════════

class TestDataQualityValidator:
    def test_not_null_rule(self):
        """非空校验"""
        v = DataQualityValidator()
        v.add_rule(v.not_null("name"))
        r1 = DataRecord(data={"name": "present"})
        v.validate(r1)
        assert r1.is_valid is True

        r2 = DataRecord(data={"other": 1})
        v.validate(r2)
        assert r2.is_valid is False
        assert any("missing" in e.lower() for e in r2.errors)

    def test_field_type_rule(self):
        """类型校验"""
        v = DataQualityValidator()
        v.add_rule(v.field_type("age", int))
        r1 = DataRecord(data={"age": 25})
        v.validate(r1)
        assert r1.is_valid is True

        r2 = DataRecord(data={"age": "twenty-five"})
        v.validate(r2)
        assert r2.is_valid is False

    def test_field_in_rule(self):
        """枚举值校验"""
        v = DataQualityValidator()
        v.add_rule(v.field_in("status", {"active", "inactive"}))
        r1 = DataRecord(data={"status": "active"})
        v.validate(r1)
        assert r1.is_valid is True

        r2 = DataRecord(data={"status": "deleted"})
        v.validate(r2)
        assert r2.is_valid is False

    def test_field_range_rule(self):
        """范围校验"""
        v = DataQualityValidator()
        v.add_rule(v.field_range("score", min_val=0, max_val=100))
        r1 = DataRecord(data={"score": 50})
        v.validate(r1)
        assert r1.is_valid is True

        r2 = DataRecord(data={"score": 150})
        v.validate(r2)
        assert r2.is_valid is False

    def test_field_pattern_rule(self):
        """正则校验"""
        v = DataQualityValidator()
        v.add_rule(v.field_pattern("email", r"^[^@]+@[^@]+$"))
        r1 = DataRecord(data={"email": "user@example.com"})
        v.validate(r1)
        assert r1.is_valid is True

        r2 = DataRecord(data={"email": "not-an-email"})
        v.validate(r2)
        assert r2.is_valid is False

    def test_custom_rule(self):
        """自定义校验规则"""
        v = DataQualityValidator()
        v.add_rule(v.custom_rule("score_even", lambda rec: (
            rec.data.get("score", 0) % 2 == 0,
            "Score must be even"
        )))
        r1 = DataRecord(data={"score": 4})
        v.validate(r1)
        assert r1.is_valid is True

        r2 = DataRecord(data={"score": 3})
        v.validate(r2)
        assert r2.is_valid is False

    def test_multiple_rules(self):
        """多规则组合校验"""
        v = DataQualityValidator()
        v.add_rule(v.not_null("id"))
        v.add_rule(v.field_type("score", int))
        v.add_rule(v.field_range("score", min_val=0, max_val=100))
        v.add_rule(v.field_in("status", {"active", "inactive"}))

        good = DataRecord(data={"id": 1, "score": 80, "status": "active"})
        v.validate(good)
        assert good.is_valid is True
        assert len(good.validation_results) == 4

        bad = DataRecord(data={"score": "N/A", "status": "bogus"})
        v.validate(bad)
        assert bad.is_valid is False
        # id missing → ERROR, score not int → ERROR, score can't calc range → ERROR, status not in set → ERROR
        assert len(bad.errors) >= 3


# ═══════════════════════════════════════════════════════════
# 4) Batch Pipeline (ETL full cycle)
# ═══════════════════════════════════════════════════════════

class TestBatchPipeline:
    def test_simple_batch_etl(self):
        """简单ETL批处理全流程"""
        p = DataPipeline()
        p.add_source(MemoryConnector(_sample_data(5)))

        # Transform: double the score
        def double_score(rec: DataRecord) -> DataRecord:
            rec.data["score"] = rec.data["score"] * 2
            return rec

        p.add_transform(double_score)

        # Validator: score must be present
        v = DataQualityValidator()
        v.add_rule(v.not_null("score"))
        p.add_validator(v)

        # Sink: collect results
        results = []
        p.add_sink(lambda r: results.append(r.data))

        stats = p.run_batch()
        assert stats.total_records == 5
        assert stats.valid_records == 5
        assert stats.success_rate == 1.0
        assert stats.total_extracted == 5
        assert stats.total_transformed == 5
        assert stats.total_loaded == 5
        assert len(results) == 5
        assert results[0]["score"] == 0  # 0*2
        assert results[4]["score"] == 80  # 40*2

    def test_batch_with_invalid_records(self):
        """批处理含无效记录"""
        p = DataPipeline()
        data = [
            {"id": 1, "score": 90},
            {"id": 2, "score": -10},   # invalid: negative score
            {"id": 3},                   # missing score
        ]
        p.add_source(MemoryConnector(data))

        v = DataQualityValidator()
        v.add_rule(v.field_range("score", min_val=0, max_val=100))
        p.add_validator(v)

        stats = p.run_batch()
        assert stats.total_records == 3
        assert stats.valid_records == 1
        assert stats.invalid_records == 2
        assert stats.success_rate == pytest.approx(1 / 3)
        assert p.state == PipelineState.COMPLETED

    def test_transform_error_handling(self):
        """Transform阶段异常处理"""
        p = DataPipeline()
        p.add_source(MemoryConnector([{"x": 1}]))

        def broken_transform(rec: DataRecord) -> DataRecord:
            raise RuntimeError("transform boom")

        p.add_transform(broken_transform)
        stats = p.run_batch()
        # Transform error is caught and recorded; record still flows through
        assert stats.total_records == 1
        assert len(p.get_records()) == 1
        assert any("transform" in e.lower() or "boom" in e.lower()
                   for e in p.get_records()[0].errors)


# ═══════════════════════════════════════════════════════════
# 5) Streaming Pipeline
# ═══════════════════════════════════════════════════════════

class TestStreamPipeline:
    def test_stream_yields_records(self):
        """流式管道逐条产出记录"""
        p = DataPipeline()
        p.add_source(MemoryConnector(_sample_data(3)))

        results = []
        for record in p.run_stream():
            results.append(record)
            assert isinstance(record, DataRecord)
            assert record.extracted_at is not None

        assert len(results) == 3
        assert p.state == PipelineState.COMPLETED

    def test_stream_with_validation(self):
        """流式管道含数据校验"""
        p = DataPipeline()
        p.add_source(MemoryConnector([
            {"name": "valid", "score": 75},
            {"name": "invalid", "score": 200},
        ]))

        v = DataQualityValidator()
        v.add_rule(v.field_range("score", 0, 100))
        p.add_validator(v)

        valid_count = 0
        invalid_count = 0
        for record in p.run_stream():
            if record.is_valid:
                valid_count += 1
            else:
                invalid_count += 1

        assert valid_count == 1
        assert invalid_count == 1
        s = p.stats
        assert s.valid_records == 1
        assert s.invalid_records == 1

    def test_stream_with_sink(self):
        """流式管道带Sink回调"""
        p = DataPipeline()
        p.add_source(MemoryConnector([{"a": 1}, {"a": 2}]))
        sink_data = []

        def sink(rec: DataRecord):
            sink_data.append(rec.data["a"])

        p.add_sink(sink)

        count = 0
        for _ in p.run_stream():
            count += 1

        assert count == 2
        assert sink_data == [1, 2]


# ═══════════════════════════════════════════════════════════
# 6) Multiple Sources
# ═══════════════════════════════════════════════════════════

class TestMultiSource:
    def test_multiple_sources_batch(self):
        """多数据源批处理"""
        p = DataPipeline()
        p.add_source(MemoryConnector([{"from": "mem1"}], name="mem1"))
        p.add_source(MemoryConnector([{"from": "mem2"}], name="mem2"))

        stats = p.run_batch()
        assert stats.total_records == 2
        records = p.get_records()
        assert records[0].source == "mem1"
        assert records[1].source == "mem2"


# ═══════════════════════════════════════════════════════════
# 7) Pipeline Stats & Introspection
# ═══════════════════════════════════════════════════════════

class TestPipelineStats:
    def test_stats_structure(self):
        """Stats结构完整"""
        p = DataPipeline()
        p.add_source(MemoryConnector(_sample_data(2)))
        p.run_batch()

        s = p.stats
        assert s.total_records == 2
        assert s.elapsed_seconds > 0
        assert "extract_ms" in s.stages
        assert "load_ms" in s.stages

        d = s.to_dict()
        assert d["valid_records"] == 2
        assert d["success_rate"] == 1.0

    def test_stats_after_reset(self):
        """Reset后Stats清零"""
        p = DataPipeline()
        p.add_source(MemoryConnector([{"x": 1}]))
        p.run_batch()
        assert p.stats.total_records == 1

        p.reset()
        assert p.stats.total_records == 0
        assert p.stats.total_extracted == 0
        assert p.state == PipelineState.IDLE

    def test_record_count(self):
        """record_count()方法"""
        p = DataPipeline()
        p.add_source(MemoryConnector(_sample_data(4)))
        p.run_batch()
        assert p.record_count() == 4

    def test_source_transform_count(self):
        """source_count / transform_count"""
        p = DataPipeline()
        p.add_source(MemoryConnector([]))
        p.add_source(MemoryConnector([]))
        p.add_transform(lambda r: r)
        p.add_transform(lambda r: r)
        p.add_transform(lambda r: r)
        assert p.source_count == 2
        assert p.transform_count == 3


# ═══════════════════════════════════════════════════════════
# 8) Context Manager
# ═══════════════════════════════════════════════════════════

class TestContextManager:
    def test_context_manager(self):
        """上下文管理器用法"""
        results = []
        with DataPipeline("ctx-test") as p:
            p.add_source(MemoryConnector([{"v": 1}, {"v": 2}]))
            p.add_sink(lambda r: results.append(r.data))
            p.run_batch()
            # Pipeline exits context cleanly
        assert len(results) == 2
        assert p.state == PipelineState.COMPLETED  # unchanged by __exit__ unless stop called


# ═══════════════════════════════════════════════════════════
# 9) Singleton Access
# ═══════════════════════════════════════════════════════════

class TestSingleton:
    def test_get_and_reset(self):
        """单例获取与重置"""
        reset_data_pipeline()
        p1 = get_data_pipeline("test-singleton")
        assert p1 is not None
        p2 = get_data_pipeline()
        assert p1 is p2  # same instance

        reset_data_pipeline()
        p3 = get_data_pipeline("fresh")
        assert p3 is not p1  # new instance

    def test_singleton_with_source(self):
        """单例管道可正常使用"""
        reset_data_pipeline()
        p = get_data_pipeline("singleton-test")
        p.add_source(MemoryConnector([{"k": "v"}]))
        stats = p.run_batch()
        assert stats.total_records == 1
        p.reset()


# ═══════════════════════════════════════════════════════════
# 10) Edge Cases & Robustness
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_pipeline_with_no_sources(self):
        """无数据源管道运行不崩溃"""
        p = DataPipeline()
        stats = p.run_batch()
        assert stats.total_records == 0
        assert stats.success_rate == 1.0

    def test_pipeline_with_no_transforms(self):
        """无Transform管道正常运行"""
        p = DataPipeline()
        p.add_source(MemoryConnector([{"x": 1}]))
        stats = p.run_batch()
        assert stats.total_records == 1

    def test_clear_pipeline(self):
        """Clear清除所有配置"""
        p = DataPipeline()
        p.add_source(MemoryConnector([{"a": 1}]))
        p.add_transform(lambda r: r)
        p.clear()
        assert p.source_count == 0
        assert p.transform_count == 0
        assert p.record_count() == 0

    def test_stop_streaming_pipeline(self):
        """停止流式管道"""
        p = DataPipeline()
        p.add_source(MemoryConnector(_sample_data(10)))

        count = 0
        for record in p.run_stream():
            count += 1
            if count >= 3:
                p.stop()
                # GeneratorExit may happen on next yield
                # or we break here

        assert count >= 3
        # After stop, state should reflect it
        # Note: breaking out of the generator triggers GeneratorExit in the generator

    def test_error_in_pipeline_run(self):
        """管道运行异常不崩溃"""
        p = DataPipeline()
        p.add_source(MemoryConnector([{"a": 1}]))

        def raise_sink(rec):
            if rec.data.get("a") == 1:
                raise RuntimeError("sink error")

        p.add_sink(raise_sink)
        stats = p.run_batch()
        # Pipeline completes; the sink error is recorded
        assert stats.total_records == 1
        assert p.state == PipelineState.COMPLETED

    def test_validation_result_fields(self):
        """ValidationResult字段完整性"""
        r = ValidationResult(
            check_name="test_check",
            level=ValidationLevel.WARNING,
            passed=False,
            message="value too high",
            field="score",
            actual_value=200,
            expected_value="<=100",
        )
        assert r.check_name == "test_check"
        assert r.level == ValidationLevel.WARNING
        assert r.passed is False
        assert r.field == "score"
        assert r.actual_value == 200

    def test_tsv_extract(self):
        """TSV文件提取 (tab-separated)"""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, newline="")
        tmp.write("id\tname\n1\talpha\n2\tbeta\n")
        tmp.close()
        try:
            conn = FileConnector(tmp.name)
            records = conn.extract_all()
            assert len(records) == 2
            assert records[0].data == {"id": "1", "name": "alpha"}
        finally:
            os.unlink(tmp.name)
