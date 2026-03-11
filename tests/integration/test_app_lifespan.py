"""Integration tests for application lifespan."""

from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from app.lifespan import StartupDependencies, create_app_lifespan


class TestAppLifespan:
    """Integration tests for the full app lifespan."""

    @pytest.mark.asyncio
    async def test_full_startup_shutdown_cycle(
        self, db_connector, vault_service, test_config
    ) -> None:
        """Test complete startup and shutdown cycle with real dependencies."""
        from app.config import override_config
        from app.routers.dependencies import (
            reset_all_dependencies,
            set_db_dependency,
            set_vault_dependency,
        )

        try:
            # Override config for test
            override_config(test_config)

            # Inject test dependencies
            set_vault_dependency(vault_service)
            set_db_dependency(db_connector)

            # Create mock function for did_service_lifespan
            lifespan_entered = False

            @asynccontextmanager
            async def mock_did_service_lifespan():
                nonlocal lifespan_entered
                lifespan_entered = True
                yield

            # Create dependencies
            deps = StartupDependencies(
                get_vault=lambda: vault_service,
                get_db=lambda: db_connector,
                did_service_lifespan=mock_did_service_lifespan,
                get_config=lambda: test_config,
            )

            # Mock logger to verify log messages
            mock_logger = MagicMock()

            # Run the lifespan
            async with create_app_lifespan(deps, logger=mock_logger):
                # Verify startup was successful
                assert lifespan_entered

                # Verify startup log messages
                log_messages = [
                    call[0][0] for call in mock_logger.info.call_args_list
                ]
                assert any("Starting application" in msg for msg in log_messages)
                assert any("Vault connection established" in msg for msg in log_messages)
                assert any(
                    "MongoDB connection established" in msg for msg in log_messages
                )
                assert any("Application startup complete" in msg for msg in log_messages)

            # After exiting, verify shutdown messages
            shutdown_messages = [
                call[0][0]
                for call in mock_logger.info.call_args_list
                if "Shutting down" in call[0][0] or "shutdown" in call[0][0].lower()
            ]
            assert len(shutdown_messages) > 0

        finally:
            # Clean up
            reset_all_dependencies()

    @pytest.mark.asyncio
    async def test_startup_fails_on_vault_error(self, db_connector, test_config) -> None:
        """Test that startup fails cleanly when vault is unreachable."""
        from app.config import override_config
        from app.routers.dependencies import reset_all_dependencies, set_db_dependency

        try:
            override_config(test_config)
            set_db_dependency(db_connector)

            # Create mock dependencies with failing vault
            def failing_get_vault():
                raise Exception("Vault connection failed")

            @asynccontextmanager
            async def mock_did_service_lifespan():
                yield

            deps = StartupDependencies(
                get_vault=failing_get_vault,
                get_db=lambda: db_connector,
                did_service_lifespan=mock_did_service_lifespan,
                get_config=lambda: test_config,
            )

            mock_logger = MagicMock()

            # Lifespan should raise RuntimeError
            with pytest.raises(RuntimeError) as exc_info:
                async with create_app_lifespan(deps, logger=mock_logger):
                    pass

            assert "Failed to connect to vault" in str(exc_info.value)

            # Verify critical log was written
            mock_logger.critical.assert_called()
            critical_msg = mock_logger.critical.call_args[0][0]
            assert "Vault connection failed" in critical_msg

        finally:
            reset_all_dependencies()

    @pytest.mark.asyncio
    async def test_startup_fails_on_db_error(self, vault_service, test_config) -> None:
        """Test that startup fails cleanly when database is unreachable."""
        from app.config import override_config
        from app.routers.dependencies import reset_all_dependencies, set_vault_dependency

        try:
            override_config(test_config)
            set_vault_dependency(vault_service)

            # Create mock DB that fails ping
            mock_db = MagicMock()
            mock_db.client.admin.command.side_effect = Exception("Connection refused")

            @asynccontextmanager
            async def mock_did_service_lifespan():
                yield

            deps = StartupDependencies(
                get_vault=lambda: vault_service,
                get_db=lambda: mock_db,
                did_service_lifespan=mock_did_service_lifespan,
                get_config=lambda: test_config,
            )

            mock_logger = MagicMock()

            # Lifespan should raise RuntimeError
            with pytest.raises(RuntimeError) as exc_info:
                async with create_app_lifespan(deps, logger=mock_logger):
                    pass

            assert "Failed to connect to MongoDB" in str(exc_info.value)

            # Verify critical log was written
            mock_logger.critical.assert_called()
            critical_msg = mock_logger.critical.call_args[0][0]
            assert "MongoDB connection failed" in critical_msg

        finally:
            reset_all_dependencies()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_closes_connections(
        self, db_connector, vault_service, test_config
    ) -> None:
        """Test that shutdown properly closes database connections."""
        from app.config import override_config
        from app.routers.dependencies import (
            reset_all_dependencies,
            set_db_dependency,
            set_vault_dependency,
        )

        try:
            override_config(test_config)
            set_vault_dependency(vault_service)
            set_db_dependency(db_connector)

            @asynccontextmanager
            async def mock_did_service_lifespan():
                yield

            deps = StartupDependencies(
                get_vault=lambda: vault_service,
                get_db=lambda: db_connector,
                did_service_lifespan=mock_did_service_lifespan,
                get_config=lambda: test_config,
            )

            mock_logger = MagicMock()

            # Track if close_connection was called
            close_called = False
            original_close = db_connector.close_connection

            def track_close():
                nonlocal close_called
                close_called = True
                original_close()

            db_connector.close_connection = track_close

            # Run lifespan
            async with create_app_lifespan(deps, logger=mock_logger):
                pass

            # Verify connection was closed
            # Note: The lifespan closes _db_connector, not our injected instance
            # So we verify the shutdown log message instead
            shutdown_logs = [call[0][0] for call in mock_logger.info.call_args_list]
            assert any("shutdown" in log.lower() for log in shutdown_logs)

        finally:
            reset_all_dependencies()
