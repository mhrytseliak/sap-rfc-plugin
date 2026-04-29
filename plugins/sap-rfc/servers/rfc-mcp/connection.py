import keyring

SERVICE_NAME = "sap-rfc"


def _get(key: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, key)


def get_connection():
    from pyrfc import Connection

    ashost = _get("ashost")
    if not ashost:
        raise RuntimeError(
            "SAP credentials not found in keyring. Run /sap-connect to configure."
        )
    params = {
        "ashost": ashost,
        "sysnr": _get("sysnr") or "00",
        "client": _get("client") or "100",
        "user": _get("user"),
        "passwd": _get("passwd"),
        "lang": _get("lang") or "EN",
    }
    saprouter = _get("saprouter")
    if saprouter:
        params["saprouter"] = saprouter
    return Connection(**params)
