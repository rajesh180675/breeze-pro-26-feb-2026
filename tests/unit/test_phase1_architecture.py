from app.core.settings import Settings as CoreSettings
from app.domain.errors import AuthenticationError as DomainAuthenticationError
from app.infrastructure.breeze.auth import AuthManager as InfraAuthManager
from app.infrastructure.breeze.rest_client import BreezeClient as InfraBreezeClient
from app.infrastructure.breeze.websocket_client import BreezeWebsocketClient as InfraBreezeWebsocketClient
from app.lib.auth import AuthManager
from app.lib.breeze_client import BreezeClient
from app.lib.breeze_ws import BreezeWebsocketClient
from app.lib.config import Settings
from app.lib.errors import AuthenticationError


def test_config_shim_preserves_settings_type():
    assert Settings is CoreSettings


def test_error_shim_preserves_exception_type():
    assert AuthenticationError is DomainAuthenticationError


def test_auth_shim_preserves_auth_manager_type():
    assert AuthManager is InfraAuthManager


def test_rest_client_shim_preserves_client_type():
    assert BreezeClient is InfraBreezeClient


def test_websocket_shim_preserves_client_type():
    assert BreezeWebsocketClient is InfraBreezeWebsocketClient
