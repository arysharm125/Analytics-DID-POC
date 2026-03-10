"""Unit tests for app/routers/health.py endpoints.

Tests the /health route including status determination logic,
vault authentication checks, MongoDB connectivity, and pool statistics.
"""

from unittest.mock import Mock, patch

from pymongo.errors import ServerSelectionTimeoutError

from app.database import ConnectionPoolStats
from app.routers.health import health


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_all_ok_basic(self, db_connector, vault_service):
        """Vault authenticated + DB connected → status: ok.

        Basic happy path test using real fixtures.
        """
        response = health(db=db_connector, vault=vault_service)

        assert response.status == "ok"
        assert response.vault_authenticated is True
        assert response.db_connected is True
        # pool_stats may or may not be None depending on client implementation
        assert response.version is not None
        assert response.full_version is not None

    def test_health_all_ok_with_healthy_pool(self, db_connector, vault_service):
        """Vault authenticated + DB connected + healthy pool → status: ok."""
        # Mock pool stats to return healthy status
        pool_stats = ConnectionPoolStats(
            max_pool_size=100,
            min_pool_size=5,
            current_size=10,
            available_count=8,
            in_use_count=2,
            wait_queue_size=0,
            pool_health="healthy",
        )

        with patch.object(db_connector, 'get_pool_stats', return_value=pool_stats):
            response = health(db=db_connector, vault=vault_service)

        assert response.status == "ok"
        assert response.vault_authenticated is True
        assert response.db_connected is True
        assert response.pool_stats is not None
        assert response.pool_stats.pool_health == "healthy"

    def test_health_degraded_critical_pool(self, db_connector, vault_service):
        """Vault authenticated + DB connected + critical pool → status: degraded."""
        pool_stats = ConnectionPoolStats(
            max_pool_size=100,
            min_pool_size=5,
            current_size=100,
            available_count=2,
            in_use_count=98,
            wait_queue_size=10,
            pool_health="critical",
        )

        with patch.object(db_connector, 'get_pool_stats', return_value=pool_stats):
            response = health(db=db_connector, vault=vault_service)

        assert response.status == "degraded"
        assert response.vault_authenticated is True
        assert response.db_connected is True
        assert response.pool_stats is not None
        assert response.pool_stats.pool_health == "critical"

    def test_health_degraded_vault_not_authenticated(self, db_connector, vault_service):
        """Vault NOT authenticated + DB connected → status: degraded."""
        with patch.object(vault_service, 'is_authenticated', return_value=False):
            response = health(db=db_connector, vault=vault_service)

        assert response.status == "degraded"
        assert response.vault_authenticated is False
        assert response.db_connected is True

    def test_health_degraded_vault_auth_raises_exception(self, db_connector, vault_service):
        """Vault is_authenticated raises exception → treated as vault_ok=False."""
        with patch.object(vault_service, 'is_authenticated', side_effect=Exception("Vault error")):
            response = health(db=db_connector, vault=vault_service)

        assert response.status == "degraded"
        assert response.vault_authenticated is False
        assert response.db_connected is True

    def test_health_unhealthy_db_client_none(self, vault_service):
        """DB client is None → status: unhealthy."""
        # Create mock db with client=None
        mock_db = Mock()
        mock_db.client = None

        response = health(db=mock_db, vault=vault_service)

        assert response.status == "unhealthy"
        assert response.vault_authenticated is True
        assert response.db_connected is False
        assert response.pool_stats is None

    def test_health_unhealthy_db_ping_fails(self, vault_service):
        """DB ping command raises exception → status: unhealthy."""
        # Create a mock db where ping fails
        mock_db = Mock()
        mock_admin = Mock()
        mock_admin.command.side_effect = ServerSelectionTimeoutError("Cannot reach MongoDB")
        mock_db.client = Mock()
        mock_db.client.admin = mock_admin

        response = health(db=mock_db, vault=vault_service)

        assert response.status == "unhealthy"
        assert response.vault_authenticated is True
        assert response.db_connected is False

    def test_health_unhealthy_both_down(self, vault_service):
        """Both vault and DB unavailable → status: unhealthy."""
        mock_db = Mock()
        mock_db.client = None

        with patch.object(vault_service, 'is_authenticated', return_value=False):
            response = health(db=mock_db, vault=vault_service)

        assert response.status == "unhealthy"
        assert response.vault_authenticated is False
        assert response.db_connected is False

    def test_health_version_fields_populated(self, db_connector, vault_service):
        """Version and full_version fields are populated from app.version."""
        from app.version import VERSION, full_version

        response = health(db=db_connector, vault=vault_service)

        assert response.version == VERSION
        assert response.full_version == full_version()
        # Verify full_version contains the base version
        assert VERSION in response.full_version

    def test_health_pool_stats_warning_status(self, db_connector, vault_service):
        """Pool with warning status still results in ok overall status.

        Only critical pool health should degrade to 'degraded'.
        """
        pool_stats = ConnectionPoolStats(
            max_pool_size=100,
            min_pool_size=5,
            current_size=80,
            available_count=20,
            in_use_count=60,
            wait_queue_size=2,
            pool_health="warning",
        )

        with patch.object(db_connector, 'get_pool_stats', return_value=pool_stats):
            response = health(db=db_connector, vault=vault_service)

        # Warning pool health should not degrade the overall status
        assert response.status == "ok"
        assert response.pool_stats is not None
        assert response.pool_stats.pool_health == "warning"

    def test_health_get_pool_stats_raises_exception(self, db_connector, vault_service):
        """get_pool_stats raising exception causes DB check to fail.

        Note: In practice, get_pool_stats() catches all exceptions internally
        and returns None. This test verifies behavior if it were to raise.
        """
        with patch.object(db_connector, 'get_pool_stats', side_effect=Exception("Pool error")):
            response = health(db=db_connector, vault=vault_service)

        # Exception in get_pool_stats causes entire DB check to fail
        assert response.status == "unhealthy"
        assert response.vault_authenticated is True
        assert response.db_connected is False
        assert response.pool_stats is None
