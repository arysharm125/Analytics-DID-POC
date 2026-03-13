"""Unit tests for the docs.py router."""

from fastapi.testclient import TestClient

from app.app_factory import create_app
from app.config import AppConfig, FeatureFlags, override_config
from app.main import app
from app.routers.dependencies import set_did_service_dependency


class TestDocsRouter:
    def test_returns_404_when_feature_flag_disabled(
        self, did_service_no_migrations, test_config
    ):
        """Endpoint should return 404 when FEATURE_DOCS_ROUTER is disabled."""
        # Create config with debug flag disabled
        config_disabled = AppConfig(
            vault=test_config.vault,
            tokens=test_config.tokens,
            mongo_pool=test_config.mongo_pool,
            features=FeatureFlags(
                didcheck_router=True,
                debug_vc_nquads=False,
                demodiv_router=False,
                docs_router=False, # Disabled
            ),
            expose_error_details=True,
        )

        override_config(config_disabled)
        set_did_service_dependency(did_service_no_migrations)
        client = TestClient(create_app())

        response_docs = client.get("/docs")
        assert response_docs.status_code == 404

        response_openapi = client.get("/openapi.json")
        assert response_openapi.status_code == 404

    def test_returns_200_when_feature_flag_enabled(
        self, did_service_no_migrations, test_config
    ):
        """Endpoint should return 200 when FEATURE_DOCS_ROUTER is enabled."""
        # Create config with debug flag disabled
        config_disabled = AppConfig(
            vault=test_config.vault,
            tokens=test_config.tokens,
            mongo_pool=test_config.mongo_pool,
            features=FeatureFlags(
                didcheck_router=True,
                debug_vc_nquads=False,
                demodiv_router=False,
                docs_router=True, # Enabled
            ),
            expose_error_details=True,
        )

        override_config(config_disabled)
        set_did_service_dependency(did_service_no_migrations)
        client = TestClient(create_app())

        response_docs = client.get("/docs")
        assert response_docs.status_code == 200

        response_openapi = client.get("/openapi.json")
        assert response_openapi.status_code == 200
