"""Unit tests for app.logging_setup module."""

import logging
from unittest.mock import MagicMock, patch

from app.logging_setup import apply_request_id_filter, configure_logging
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
