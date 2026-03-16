"""Unit tests for app.logging_setup module."""

import logging
import socket
from unittest.mock import MagicMock, patch

import pytest

from app.logging_setup import SuppressOnlyPymongoNameResolution, apply_request_id_filter, configure_logging
from app.request_id import RequestIdFilter


class TestConfigureLogging:
    """Test suite for configure_logging function."""

    @patch("app.logging_setup.logging.config.fileConfig")
    @patch("app.logging_setup.apply_request_id_filter")
    def test_configure_logging_calls_fileconfig(
        self, mock_apply_filter: MagicMock, mock_fileconfig: MagicMock
    ) -> None:
        """configure_logging should call fileConfig with correct path."""
        configure_logging()

        mock_fileconfig.assert_called_once_with(
            "deployment/logging.ini", disable_existing_loggers=False
        )

    @patch("app.logging_setup.logging.config.fileConfig")
    @patch("app.logging_setup.apply_request_id_filter")
    def test_configure_logging_applies_filter(
        self, mock_apply_filter: MagicMock, mock_fileconfig: MagicMock
    ) -> None:
        """configure_logging should apply request ID filter."""
        configure_logging()

        mock_apply_filter.assert_called_once()

    @patch("app.logging_setup.logging.config.fileConfig")
    @patch("app.logging_setup.apply_request_id_filter")
    @patch("app.logging_setup.logging.getLogger")
    def test_configure_logging_sets_third_party_log_levels(
        self,
        mock_get_logger: MagicMock,
        mock_apply_filter: MagicMock,
        mock_fileconfig: MagicMock,
    ) -> None:
        """configure_logging should set WARNING level for pymongo and urllib3."""
        # Create mock loggers
        mock_pymongo_logger = MagicMock()
        mock_urllib3_logger = MagicMock()

        def get_logger_side_effect(name: str) -> MagicMock:
            if name == "pymongo":
                return mock_pymongo_logger
            elif name == "urllib3":
                return mock_urllib3_logger
            return MagicMock()

        mock_get_logger.side_effect = get_logger_side_effect

        configure_logging()

        # Verify setLevel was called with WARNING for both loggers
        mock_pymongo_logger.setLevel.assert_called_once_with(logging.WARNING)
        mock_urllib3_logger.setLevel.assert_called_once_with(logging.WARNING)

    @patch("app.logging_setup.logging.config.fileConfig")
    @patch("app.logging_setup.apply_request_id_filter")
    def test_configure_logging_custom_path(
        self, mock_apply_filter: MagicMock, mock_fileconfig: MagicMock
    ) -> None:
        """configure_logging should accept custom config path."""
        custom_path = "custom/logging.ini"
        configure_logging(custom_path)

        mock_fileconfig.assert_called_once_with(
            custom_path, disable_existing_loggers=False
        )


class TestApplyRequestIdFilter:
    """Test suite for apply_request_id_filter function."""

    @patch("app.logging_setup.logging.root.handlers", [])
    @patch("app.logging_setup.RequestIdFilter")
    def test_apply_request_id_filter_no_handlers(
        self, mock_filter_class: MagicMock
    ) -> None:
        """apply_request_id_filter should handle empty handler list."""
        mock_filter_instance = MagicMock()
        mock_filter_class.return_value = mock_filter_instance

        apply_request_id_filter()

        # Filter should be created but not added to any handlers
        mock_filter_class.assert_called_once()
        mock_filter_instance.addFilter.assert_not_called()

    def test_apply_request_id_filter_adds_to_all_handlers(self) -> None:
        """apply_request_id_filter should add filter to all root handlers."""
        # Create mock handlers
        mock_handler1 = MagicMock()
        mock_handler2 = MagicMock()
        mock_handler3 = MagicMock()

        with patch(
            "app.logging_setup.logging.root.handlers",
            [mock_handler1, mock_handler2, mock_handler3],
        ):
            apply_request_id_filter()

            # Verify filter was added to all handlers
            mock_handler1.addFilter.assert_called_once()
            mock_handler2.addFilter.assert_called_once()
            mock_handler3.addFilter.assert_called_once()

            # Verify the filter is a RequestIdFilter instance
            filter1 = mock_handler1.addFilter.call_args[0][0]
            filter2 = mock_handler2.addFilter.call_args[0][0]
            filter3 = mock_handler3.addFilter.call_args[0][0]

            assert isinstance(filter1, RequestIdFilter)
            assert isinstance(filter2, RequestIdFilter)
            assert isinstance(filter3, RequestIdFilter)
            # All handlers should get the same filter instance
            assert filter1 is filter2 is filter3


@pytest.fixture
def logger_with_dns_filter(caplog):
    """
    Create a logger with the DNS error filter that works with caplog.
    caplog automatically captures log records, so we just need to configure the logger.
    """
    logger = logging.getLogger("pymongo.client")
    original_level = logger.level
    original_propagate = logger.propagate
    original_handlers = list(logger.handlers)

    logger.setLevel(logging.ERROR)
    logger.propagate = True  # Allow caplog to capture

    # Clear existing handlers for isolation
    for h in list(logger.handlers):
        logger.removeHandler(h)

    # Add the DNS filter to caplog's handler
    dns_filter = SuppressOnlyPymongoNameResolution()
    for handler in logging.root.handlers:
        handler.addFilter(dns_filter)

    yield logger

    # Cleanup: restore original state and remove filter
    logger.setLevel(original_level)
    logger.propagate = original_propagate
    for h in list(logger.handlers):
        logger.removeHandler(h)
    for h in original_handlers:
        logger.addHandler(h)
    for handler in logging.root.handlers:
        handler.removeFilter(dns_filter)

class TestPymongoClientDNSErrorSuppression:
    """
    Tests related to suppression of DNS error from pymongo.
    """

    def _emit_logger_error_with_exc(self, logger: logging.Logger, msg: str, exc: BaseException):
        """Helper to raise exc and log into pymongo"""
        try:
            raise exc
        except Exception:
            logger.error(msg, exc_info=True)


    def test_suppresses_only_gaierror_name_or_service(self, logger_with_dns_filter, caplog):
        """
        socket.gaierror(-2, 'Name or service not known') should be suppressed.
        """
        caplog.set_level(logging.ERROR)
        self._emit_logger_error_with_exc(
            logger_with_dns_filter,
            "MongoClient background task encountered an error",
            socket.gaierror(-2, "Name or service not known"),
        )
        # The filter should suppress this error, so no records should be captured
        assert len(caplog.records) == 0
        assert "MongoClient background task encountered an error" not in caplog.text


    @pytest.mark.parametrize(
        "exc",
        [
            socket.gaierror(0, "Temporary failure in name resolution"),  # different errno/message
            TimeoutError("timed out"),
            TimeoutError("operation timed out"),
            ConnectionError("connection reset"),
            RuntimeError("some other failure"),
        ],
    )
    def test_other_errors_are_not_suppressed(self, logger_with_dns_filter, caplog, exc):
        """
        Non-matching exceptions must pass through and be visible in logs (with stack trace).
        """
        caplog.set_level(logging.ERROR)
        self._emit_logger_error_with_exc(
            logger_with_dns_filter,
            "MongoClient background task encountered an error",
            exc,
        )
        # The error should NOT be suppressed, so it should appear in caplog
        assert len(caplog.records) == 1
        assert "MongoClient background task encountered an error" in caplog.text
        # Verify exception info is present
        record = caplog.records[0]
        assert record.exc_info is not None
        assert isinstance(record.exc_info[1], type(exc))


    def test_non_pymongo_loggers_unaffected(self, caplog):
        """
        Ensure the filter does not touch non-pymongo loggers.
        """
        logger = logging.getLogger("myapp.component")
        original_level = logger.level
        original_propagate = logger.propagate
        original_handlers = list(logger.handlers)

        logger.setLevel(logging.ERROR)
        logger.propagate = True  # Allow caplog to capture
        for h in list(logger.handlers):
            logger.removeHandler(h)

        # Add DNS filter to root handlers (to test that non-pymongo loggers bypass it)
        dns_filter = SuppressOnlyPymongoNameResolution()
        for handler in logging.root.handlers:
            handler.addFilter(dns_filter)

        try:
            caplog.set_level(logging.ERROR)
            self._emit_logger_error_with_exc(
                logger, "Something failed", RuntimeError("boom")
            )
            # Non-pymongo logger should NOT be affected by the filter
            assert len(caplog.records) == 1
            assert "Something failed" in caplog.text
            # Verify exception info is present
            assert caplog.records[0].exc_info is not None
        finally:
            # Cleanup
            logger.setLevel(original_level)
            logger.propagate = original_propagate
            for h in list(logger.handlers):
                logger.removeHandler(h)
            for h in original_handlers:
                logger.addHandler(h)
            for handler in logging.root.handlers:
                handler.removeFilter(dns_filter)


    def test_filter_applies_via_root_handlers_only_to_pymongo(self, caplog):
        """
        If the filter is attached at the root handlers, it should still only
        suppress pymongo.client DNS -2, and allow other records (including other
        loggers) to pass.
        """
        # Add the DNS filter to caplog's handler (which is on the root logger)
        dns_filter = SuppressOnlyPymongoNameResolution()
        for handler in logging.root.handlers:
            handler.addFilter(dns_filter)

        try:
            caplog.set_level(logging.ERROR)

            # 1) PyMongo.client gaierror -2 should be suppressed
            pym_client_logger = logging.getLogger("pymongo.client")
            try:
                raise socket.gaierror(-2, "Name or service not known")
            except Exception:
                pym_client_logger.error("Background thread error", exc_info=True)

            # 2) PyMongo.client other error should appear
            try:
                raise RuntimeError("other failure")
            except Exception:
                pym_client_logger.error("Background thread error", exc_info=True)

            # 3) Non-pymongo error should appear
            app_logger = logging.getLogger("myapp")
            try:
                raise RuntimeError("app failure")
            except Exception:
                app_logger.error("App error", exc_info=True)

            # Validate captured records
            # The suppressed one should not be in caplog, others should
            messages = [r.message for r in caplog.records]

            # Exactly two messages: the 'other failure' and 'App error'
            assert len(caplog.records) == 2, f"Expected 2 records, got {len(caplog.records)}: {messages}"
            assert any("Background thread error" in m for m in messages)
            assert any("App error" in m for m in messages)

            # There should be no record that includes 'gaierror' -2 stack
            assert not any(
                ("Name or service not known" in (r.exc_text or "") or
                (r.exc_info and isinstance(r.exc_info[1], socket.gaierror) and r.exc_info[1].args and r.exc_info[1].args[0] == -2))
                for r in caplog.records
            )
        finally:
            # Remove the filter from all handlers
            for handler in logging.root.handlers:
                handler.removeFilter(dns_filter)
