"""End-to-end smoke test: real MCP stdio client -> server -> fake Ollama HTTP endpoint.

Usage: uv run python scripts/smoke_client.py
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPLY = "FILE: calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n"


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({"message": {"content": REPLY}, "done_reason": "stop", "prompt_eval_count": 50, "eval_count": 20}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


async def main() -> None:
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    root = Path(tempfile.mkdtemp()).resolve()
    g = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (root / ".localexec.json").write_text(json.dumps({"checks": [{"name": "syn", "argv": [sys.executable, "-c", "print('ok')"]}]}))
    g("add", "-A"); g("commit", "-qm", "i")
    env = {**os.environ, "LOCALEXEC_OLLAMA_URL": f"http://127.0.0.1:{srv.server_port}"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "localexec.server"], cwd=str(root), env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])
            res = await s.call_tool("implement_task", {"task_id": "S1", "spec": "fix add", "files_to_edit": ["calc.py"]})
            print("content blocks:", len(res.content), "| structured:", getattr(res, "structured_content", None))
            print(res.content[0].text)
            print("file:", (root / "calc.py").read_text().strip().splitlines()[-1])
            print(res.content[0].text and "revert:", (await s.call_tool("revert_task", {"task_id": "S1"})).content[0].text)
            print("file:", (root / "calc.py").read_text().strip().splitlines()[-1])


asyncio.run(main())
