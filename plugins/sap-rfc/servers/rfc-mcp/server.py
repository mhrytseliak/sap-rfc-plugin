import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
from tools import system, ddic, source, fm, text_pool, sapscript, syntax, source_write

mcp = FastMCP("rfc-mcp")
system.register(mcp)
ddic.register(mcp)
source.register(mcp)
fm.register(mcp)
text_pool.register(mcp)
sapscript.register(mcp)
syntax.register(mcp)
source_write.register(mcp)

if __name__ == "__main__":
    mcp.run()
