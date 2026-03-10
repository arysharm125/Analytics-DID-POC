"""Unit tests for app/database.py.

These tests verify the MongoConnector initialization and validation logic
without requiring a real MongoDB connection.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.database import MongoConnector, MongoConnectorInitError


class TestMongoConnectorInitialization:
    """Test MongoConnector initialization rules."""

    def test_direct_instantiation_raises_error(self):
        """Direct instantiation of MongoConnector should raise MongoConnectorInitError."""
        with pytest.raises(
            MongoConnectorInitError,
            match=r"Direct instantiation of MongoConnector is not supported.*"
        ):
            MongoConnector()

    def test_error_message_mentions_factory_methods(self):
        """Error message should mention the available factory methods."""
        with pytest.raises(MongoConnectorInitError) as exc_info:
            MongoConnector()

        error_message = str(exc_info.value)
        assert "from_uri()" in error_message
        assert "from_client()" in error_message
        assert "from_vault_service()" in error_message

    def test_get_collection_raises_if_db_not_initialized(self):
        """Calling get_collection on uninitialized connector should raise RuntimeError."""
        # Create an instance using __new__ to bypass __init__, simulating uninitialized state
        instance = MongoConnector.__new__(MongoConnector)
        instance.db = None  # type: ignore # Explicitly set db to None

        with pytest.raises(RuntimeError, match="MongoConnector not initialized"):
            instance.get_collection("test_collection")


class TestConnectionPoolStats:
    """Test connection pool statistics functionality."""

    def test_get_pool_stats_returns_none_when_client_is_none(self):
        """get_pool_stats should return None when client is not initialized."""
        instance = MongoConnector.__new__(MongoConnector)
        instance.client = None

        result = instance.get_pool_stats()
        assert result is None

    def test_get_pool_stats_with_mongomock_returns_none(self):
        """mongomock doesn't have pool stats, should return None gracefully."""
        import mongomock

        client = mongomock.MongoClient()
        connector = MongoConnector.from_client(client, "test_db")

        # Should return None without crashing (mongomock doesn't expose pool internals)
        result = connector.get_pool_stats()
        assert result is None


class TestFromVaultService:
    """Test MongoConnector.from_vault_service() factory method."""

    def test_from_vault_service_success(self, vault_service):
        """Should read config from vault and create connector."""
        # Store valid config in vault
        vault_service._client.write_secret("secret", "mongo", {
            "connection_string": "mongodb://localhost:27017",
            "database_name": "test_db"
        })

        # Mock from_uri to avoid actual connection
        mock_connector = MagicMock()
        with patch.object(MongoConnector, 'from_uri', return_value=mock_connector) as mock_from_uri:
            result = MongoConnector.from_vault_service(vault_service)

            # Verify from_uri was called with correct parameters
            mock_from_uri.assert_called_once_with("mongodb://localhost:27017", "test_db")
            assert result is mock_connector

    def test_from_vault_service_secret_not_found(self, vault_service, vault_mode):
        """Should raise RuntimeError when vault secret not found."""
        if vault_mode == "container":
            pytest.skip("Test requires mock vault (container vault may have secrets from other tests)")

        # Vault doesn't have the 'mongo' secret
        with pytest.raises(RuntimeError, match="Failed to read MongoDB config from vault"):
            MongoConnector.from_vault_service(vault_service)

    def test_from_vault_service_missing_connection_string(self, vault_service):
        """Should raise RuntimeError when connection_string key is missing."""
        # Store config missing connection_string
        vault_service._client.write_secret("secret", "mongo", {
            "database_name": "test_db"
        })

        with pytest.raises(RuntimeError, match="missing key: connection_string"):
            MongoConnector.from_vault_service(vault_service)

    def test_from_vault_service_missing_database_name(self, vault_service):
        """Should raise RuntimeError when database_name key is missing."""
        # Store config missing database_name
        vault_service._client.write_secret("secret", "mongo", {
            "connection_string": "mongodb://localhost:27017"
        })

        with pytest.raises(RuntimeError, match="missing key: database_name"):
            MongoConnector.from_vault_service(vault_service)

    def test_from_vault_service_empty_connection_string(self, vault_service):
        """Should raise RuntimeError when connection_string is empty."""
        vault_service._client.write_secret("secret", "mongo", {
            "connection_string": "",
            "database_name": "test_db"
        })

        with pytest.raises(RuntimeError, match="missing key: connection_string"):
            MongoConnector.from_vault_service(vault_service)

    def test_from_vault_service_empty_database_name(self, vault_service):
        """Should raise RuntimeError when database_name is empty."""
        vault_service._client.write_secret("secret", "mongo", {
            "connection_string": "mongodb://localhost:27017",
            "database_name": ""
        })

        with pytest.raises(RuntimeError, match="missing key: database_name"):
            MongoConnector.from_vault_service(vault_service)


class TestConnectRetryLogic:
    """Test MongoConnector._connect() retry logic."""

    def test_connect_succeeds_first_try(self):
        """Should connect successfully on first attempt."""
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}  # Successful ping
        mock_client.__getitem__ = MagicMock()  # For db access

        with patch('app.database.MongoClient', return_value=mock_client), \
             patch('app.database.time.sleep') as mock_sleep:

            instance = MongoConnector.__new__(MongoConnector)
            instance.client = None
            instance._connect("mongodb://localhost:27017", "test_db")

            # Verify connection succeeded
            assert instance.client is mock_client
            assert instance.db is not None

            # Should not have retried (no sleep calls)
            mock_sleep.assert_not_called()

    def test_connect_retries_on_failure(self):
        """Should retry on connection failure and eventually succeed."""
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock()

        # Fail twice, succeed on third attempt
        mock_client.admin.command.side_effect = [
            Exception("First failure"),
            Exception("Second failure"),
            {"ok": 1}  # Success on third try
        ]

        with patch('app.database.MongoClient', return_value=mock_client), \
             patch('app.database.time.sleep') as mock_sleep:

            instance = MongoConnector.__new__(MongoConnector)
            instance.client = None
            instance._connect("mongodb://localhost:27017", "test_db")

            # Verify retries happened
            assert mock_sleep.call_count == 2  # Slept after first and second failures
            mock_sleep.assert_called_with(3)  # Each sleep is 3 seconds

            # Connection should eventually succeed
            assert instance.client is mock_client

    def test_connect_fails_after_three_attempts(self):
        """Should raise RuntimeError after 3 failed connection attempts."""
        mock_client = MagicMock()
        mock_client.admin.command.side_effect = Exception("Always fails")

        with patch('app.database.MongoClient', return_value=mock_client), \
             patch('app.database.time.sleep') as mock_sleep:

            instance = MongoConnector.__new__(MongoConnector)
            instance.client = None

            with pytest.raises(RuntimeError, match="Could not connect to MongoDB after 3 attempts"):
                instance._connect("mongodb://localhost:27017", "test_db")

            # Verify all 3 attempts were made (3 sleeps, one after each failure)
            assert mock_sleep.call_count == 3
            mock_sleep.assert_called_with(3)  # Each sleep is 3 seconds

    def test_connect_uses_tls_for_atlas(self):
        """Should enable TLS for MongoDB Atlas connection strings."""
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client.__getitem__ = MagicMock()

        with patch('app.database.MongoClient', return_value=mock_client) as mock_mongo_client, \
             patch('app.database.time.sleep'):

            instance = MongoConnector.__new__(MongoConnector)
            instance.client = None

            # Test mongodb+srv:// connection
            instance._connect("mongodb+srv://cluster.mongodb.net", "test_db")

            # Verify TLS was enabled
            call_kwargs = mock_mongo_client.call_args[1]
            assert call_kwargs['tls'] is True

    def test_connect_uses_tls_for_mongodb_net(self):
        """Should enable TLS for mongodb.net connections."""
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client.__getitem__ = MagicMock()

        with patch('app.database.MongoClient', return_value=mock_client) as mock_mongo_client, \
             patch('app.database.time.sleep'):

            instance = MongoConnector.__new__(MongoConnector)
            instance.client = None

            # Test connection string with mongodb.net
            instance._connect("mongodb://cluster.mongodb.net:27017", "test_db")

            # Verify TLS was enabled
            call_kwargs = mock_mongo_client.call_args[1]
            assert call_kwargs['tls'] is True

    def test_connect_no_tls_for_localhost(self):
        """Should not use TLS for localhost connections."""
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client.__getitem__ = MagicMock()

        with patch('app.database.MongoClient', return_value=mock_client) as mock_mongo_client, \
             patch('app.database.time.sleep'):

            instance = MongoConnector.__new__(MongoConnector)
            instance.client = None

            # Test localhost connection
            instance._connect("mongodb://localhost:27017", "test_db")

            # Verify TLS was not enabled
            call_kwargs = mock_mongo_client.call_args[1]
            assert call_kwargs['tls'] is False
