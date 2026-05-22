from __future__ import annotations

from types import SimpleNamespace

from stress_tester.core.user_manager import KamiwazaUserManager
from stress_tester.models import RunCreateRequest


def _run_config(**kwargs) -> RunCreateRequest:
    base = {
        "concurrent_users": 1,
        "role_distribution": {"viewer": 1},
        "browser_distribution": {"chromium": 1},
        "os_emulation": ["win-chrome"],
        "scenarios": ["login"],
        "duration_seconds": 30,
        "ramp_up_seconds": 0,
        "vision_enabled": False,
    }
    base.update(kwargs)
    return RunCreateRequest(**base)


def test_runtime_config_uses_env_when_no_overrides():
    settings = SimpleNamespace(
        kamiwaza_url="https://env.example",
        kamiwaza_admin_user="env-admin",
        kamiwaza_admin_password="env-pass",
        kamiwaza_admin_token=None,
    )
    manager = KamiwazaUserManager(settings)

    cfg = manager.resolve_runtime_config(_run_config())

    assert cfg.base_url == "https://env.example"
    assert cfg.admin_user == "env-admin"
    assert cfg.source == "env"


def test_runtime_config_uses_override_and_fallback_mix():
    settings = SimpleNamespace(
        kamiwaza_url="https://env.example",
        kamiwaza_admin_user="env-admin",
        kamiwaza_admin_password="env-pass",
        kamiwaza_admin_token=None,
    )
    manager = KamiwazaUserManager(settings)

    cfg = manager.resolve_runtime_config(
        _run_config(
            kamiwaza_url="https://override.example",
            kamiwaza_admin_user="override-admin",
        )
    )

    assert cfg.base_url == "https://override.example"
    assert cfg.admin_user == "override-admin"
    assert cfg.admin_password == "env-pass"
    assert cfg.source == "mixed"


def test_response_json_handles_non_json_response():
    settings = SimpleNamespace(
        kamiwaza_url="https://env.example",
        kamiwaza_admin_user="env-admin",
        kamiwaza_admin_password="env-pass",
        kamiwaza_admin_token=None,
    )
    manager = KamiwazaUserManager(settings)

    class FakeResponse:
        content = b"<html>ok</html>"

        @staticmethod
        def json():
            raise ValueError("not json")

    assert manager._response_json(FakeResponse()) == {}


def test_runtime_config_uses_kubectl_secret_when_password_is_missing(monkeypatch):
    settings = SimpleNamespace(
        kamiwaza_url="https://env.example",
        kamiwaza_admin_user=None,
        kamiwaza_admin_password=None,
        kamiwaza_admin_token=None,
    )
    manager = KamiwazaUserManager(settings)
    monkeypatch.setattr(manager, "_kubectl_admin_password", lambda: "secret-pass")

    cfg = manager.resolve_runtime_config(_run_config())

    assert cfg.base_url == "https://env.example"
    assert cfg.admin_user == "admin"
    assert cfg.admin_password == "secret-pass"
    assert cfg.source == "kubectl-secret"


def test_runtime_config_defaults_admin_credentials_when_secret_is_unavailable(monkeypatch):
    settings = SimpleNamespace(
        kamiwaza_url="https://env.example",
        kamiwaza_admin_user=None,
        kamiwaza_admin_password=None,
        kamiwaza_admin_token=None,
    )
    manager = KamiwazaUserManager(settings)
    monkeypatch.setattr(manager, "_kubectl_admin_password", lambda: None)

    cfg = manager.resolve_runtime_config(_run_config())

    assert cfg.base_url == "https://env.example"
    assert cfg.admin_user == "admin"
    assert cfg.admin_password == "kamiwaza"
    assert cfg.source == "default"


def test_api_base_url_for_user_admin_strips_runtime_app_path():
    url = "https://test.kamiwaza.dev/runtime/apps/kaizen-mncpbftx-716a7143/"
    normalized = KamiwazaUserManager._api_base_url_for_user_admin(url)
    assert normalized == "https://test.kamiwaza.dev"


def test_api_base_url_for_user_admin_preserves_prefix_before_runtime_apps():
    url = "https://example.com/platform/runtime/apps/kaizen-123"
    normalized = KamiwazaUserManager._api_base_url_for_user_admin(url)
    assert normalized == "https://example.com/platform"
