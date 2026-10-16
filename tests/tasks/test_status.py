import httpx

from conftest import cfg, write_cfg
from localexec.tasks.status import status


def _tags(models, running):
    def handler(req: httpx.Request):
        key = "models"
        names = running if req.url.path == "/api/ps" else models
        return httpx.Response(200, json={key: [{"name": n} for n in names]})
    return httpx.MockTransport(handler)


def test_status_variants(proj):
    cfg(proj)
    ok = status(proj, _tags(["qwen-coder-16k:latest"], ["qwen-coder-16k:latest"]))
    assert ok["status"] == "ok" and ok["model_installed"] and ok["model_loaded"] and ok["checks"] == ["syn"]
    cold = status(proj, _tags(["qwen-coder-16k:latest"], []))
    assert cold["status"] == "ok" and cold["model_loaded"] is False
    missing = status(proj, _tags(["llama3"], []))
    assert missing["status"] == "error" and "ollama list" in missing["hint"]

    def refuse(req):
        raise httpx.ConnectError("no")
    down = status(proj, httpx.MockTransport(refuse))
    assert down["status"] == "error" and "cannot reach" in down["ollama"]
    write_cfg(proj, "{bad")
    assert status(proj)["status"] == "error"
