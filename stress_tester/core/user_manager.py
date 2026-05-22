from __future__ import annotations

import secrets
import string
import subprocess
from base64 import b64decode
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import httpx

from stress_tester.models import RunCreateRequest, TestUser

if TYPE_CHECKING:
    from stress_tester.config import Settings


class UserProvisionError(RuntimeError):
    """Raised when user provisioning fails."""


@dataclass(slots=True)
class RuntimeKamiwazaConfig:
    base_url: str
    admin_user: str | None
    admin_password: str | None
    admin_token: str | None
    source: str

    @property
    def has_login_credentials(self) -> bool:
        return bool(self.admin_user and self.admin_password)


class KamiwazaUserManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @staticmethod
    def _response_json(response: httpx.Response) -> dict[str, Any]:
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError:
            return {}
        if isinstance(payload, dict):
            return payload
        return {}

    @staticmethod
    def _api_base_url_for_user_admin(base_url: str) -> str:
        """Normalize app runtime URLs to the platform API base for auth/user endpoints.

        Example:
        https://host/runtime/apps/kaizen-abc -> https://host
        https://host/prefix/runtime/apps/kaizen-abc -> https://host/prefix
        """
        raw = (base_url or "").strip().rstrip("/")
        if not raw:
            return raw

        split = urlsplit(raw)
        path = split.path.rstrip("/")
        marker = "/runtime/apps"

        if path == marker:
            api_path = ""
        elif path.startswith(f"{marker}/"):
            api_path = ""
        elif f"{marker}/" in path:
            api_path = path.split(f"{marker}/", 1)[0].rstrip("/")
        else:
            api_path = path

        return urlunsplit((split.scheme, split.netloc, api_path, "", "")).rstrip("/")

    @staticmethod
    def _kubectl_admin_password() -> str | None:
        """Read the default admin password from the local Kamiwaza cluster.

        This is the preferred fallback for local/operator runs. Explicit run
        credentials, env credentials, and admin tokens still take precedence.
        """
        try:
            encoded = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "secret",
                    "kamiwaza-user-admin",
                    "-n",
                    "kamiwaza",
                    "-o",
                    "jsonpath={.data.password}",
                ],
                capture_output=True,
                check=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
        if not encoded:
            return None
        try:
            decoded = b64decode(encoded).decode("utf-8").strip()
        except Exception:
            return None
        return decoded or None

    def resolve_runtime_config(self, run_config: RunCreateRequest | None = None) -> RuntimeKamiwazaConfig:
        has_overrides = False
        used_env_fallback = False
        used_default_fallback = False
        used_kubectl_fallback = False

        def pick(field: str, env_value: str | None) -> str | None:
            nonlocal has_overrides, used_env_fallback
            if run_config is None:
                return self._clean(env_value)
            raw = getattr(run_config, field)
            normalized = self._clean(raw)
            if normalized is not None:
                has_overrides = True
                return normalized
            env_normalized = self._clean(env_value)
            if env_normalized is not None:
                used_env_fallback = True
            return env_normalized

        base_url = (pick("kamiwaza_url", self.settings.kamiwaza_url) or "").rstrip("/")
        admin_user = pick("kamiwaza_admin_user", self.settings.kamiwaza_admin_user)
        admin_password = pick("kamiwaza_admin_password", self.settings.kamiwaza_admin_password)
        admin_token = pick("kamiwaza_admin_token", self.settings.kamiwaza_admin_token)

        if not admin_token and not admin_password:
            admin_password = self._kubectl_admin_password()
            if admin_password:
                used_kubectl_fallback = True
                if not admin_user:
                    admin_user = "admin"

        # Final friendly local default when no cluster secret is available.
        if not admin_token and not admin_user and not admin_password:
            admin_user = "admin"
            admin_password = "kamiwaza"
            used_default_fallback = True

        if has_overrides and (used_env_fallback or used_default_fallback or used_kubectl_fallback):
            source = "mixed"
        elif has_overrides:
            source = "override"
        elif used_kubectl_fallback:
            source = "kubectl-secret"
        elif used_default_fallback:
            source = "default"
        else:
            source = "env"

        return RuntimeKamiwazaConfig(
            base_url=base_url,
            admin_user=admin_user,
            admin_password=admin_password,
            admin_token=admin_token,
            source=source,
        )

    def is_configured(self, runtime_config: RuntimeKamiwazaConfig | None = None) -> bool:
        cfg = runtime_config or self.resolve_runtime_config()
        return bool(cfg.base_url)

    def _ensure_configured(self, runtime_config: RuntimeKamiwazaConfig) -> None:
        if self.is_configured(runtime_config):
            return
        raise UserProvisionError(
            "KAMIWAZA_URL is required to run tests. "
            "Set it in env or provide kamiwaza_url in the run request/UI."
        )

    def _ensure_auth_material(self, runtime_config: RuntimeKamiwazaConfig) -> None:
        if runtime_config.admin_token or runtime_config.has_login_credentials:
            return
        raise UserProvisionError(
            "Admin auth is required to provision users. "
            "Set KAMIWAZA_ADMIN_TOKEN or KAMIWAZA_ADMIN_USER/KAMIWAZA_ADMIN_PASSWORD "
            "in env or provide run-specific overrides in the UI."
        )

    async def _try_admin_login(
        self,
        client: httpx.AsyncClient,
        runtime_config: RuntimeKamiwazaConfig,
    ) -> str | None:
        if runtime_config.admin_token:
            return runtime_config.admin_token
        if not runtime_config.has_login_credentials:
            return None

        login_attempts = [
            ("form", "/api/auth/token"),
            ("form", "/auth/token"),
            ("query", "/api/auth/local-login"),
            ("query", "/auth/local-login"),
            ("json", "/api/v1/auth/login"),
            ("json", "/api/v1/login"),
            ("json", "/auth/login"),
        ]
        json_payload_variants = [
            {
                "username": runtime_config.admin_user,
                "password": runtime_config.admin_password,
            },
            {
                "user": runtime_config.admin_user,
                "password": runtime_config.admin_password,
            },
        ]

        for mode, path in login_attempts:
            if mode == "json":
                payloads = json_payload_variants
            else:
                payloads = [{"username": runtime_config.admin_user, "password": runtime_config.admin_password}]

            for payload in payloads:
                try:
                    if mode == "form":
                        response = await client.post(path, data=payload, timeout=20)
                    elif mode == "query":
                        response = await client.post(path, params=payload, timeout=20)
                    else:
                        response = await client.post(path, json=payload, timeout=20)
                except httpx.HTTPError:
                    continue

                if response.status_code >= 400:
                    continue
                data = self._response_json(response)
                token = (
                    data.get("access_token")
                    or data.get("token")
                    or data.get("jwt")
                    or data.get("data", {}).get("token")
                    or data.get("data", {}).get("access_token")
                )
                if token:
                    runtime_config.admin_token = str(token)
                    return runtime_config.admin_token
        return None

    @staticmethod
    def _auth_headers(runtime_config: RuntimeKamiwazaConfig) -> dict[str, str]:
        if not runtime_config.admin_token:
            return {}
        return {"Authorization": f"Bearer {runtime_config.admin_token}"}

    @staticmethod
    def _build_role_list(role_distribution: dict[str, int]) -> list[str]:
        roles: list[str] = []
        for role, count in role_distribution.items():
            roles.extend([role] * max(0, count))
        return roles

    @staticmethod
    def _gen_password(length: int = 20) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    async def provision_test_users(
        self,
        run_id: str,
        count: int,
        role_distribution: dict[str, int],
        runtime_config: RuntimeKamiwazaConfig | None = None,
    ) -> list[TestUser]:
        cfg = runtime_config or self.resolve_runtime_config()
        self._ensure_configured(cfg)
        self._ensure_auth_material(cfg)

        roles = self._build_role_list(role_distribution)
        if len(roles) != count:
            raise UserProvisionError(
                f"role distribution mismatch: expected {count}, got {len(roles)}"
            )

        created: list[TestUser] = []
        api_base_url = self._api_base_url_for_user_admin(cfg.base_url)
        async with httpx.AsyncClient(base_url=api_base_url, verify=False) as client:
            await self._try_admin_login(client, cfg)
            create_paths = ["/api/v1/users/local", "/api/auth/users/local", "/auth/users/local"]
            for idx, role in enumerate(roles, start=1):
                username = f"stress-tester-{run_id[:8]}-{role}-{idx}"
                password = self._gen_password()
                payload = {
                    "username": username,
                    "password": password,
                    "role": role,
                }
                response: httpx.Response | None = None
                for create_path in create_paths:
                    response = await client.post(
                        create_path,
                        json=payload,
                        headers=self._auth_headers(cfg),
                        timeout=20,
                    )
                    if response.status_code == 404:
                        continue
                    if response.status_code < 400:
                        break
                if response is None or response.status_code >= 400:
                    status = response.status_code if response else "n/a"
                    detail = response.text if response else "no response"
                    hint = ""
                    if (
                        response is not None
                        and response.status_code == 401
                        and not cfg.admin_token
                    ):
                        hint = (
                            " (password login did not yield API auth for user provisioning; "
                            "try an admin token/PAT in the UI)"
                        )
                    raise UserProvisionError(
                        f"failed creating user {username}: {status} {detail}{hint}"
                    )
                data = self._response_json(response)
                user_id = (
                    data.get("id")
                    or data.get("user_id")
                    or data.get("data", {}).get("id")
                    or data.get("data", {}).get("user_id")
                    or username
                )
                created.append(
                    TestUser(
                        username=username,
                        password=password,
                        role=role,
                        user_id=str(user_id),
                    )
                )
        return created

    async def cleanup_test_users(
        self,
        users: list[TestUser],
        runtime_config: RuntimeKamiwazaConfig | None = None,
    ) -> None:
        cfg = runtime_config or self.resolve_runtime_config()
        if not users or not self.is_configured(cfg):
            return

        api_base_url = self._api_base_url_for_user_admin(cfg.base_url)
        async with httpx.AsyncClient(base_url=api_base_url, verify=False) as client:
            await self._try_admin_login(client, cfg)
            delete_paths = ["/api/v1/users/{user_id}", "/api/auth/users/{user_id}", "/auth/users/{user_id}"]
            for user in users:
                try:
                    for delete_tpl in delete_paths:
                        response = await client.delete(
                            delete_tpl.format(user_id=user.user_id),
                            headers=self._auth_headers(cfg),
                            timeout=20,
                        )
                        if response.status_code == 404:
                            continue
                        break
                except httpx.HTTPError:
                    continue

    async def cleanup_orphaned_users(self) -> int:
        cfg = self.resolve_runtime_config()
        if not self.is_configured(cfg):
            return 0
        if not (cfg.admin_token or cfg.has_login_credentials):
            return 0

        removed = 0
        api_base_url = self._api_base_url_for_user_admin(cfg.base_url)
        async with httpx.AsyncClient(base_url=api_base_url, verify=False) as client:
            await self._try_admin_login(client, cfg)
            list_paths = ["/api/v1/users", "/api/auth/users", "/auth/users"]
            response: httpx.Response | None = None
            try:
                for list_path in list_paths:
                    response = await client.get(
                        list_path,
                        headers=self._auth_headers(cfg),
                        timeout=20,
                    )
                    if response.status_code == 404:
                        continue
                    break
            except httpx.HTTPError:
                return 0

            if response is None or response.status_code >= 400:
                return 0

            data = self._response_json(response)
            records = data.get("items") or data.get("data") or data
            if not isinstance(records, list):
                return 0

            for row in records:
                if not isinstance(row, dict):
                    continue
                username = str(row.get("username") or row.get("name") or "")
                if not username.startswith("stress-tester-"):
                    continue
                user_id = str(row.get("id") or row.get("user_id") or "")
                if not user_id:
                    continue
                try:
                    delete_resp = await client.delete(
                        f"/api/v1/users/{user_id}",
                        headers=self._auth_headers(cfg),
                        timeout=20,
                    )
                    if delete_resp.status_code == 404:
                        delete_resp = await client.delete(
                            f"/api/auth/users/{user_id}",
                            headers=self._auth_headers(cfg),
                            timeout=20,
                        )
                except httpx.HTTPError:
                    continue
                if delete_resp.status_code < 400:
                    removed += 1
        return removed
