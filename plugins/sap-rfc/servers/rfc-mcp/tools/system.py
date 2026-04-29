import keyring

from connection import get_connection, SERVICE_NAME


def register(mcp):
    @mcp.tool()
    def ping() -> dict:
        """Verify SAP connectivity and identify the connected system.

        Call this FIRST when starting work on SAP, after `/sap-connect`, or whenever
        another tool returns a connection error — it confirms credentials are valid
        and tells you which system you're on (DEV/QAS/PRD, S/4 vs ECC, release).

        Returns: {status: 'ok'|'error', workspace, system_id, host, database,
        sap_release, s4_hana}. `workspace` is the landscape-XML display name
        stored at /sap-connect time (empty if connection predates workspace
        tracking — re-run /sap-connect to populate).
        On error: {status: 'error', type, message} — typically LogonError (bad creds)
        or CommunicationError (host/router/network).
        """
        from pyrfc import LogonError, CommunicationError
        try:
            conn = get_connection()
            conn.call("RFC_PING")
            sys_info = conn.call("RFC_SYSTEM_INFO")
            info = sys_info["RFCSI_EXPORT"]
            conn.close()
            workspace = keyring.get_password(SERVICE_NAME, "workspace") or ""
            return {
                "status": "ok",
                "workspace": workspace,
                "system_id": info.get("RFCSYSID", ""),
                "host": info.get("RFCHOST", ""),
                "database": info.get("RFCDBSYS", ""),
                "sap_release": info.get("RFCSAPRL", ""),
                "s4_hana": sys_info.get("S4_HANA", ""),
            }
        except LogonError as e:
            return {"status": "error", "type": "LogonError", "message": str(e)}
        except CommunicationError as e:
            return {"status": "error", "type": "CommunicationError", "message": str(e)}
        except Exception as e:
            return {"status": "error", "type": type(e).__name__, "message": str(e)}
