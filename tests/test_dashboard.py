"""
Tests unitaires pour le serveur Dashboard Web et son API REST.
"""
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.node import JarvisNode
from jarvismesh.skills import DEFAULT_SKILLS, DEFAULT_SCHEMAS
from jarvismesh.dashboard import DashboardServer


def _sync_http_get(url: str):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


def _sync_http_post(url: str, data: dict):
    payload_bytes = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload_bytes, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


async def http_get(url: str):
    return await asyncio.to_thread(_sync_http_get, url)


async def http_post(url: str, data: dict):
    return await asyncio.to_thread(_sync_http_post, url, data)


async def test_dashboard():
    print("== Test 1: Démarrage du nœud et du serveur Dashboard ==")
    node = JarvisNode(
        "dash-test-node",
        9301,
        skills={"echo": DEFAULT_SKILLS["echo"], "reverse": DEFAULT_SKILLS["reverse"]},
        schemas=DEFAULT_SCHEMAS,
    )
    await node.start(enable_zeroconf=False)

    dash = DashboardServer(node, host="127.0.0.1", port=9302)
    await dash.start()

    base_url = "http://127.0.0.1:9302"

    print("\n== Test 2: Fichiers statiques Web (HTML / CSS / JS) ==")
    status, html_content = await http_get(f"{base_url}/")
    print(f"  -> GET / : status={status}, len={len(html_content)}")
    assert status == 200 and "JarvisMesh" in html_content

    status_css, css_content = await http_get(f"{base_url}/style.css")
    print(f"  -> GET /style.css : status={status_css}, len={len(css_content)}")
    assert status_css == 200 and "--bg-dark" in css_content

    status_js, js_content = await http_get(f"{base_url}/app.js")
    print(f"  -> GET /app.js : status={status_js}, len={len(js_content)}")
    assert status_js == 200 and "addEventListener" in js_content

    print("\n== Test 3: API REST /api/status et /api/skills ==")
    status_api, status_body = await http_get(f"{base_url}/api/status")
    status_data = json.loads(status_body)
    print(f"  -> GET /api/status : name={status_data['name']}, port={status_data['port']}")
    assert status_data["name"] == "dash-test-node"
    assert "echo" in status_data["skills"]

    _, skills_body = await http_get(f"{base_url}/api/skills")
    skills_data = json.loads(skills_body)
    print(f"  -> GET /api/skills : {list(skills_data['skills'].keys())}")
    assert "echo" in skills_data["skills"]
    assert "reverse" in skills_data["skills"]

    print("\n== Test 4: API REST POST /api/delegate ==")
    code, del_res = await http_post(
        f"{base_url}/api/delegate",
        {"skill": "reverse", "payload": {"text": "dashboard"}},
    )
    print(f"  -> POST /api/delegate : ok={del_res.get('ok')} result={del_res.get('result')}")
    assert del_res["ok"] is True
    assert del_res["result"]["reversed"] == "draobhsad"

    print("\n== Test 5: API REST POST /api/workflow/run ==")
    wf_payload = {
        "workflow": {
            "name": "API Test Workflow",
            "stages": [
                {"name": "s1", "skill": "echo", "payload": {"text": "{input.msg}"}},
                {"name": "s2", "skill": "reverse", "payload": {"text": "{steps.s1.result.echo}"}},
            ],
        },
        "input": {"msg": "Supervision API"},
    }
    code_wf, wf_res = await http_post(f"{base_url}/api/workflow/run", wf_payload)
    print(f"  -> POST /api/workflow/run : ok={wf_res.get('ok')} duration={wf_res.get('duration_sec')}s")
    assert wf_res["ok"] is True
    assert wf_res["final_output"]["reversed"] == "IPA noisivrepuS"

    await dash.stop()
    await node.stop()
    print("\nTous les tests du Dashboard sont passés avec succès !")


if __name__ == "__main__":
    asyncio.run(test_dashboard())
