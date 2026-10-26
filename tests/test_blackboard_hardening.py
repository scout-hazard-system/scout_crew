"""Blackboard key-endpoint hardening, including the NUC scout-bb-refresh flow."""

from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from scout_crew.blackboard import auth
from scout_crew.blackboard.server import ServerState, make_handler
from scout_crew.blackboard.store import BlackboardStore

SECRET = "s" * 64
ADMIN = "a" * 64
ENTRY = "entry-token-for-tests"
# Exactly what /usr/local/sbin/scout-bb-refresh on the NUC requests.
NUC_ROLES = {
    "alert": ["pipeline"], "intel": ["pipeline"], "vet": ["pipeline"],
    "rank": ["pipeline"], "core": ["pipeline"],
    "manager": ["pipeline", "dev_debug"], "dev": ["pipeline", "dev_debug"],
    "hermes": ["pipeline", "dev_debug"], "pa": ["pipeline", "dev_debug"],
}


def _serve(**kw):
    store = BlackboardStore(memory=True)
    state = ServerState(store, secret=SECRET, entry_token=ENTRY, **kw)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, store, f"http://127.0.0.1:{httpd.server_address[1]}"


@pytest.fixture()
def default_server():
    httpd, store, base = _serve(admin_secret=ADMIN)
    yield base
    httpd.shutdown()
    store.close()


@pytest.fixture()
def dell_server():
    httpd, store, base = _serve(admin_secret=ADMIN, entry_roles=set(NUC_ROLES))
    yield base
    httpd.shutdown()
    store.close()


def _call(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _authorize(base, role, cats, proof=None):
    return _call(base, "POST", "/v1/keys/authorize",
                 {"proof": proof or {"entry_token": ENTRY}, "device_id": "nuxci7",
                  "role": role, "categories": cats, "ttl": 86400})


def test_default_entry_roles_refuse_admin(default_server):
    assert _authorize(default_server, "manager", ["pipeline"])[0] == 403
    assert _authorize(default_server, "alert", ["pipeline"])[0] == 200


def test_nuc_refresh_flow_still_works_with_explicit_roles(dell_server):
    for role, cats in NUC_ROLES.items():
        code, body = _authorize(dell_server, role, cats)
        assert code == 200, (role, body)
        assert auth.verify_token(SECRET, body["token"])["role"] == role


def test_category_outside_acl_refused(dell_server):
    assert _authorize(dell_server, "alert", ["dev_debug"])[0] == 400


def test_captcha_only_proof_refused():
    httpd, store, base = _serve()
    try:
        state_less = _call(base, "POST", "/v1/keys/authorize", {"proof": {"captcha_token": "x"}, "role": "alert"})
        assert state_less[0] == 401  # entry token configured -> wrong proof
    finally:
        httpd.shutdown()
        store.close()
    store = BlackboardStore(memory=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(ServerState(store, secret=SECRET)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        code, _ = _call(f"http://127.0.0.1:{httpd.server_address[1]}", "POST", "/v1/keys/authorize",
                        {"proof": {"captcha_token": "x"}, "role": "alert"})
        assert code == 503
    finally:
        httpd.shutdown()
        store.close()


def test_separate_admin_secret(default_server):
    assert _call(default_server, "POST", "/v1/keys/issue", {"role": "manager"}, {"X-Scout-Admin": SECRET})[0] == 401
    assert _call(default_server, "POST", "/v1/keys/issue", {"role": "manager"}, {"X-Scout-Admin": ADMIN})[0] == 200


def test_legacy_admin_secret_when_unset():
    httpd, store, base = _serve()
    try:
        assert _call(base, "POST", "/v1/keys/issue", {"role": "manager"}, {"X-Scout-Admin": SECRET})[0] == 200
    finally:
        httpd.shutdown()
        store.close()


def test_stats_requires_token(default_server):
    assert _call(default_server, "GET", "/v1/stats")[0] == 401


def test_meta_provenance_from_token(default_server):
    tok = auth.mint_token(SECRET, role="alert", categories=["pipeline"], device_id="nuxci7")
    code, body = _call(default_server, "POST", "/v1/write",
                       {"category": "pipeline", "role": "alert", "title": "t", "body": "b",
                        "meta": {"device_id": "forged"}},
                       {"Authorization": f"Bearer {tok}"})
    assert code == 200, body
    assert body["meta"]["device_id"] == "nuxci7"


def test_body_cap(default_server):
    from urllib.parse import urlparse

    u = urlparse(default_server)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
    conn.putrequest("POST", "/v1/write")
    conn.putheader("Content-Length", str(2 * 1024 * 1024))
    conn.endheaders()
    assert conn.getresponse().status == 413
    conn.close()


def test_token_needs_exp_and_reserved_claims():
    tok = auth.mint_token(SECRET, role="alert", categories=["pipeline"], extra={"role": "manager"})
    assert auth.verify_token(SECRET, tok)["role"] == "alert"
    claims = auth.parse_token(tok)
    claims.pop("exp")
    p64 = auth._b64e(json.dumps(claims, separators=(",", ":")).encode())
    with pytest.raises(auth.TokenError):
        auth.verify_token(SECRET, f"{p64}.{auth._sign(SECRET, p64)}")


@pytest.mark.parametrize("url,ok", [
    ("http://10.66.0.1:11434", True), ("http://localhost:11434", True),
    ("https://evil.example.com:11434", False), ("http://172.217.4.46:11434", False),
])
def test_local_only(monkeypatch, url, ok):
    from scout_crew import local_llms

    monkeypatch.setenv("OLLAMA_HOST_ALERT", url)
    if ok:
        local_llms.assert_local_only()
    else:
        with pytest.raises(RuntimeError):
            local_llms.assert_local_only()
