"""Unit tests for app.lifespan module."""

import asyncio
from contextlib import suppress
from unittest.mock import MagicMock

import pytest

from app.database import ConnectionPoolStats
from app.lifespan import (
    log_pool_stats_once,
    pool_monitor_loop,
    validate_db_connectivity,
    validate_vault_connectivity,
)


class TestLogPoolStatsOnce:
    """Test suite for log_pool_stats_once function."""

    def test_log_pool_stats_once_healthy(self) -> None:
        """Should log info message when pool is healthy."""
        # Create mock database with healthy pool stats
        mock_db = MagicMock()
        mock_stats = ConnectionPoolStats(
            max_pool_size=100,
            min_pool_size=5,
            current_size=10,
            available_count=8,
            in_use_count=2,
            wait_queue_size=0,
            pool_health="healthy",
        )
        mock_db.get_pool_stats.return_value = mock_stats

        # Create mock logger
        mock_logger = MagicMock()

        log_pool_stats_once(mock_db, mock_logger)

        # Verify info was logged with correct message
        mock_logger.info.assert_called_once()
        log_message = mock_logger.info.call_args[0][0]
        assert "2/100 in use" in log_message
        assert "8 available" in log_message
        assert "wait_queue=0" in log_message
        assert "health=healthy" in log_message

        # No warning or error should be logged
        mock_logger.warning.assert_not_called()
        mock_logger.error.assert_not_called()

    def test_log_pool_stats_once_warning(self) -> None:
        """Should log warning when pool health is warning."""
        # Create mock database with warning pool stats (70%+ utilization)
        mock_db = MagicMock()
        mock_stats = ConnectionPoolStats(
            max_pool_size=100,
            min_pool_size=5,
            current_size=75,
            available_count=25,
            in_use_count=75,
            wait_queue_size=0,
            pool_health="warning",
        )
        mock_db.get_pool_stats.return_value = mock_stats

        mock_logger = MagicMock()

        log_pool_stats_once(mock_db, mock_logger)

        # Verify both info and warning were logged
        mock_logger.info.assert_called_once()
        mock_logger.warning.assert_called_once()

        warning_message = mock_logger.warning.call_args[0][0]
        assert "WARNING" in warning_message
        assert "75/100" in warning_message
        assert "75.0%" in warning_message

        # No error should be logged
        mock_logger.error.assert_not_called()

    def test_log_pool_stats_once_critical(self) -> None:
        """Should log error when pool health is critical."""
        # Create mock database with critical pool stats (90%+ utilization)
        mock_db = MagicMock()
        mock_stats = ConnectionPoolStats(
            max_pool_size=100,
            min_pool_size=5,
            current_size=95,
            available_count=5,
            in_use_count=95,
            wait_queue_size=3,
            pool_health="critical",
        )
        mock_db.get_pool_stats.return_value = mock_stats

        mock_logger = MagicMock()

        log_pool_stats_once(mock_db, mock_logger)

        # Verify both info and error were logged
        mock_logger.info.assert_called_once()
        mock_logger.error.assert_called_once()

        error_message = mock_logger.error.call_args[0][0]
        assert "CRITICAL" in error_message
        assert "95/100" in error_message
        assert "95.0%" in error_message
        assert "wait_queue=3" in error_message

    def test_log_pool_stats_once_handles_none_stats(self) -> None:
        """Should handle gracefully when get_pool_stats returns None."""
        mock_db = MagicMock()
        mock_db.get_pool_stats.return_value = None

        mock_logger = MagicMock()

        # Should not raise exception
        log_pool_stats_once(mock_db, mock_logger)

        # Nothing should be logged
        mock_logger.info.assert_not_called()
        mock_logger.warning.assert_not_called()
        mock_logger.error.assert_not_called()

    def test_log_pool_stats_once_handles_exception(self) -> None:
        """Should log debug message on exception without crashing."""
        mock_db = MagicMock()
        mock_db.get_pool_stats.side_effect = Exception("Database error")

        mock_logger = MagicMock()

        # Should not raise exception
        log_pool_stats_once(mock_db, mock_logger)

        # Only debug message should be logged
        mock_logger.debug.assert_called_once()
        debug_message = mock_logger.debug.call_args[0][0]
        assert "Pool stats monitoring error" in debug_message


class TestPoolMonitorLoop:
    """Test suite for pool_monitor_loop function."""

    @pytest.mark.asyncio
    async def test_pool_monitor_loop_calls_once_per_interval(self) -> None:
        """Should call log_pool_stats_once after each interval."""
        mock_db = MagicMock()
        mock_db.get_pool_stats.return_value = None
        mock_get_db = MagicMock(return_value=mock_db)

        mock_logger = MagicMock()

        # Start the monitor loop with short interval
        task = asyncio.create_task(pool_monitor_loop(mock_get_db, 0.1, mock_logger))

        # Wait for at least one iteration
        await asyncio.sleep(0.15)

        # Cancel the task
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

        # Verify get_db was called at least once
        assert mock_get_db.call_count >= 1

    @pytest.mark.asyncio
    async def test_pool_monitor_loop_continues_on_error(self) -> None:
        """Should continue running even if log_pool_stats_once raises exception."""
        mock_db = MagicMock()
        # First call raises exception, second call succeeds
        mock_db.get_pool_stats.side_effect = [
            Exception("First error"),
            None,
        ]
        mock_get_db = MagicMock(return_value=mock_db)

        mock_logger = MagicMock()

        # Start the monitor loop
        task = asyncio.create_task(pool_monitor_loop(mock_get_db, 0.05, mock_logger))

        # Wait for multiple iterations
        await asyncio.sleep(0.15)

        # Cancel the task
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

        # Verify loop continued after exception (multiple calls to get_pool_stats)
        assert mock_db.get_pool_stats.call_count >= 2


class TestValidateVaultConnectivity:
    """Test suite for validate_vault_connectivity function."""

    def test_validate_vault_connectivity_success(self) -> None:
        """Should succeed when vault is accessible."""
        mock_vault = MagicMock()
        mock_get_vault = MagicMock(return_value=mock_vault)

        # Should not raise exception
        validate_vault_connectivity(mock_get_vault)

        mock_get_vault.assert_called_once()

    def test_validate_vault_connectivity_failure_raises(self) -> None:
        """Should raise RuntimeError when vault connection fails."""
        mock_get_vault = MagicMock(side_effect=Exception("Vault connection failed"))

        with pytest.raises(RuntimeError) as exc_info:
            validate_vault_connectivity(mock_get_vault)

        assert "Failed to connect to vault" in str(exc_info.value)
        assert "aborting startup" in str(exc_info.value)

    def test_validate_vault_connectivity_preserves_cause(self) -> None:
        """Should preserve the original exception as __cause__."""
        original_error = Exception("Original vault error")
        mock_get_vault = MagicMock(side_effect=original_error)

        with pytest.raises(RuntimeError) as exc_info:
            validate_vault_connectivity(mock_get_vault)

        assert exc_info.value.__cause__ is original_error


class TestValidateDbConnectivity:
    """Test suite for validate_db_connectivity function."""

    def test_validate_db_connectivity_success(self) -> None:
        """Should succeed when database is accessible."""
        mock_db = MagicMock()
        mock_db.client.admin.command.return_value = {"ok": 1}
        mock_get_db = MagicMock(return_value=mock_db)

        # Should not raise exception
        validate_db_connectivity(mock_get_db)

        mock_get_db.assert_called_once()
        mock_db.client.admin.command.assert_called_once_with("ping")

    def test_validate_db_connectivity_failure_raises(self) -> None:
        """Should raise RuntimeError when database connection fails."""
        mock_db = MagicMock()
        mock_db.client.admin.command.side_effect = Exception("Connection refused")
        mock_get_db = MagicMock(return_value=mock_db)

        with pytest.raises(RuntimeError) as exc_info:
            validate_db_connectivity(mock_get_db)

        assert "Failed to connect to MongoDB" in str(exc_info.value)
        assert "aborting startup" in str(exc_info.value)

    def test_validate_db_connectivity_none_client_raises(self) -> None:
        """Should raise RuntimeError when client is None."""
        mock_db = MagicMock()
        mock_db.client = None
        mock_get_db = MagicMock(return_value=mock_db)

        with pytest.raises(RuntimeError) as exc_info:
            validate_db_connectivity(mock_get_db)

        assert "Failed to connect to MongoDB" in str(exc_info.value)

    def test_validate_db_connectivity_preserves_cause(self) -> None:
        """Should preserve the original exception as __cause__."""
        original_error = Exception("Original DB error")
        mock_db = MagicMock()
        mock_db.client.admin.command.side_effect = original_error
        mock_get_db = MagicMock(return_value=mock_db)

        with pytest.raises(RuntimeError) as exc_info:
            validate_db_connectivity(mock_get_db)

        assert exc_info.value.__cause__ is original_error
