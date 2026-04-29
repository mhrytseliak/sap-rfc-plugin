# sap-connect

Connect to a SAP system via RFC.

## Auto-trigger keywords
SAP connection, SAP logon, connect to SAP, RFC connection, landscape XML, SAP system, pyrfc

## What it does
1. Parses SAP Logon landscape XML or accepts manual entry
2. Opens a secure logon dialog (Client, User, Password, Language)
3. Stores credentials in OS keyring
4. Detects and stores SAP Router strings automatically
5. Registers the MCP server for SAP tools
