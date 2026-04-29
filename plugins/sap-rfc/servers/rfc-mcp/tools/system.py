import keyring

from connection import get_connection, SERVICE_NAME
from timeout import with_timeout, RFCTimeout, PING_TIMEOUT


def _ping_impl() -> dict:
    conn = get_connection()
    try:
        conn.call("RFC_PING")
        sys_info = conn.call("RFC_SYSTEM_INFO")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    info = sys_info["RFCSI_EXPORT"]
    workspace = keyring.get_password(SERVICE_NAME, "workspace") or ""
    return {
        "workspace": workspace,
        "system_id": info.get("RFCSYSID", ""),
        "host": info.get("RFCHOST", ""),
        "sap_release": info.get("RFCSAPRL", ""),
    }


def register(mcp):
    @mcp.tool()
    def ping() -> dict:
        """Verify SAP connectivity and identify the connected system.

        Call this FIRST when starting work on SAP, after `/sap-connect`, or whenever
        another tool returns a connection error — it confirms credentials are valid
        and tells you which system you're on (DEV/QAS/PRD, S/4 vs ECC, release).

        Uses a short 10-second timeout (vs 60s for other RFC tools) so unhealthy
        systems fail fast.

        Returns: {workspace, system_id, host, sap_release} on success.
        `workspace` is the landscape-XML display name stored at /sap-connect
        time (empty if connection predates workspace tracking — re-run
        /sap-connect to populate).
        On error: {status: 'error', type, message} — typically LogonError (bad
        creds), CommunicationError (host/router/network), or Timeout.
        """
        from pyrfc import LogonError, CommunicationError
        try:
            return with_timeout(_ping_impl, seconds=PING_TIMEOUT)
        except RFCTimeout as e:
            return {"status": "error", "type": "Timeout", "message": str(e)}
        except LogonError as e:
            return {"status": "error", "type": "LogonError", "message": str(e)}
        except CommunicationError as e:
            return {"status": "error", "type": "CommunicationError", "message": str(e)}
        except Exception as e:
            return {"status": "error", "type": type(e).__name__, "message": str(e)}
