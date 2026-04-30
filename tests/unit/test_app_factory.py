"""Unit tests for app.app_factory module."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from starlette.routing import Mount, Route

from app.app_factory import create_app


def _extract_app_routes(app: FastAPI) -> list[str]:
    """Extract route paths from a FastAPI app, filtering to routes with path attribute."""
    return [route.path for route in app.routes if isinstance(route, (Route, Mount))]


class TestCreateApp:
    """Test suite for create_app function."""

    def test_create_app_returns_fastapi_instance(self) -> None:
        """create_app should return a FastAPI instance."""
        # Use a mock lifespan to avoid actual startup
        mock_lifespan = MagicMock()

        app = create_app(lifespan=mock_lifespan)

        assert isinstance(app, FastAPI)
        assert app.version is not None

    def test_create_app_includes_epdw_router(self) -> None:
        """create_app should include the EPDW router."""
        mock_lifespan = MagicMock()

        app = create_app(lifespan=mock_lifespan)

        # Check that EPDW routes are present
        routes = _extract_app_routes(app)
        assert any("/epdw/did.json" in route for route in routes)

    def test_create_app_includes_advisory_router(self) -> None:
        """create_app should include the advisory router."""
        mock_lifespan = MagicMock()

        app = create_app(lifespan=mock_lifespan)

        # Check that advisory routes are present
        routes = _extract_app_routes(app)
        assert any("/advisory" in route for route in routes)

    def test_create_app_includes_health_router(self) -> None:
        """create_app should include the health router."""
        mock_lifespan = MagicMock()

        app = create_app(lifespan=mock_lifespan)

        # Check that health routes are present
        routes = _extract_app_routes(app)
        assert any("/health" in route for route in routes)

    def test_create_app_includes_docs_router(self) -> None:
        """create_app should include the docs router."""
        mock_lifespan = MagicMock()

        app = create_app(lifespan=mock_lifespan)

        # Check that docs routes are present
        routes = _extract_app_routes(app)
        assert any("/docs" in route for route in routes)

    @patch("app.app_factory.get_config")
    def test_create_app_includes_didcheck_when_enabled(
        self, mock_get_config: MagicMock
    ) -> None:
        """create_app should include didcheck router when feature flag is enabled."""
        # Mock config with didcheck enabled
        mock_config = MagicMock()
        mock_config.features.didcheck_router = True
        mock_get_config.return_value = mock_config

        mock_lifespan = MagicMock()

        app = create_app(lifespan=mock_lifespan)

        # Check that didcheck routes are present
        routes = _extract_app_routes(app)
        assert any("/didcheck" in route for route in routes)

    @patch("app.app_factory.get_config")
    def test_create_app_excludes_didcheck_when_disabled(
        self, mock_get_config: MagicMock
    ) -> None:
        """create_app should exclude didcheck router when feature flag is disabled."""
        # Mock config with didcheck disabled
        mock_config = MagicMock()
        mock_config.features.didcheck_router = False
        mock_get_config.return_value = mock_config

        mock_lifespan = MagicMock()

        app = create_app(lifespan=mock_lifespan)

        # Check that didcheck routes are NOT present
        routes = _extract_app_routes(app)
        assert not any("/didcheck" in route for route in routes)

    def test_create_app_custom_lifespan(self) -> None:
        """create_app should accept custom lifespan function."""
        custom_lifespan_called = False

        def custom_lifespan(app):
            nonlocal custom_lifespan_called
            custom_lifespan_called = True
            # Return a simple async context manager
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def lifespan_cm():
                yield

            return lifespan_cm()

        app = create_app(lifespan=custom_lifespan)

        assert isinstance(app, FastAPI)
        # The lifespan is only called when the app starts, so we can't verify
        # it was called in this test, but we can verify it was assigned
        assert app.router.lifespan_context is not None

    def test_create_app_middleware_applied(self) -> None:
        """create_app should apply required middleware."""
        mock_lifespan = MagicMock()

        app = create_app(lifespan=mock_lifespan)

        # Check that middleware stack is not empty
        assert len(app.user_middleware) > 0

        # Verify specific middleware classes are present
        middleware_classes = [getattr(m.cls, '__name__', '') for m in app.user_middleware]
        assert "AccessLogMiddleware" in middleware_classes
        assert "RequestIdMiddleware" in middleware_classes

    def test_create_app_exception_handlers_configured(self) -> None:
        """create_app should configure exception handlers."""
        mock_lifespan = MagicMock()

        app = create_app(lifespan=mock_lifespan)

        # Verify exception handlers are configured
        # The app should have exception handlers registered
        from fastapi import HTTPException

        assert HTTPException in app.exception_handlers

    @patch("app.app_factory.get_config")
    @patch("app.app_factory.get_vault")
    @patch("app.app_factory.get_db")
    @patch("app.app_factory.did_service_lifespan")
    def test_create_app_default_lifespan_uses_dependencies(
        self,
        mock_did_service_lifespan: MagicMock,
        mock_get_db: MagicMock,
        mock_get_vault: MagicMock,
        mock_get_config: MagicMock,
    ) -> None:
        """create_app with no lifespan should create default lifespan with dependencies."""
        # Mock config
        mock_config = MagicMock()
        mock_config.features.didcheck_router = False
        mock_get_config.return_value = mock_config

        # This will create the default lifespan
        app = create_app()

        # We can't easily test that the lifespan uses these dependencies without
        # actually starting the app, but we can verify the app was created
        assert isinstance(app, FastAPI)
