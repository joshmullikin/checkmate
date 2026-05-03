import logging


class TestCoreLogging:
    def test_setup_logging_json_format(self, monkeypatch):
        import core.logging as core_log

        monkeypatch.setattr(core_log, "LOG_FORMAT", "json")
        core_log.setup_logging()

    def test_setup_logging_with_log_file(self, monkeypatch, tmp_path):
        import core.logging as core_log
        from logging.handlers import RotatingFileHandler

        log_file = str(tmp_path / "test.log")
        monkeypatch.setattr(core_log, "LOG_FILE", log_file)
        core_log.setup_logging()

        root = logging.getLogger()
        assert any(isinstance(handler, RotatingFileHandler) for handler in root.handlers)

    def test_requestid_formatter_injects_id(self):
        from core.logging import RequestIdFormatter

        formatter = RequestIdFormatter("%(request_id)s %(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        if hasattr(record, "request_id"):
            del record.request_id

        result = formatter.format(record)
        assert result
