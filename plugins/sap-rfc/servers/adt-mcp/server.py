import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP

from tools import (
    ping as t_ping,
    syntax as t_syntax,
    transport as t_transport,
    transport_create as t_transport_create,
    create_program as t_create_program,
    create_include as t_create_include,
    create_class as t_create_class,
    source_write as t_source_write,
    activate as t_activate,
    code_inspector as t_code_inspector,
)

mcp = FastMCP("adt-mcp")
t_ping.register(mcp)
t_syntax.register(mcp)
t_transport.register(mcp)
t_transport_create.register(mcp)
t_create_program.register(mcp)
t_create_include.register(mcp)
t_create_class.register(mcp)
t_source_write.register(mcp)
t_activate.register(mcp)
t_code_inspector.register(mcp)

if __name__ == "__main__":
    mcp.run()
