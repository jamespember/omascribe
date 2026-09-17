"""GitHub Copilot authentication via OAuth Device Flow and token management."""

import json
import os
import time
import urllib.request
import urllib.error
from typing import Optional, Tuple

from .logger import get_logger

logger = get_logger(__name__)

# VS Code Copilot client_id (public, not a secret).  Override via
# GITHUB_COPILOT_CLIENT_ID env var or github_copilot_client_id in config.

COPILOT_CLIENT_ID = os.environ.get("GITHUB_COPILOT_CLIENT_ID", "Iv1.b507a08c87ecfe98")

# GitHub OAuth / Copilot API endpoints
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_API_BASE = "https://api.githubcopilot.com"

# OAuth scope required for Copilot access
COPILOT_SCOPE = "read:user"

# Device flow polling timeout (5 minutes)
DEVICE_FLOW_TIMEOUT = 300


class DeviceFlowError(Exception):
    """Raised when the device flow fails."""

    pass


class CopilotTokenError(Exception):
    """Raised when Copilot token exchange fails."""

    pass


def start_device_flow(client_id: Optional[str] = None) -> dict:
    """Start the GitHub OAuth Device Flow.

    Returns a dict with keys:
        - device_code: Code used to poll for the access token
        - user_code: Code the user enters at the verification URL
        - verification_uri: URL the user visits (https://github.com/login/device)
        - expires_in: Seconds until the device code expires
        - interval: Polling interval in seconds

    Raises:
        DeviceFlowError: If the request fails or client_id is not configured.
    """
    cid = client_id or COPILOT_CLIENT_ID

    data = json.dumps(
        {
            "client_id": cid,
            "scope": COPILOT_SCOPE,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        DEVICE_CODE_URL,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error(f"Device flow request failed: {e.code} {body}")
        raise DeviceFlowError(f"GitHub returned HTTP {e.code}: {body}")
    except Exception as e:
        logger.error(f"Device flow request failed: {e}")
        raise DeviceFlowError(f"Failed to start device flow: {e}")

    if "error" in result:
        raise DeviceFlowError(
            f"GitHub error: {result.get('error_description', result['error'])}"
        )

    logger.info(f"Device flow started: user_code={result.get('user_code')}")
    return result


def poll_for_token(
    device_code: str,
    interval: int = 5,
    timeout: int = DEVICE_FLOW_TIMEOUT,
    client_id: Optional[str] = None,
) -> str:
    """Poll GitHub until the user authorizes the device, or timeout.

    Args:
        device_code: The device_code from start_device_flow().
        interval: Polling interval in seconds.
        timeout: Maximum time to wait in seconds.
        client_id: Override the default client_id.

    Returns:
        The OAuth access_token string.

    Raises:
        DeviceFlowError: If authorization fails, is denied, or times out.
    """
    cid = client_id or COPILOT_CLIENT_ID
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        time.sleep(interval)

        data = json.dumps(
            {
                "client_id": cid,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            ACCESS_TOKEN_URL,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"Token poll request failed: {e}")
            continue

        error = result.get("error")

        if error == "authorization_pending":
            # User hasn't entered the code yet, keep polling
            continue
        elif error == "slow_down":
            # GitHub asked us to slow down, increase interval
            interval += 5
            continue
        elif error == "expired_token":
            raise DeviceFlowError("Device code expired. Please try again.")
        elif error == "access_denied":
            raise DeviceFlowError("Authorization was denied by the user.")
        elif error:
            desc = result.get("error_description", error)
            raise DeviceFlowError(f"Authorization failed: {desc}")

        # Success - we have an access token
        access_token = result.get("access_token")
        if access_token:
            logger.info("Device flow completed successfully")
            return access_token

        raise DeviceFlowError(f"Unexpected response from GitHub: {result}")

    raise DeviceFlowError("Authorization timed out. Please try again.")


class CopilotTokenManager:
    """Manages Copilot session tokens (short-lived) from a GitHub OAuth token (long-lived).

    The GitHub OAuth access token (from device flow) is exchanged for a
    short-lived Copilot session token (~30 min). This class caches the session
    token and transparently refreshes it when expired.
    """

    def __init__(self, github_token: str):
        """
        Args:
            github_token: Long-lived GitHub OAuth access token (from device flow).
        """
        if not github_token:
            raise CopilotTokenError("GitHub token is required")
        self.github_token = github_token
        self._copilot_token: Optional[str] = None
        self._expires_at: float = 0

    def get_token(self) -> str:
        """Get a valid Copilot session token, refreshing if needed.

        Returns:
            A valid Copilot API session token.

        Raises:
            CopilotTokenError: If the token exchange fails.
        """
        # Return cached token if still valid (with 60s buffer)
        if self._copilot_token and time.time() < (self._expires_at - 60):
            return self._copilot_token

        return self._refresh_token()

    def invalidate(self) -> None:
        """Force the next get_token() call to fetch a fresh Copilot session token."""
        self._copilot_token = None
        self._expires_at = 0

    def _refresh_token(self) -> str:
        """Exchange GitHub token for a fresh Copilot session token."""
        logger.info("Refreshing Copilot session token")

        req = urllib.request.Request(
            COPILOT_TOKEN_URL,
            headers={
                "Authorization": f"token {self.github_token}",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 401:
                raise CopilotTokenError(
                    "GitHub token is invalid or expired. Please re-authenticate with GitHub Copilot."
                )
            elif e.code == 403:
                logger.error(f"Copilot 403 response: {body}")
                raise CopilotTokenError(
                    "Access denied. Ensure you have an active GitHub Copilot subscription."
                )
            elif e.code == 404:
                raise CopilotTokenError(
                    "Copilot access not found (404). The OAuth token may have been "
                    "issued with an unrecognised client_id. Re-authenticate using the "
                    "VS Code client_id (Iv1.b507a08c87ecfe98) or check your Copilot subscription."
                )
            logger.error(f"Copilot token exchange failed: {e.code} {body}")
            raise CopilotTokenError(
                f"Copilot token exchange failed (HTTP {e.code}): {body}"
            )
        except Exception as e:
            logger.error(f"Copilot token exchange failed: {e}")
            raise CopilotTokenError(f"Failed to get Copilot token: {e}")

        self._copilot_token = data.get("token")
        self._expires_at = data.get("expires_at", 0)

        if not self._copilot_token:
            raise CopilotTokenError(f"No token in Copilot response: {data}")

        logger.info(f"Copilot session token refreshed (expires_at={self._expires_at})")
        return self._copilot_token
