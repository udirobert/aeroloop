import json

import httpx

import base_anchor
import commitments
import db
from conftest import make_pairs
from eth_account import Account


def test_base_not_configured(monkeypatch):
    monkeypatch.delenv("BASE_ANCHOR_PRIVATE_KEY", raising=False)
    r = base_anchor.anchor_root("ab" * 32)
    assert r["status"] == "not_configured"
    assert r["network"] == "base-sepolia"
    assert r["chain_id"] == 84532


def test_base_mocked_rpc_success(monkeypatch):
    key = Account.create().key.hex()
    monkeypatch.setenv("BASE_ANCHOR_PRIVATE_KEY", key)
    monkeypatch.setenv("BASE_RPC_URL", "https://rpc.test")
    acct = Account.from_key(key)
    sent_raw = {}
    root = "cd" * 32

    def handler(req):
        body = json.loads(req.content)
        m = body["method"]
        if m == "eth_maxPriorityFeePerGas":
            result = hex(1_000_000_000)
        elif m == "eth_feeHistory":
            result = {"baseFeePerGas": [hex(1_000_000_000)]}
        elif m == "eth_getTransactionCount":
            result = "0x0"
        elif m == "eth_estimateGas":
            result = hex(30_000)
        elif m == "eth_sendRawTransaction":
            sent_raw["data"] = body["params"][0]
            result = "0x" + "aa" * 32
        elif m == "eth_getTransactionReceipt":
            result = {"blockNumber": "0x1234", "status": "0x1"}
        elif m == "eth_getBlockByNumber":
            result = {"number": "0x1234", "timestamp": "0x691a4f00"}
        else:
            raise AssertionError(m)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = base_anchor.anchor_root(root, client=client)
    assert r["status"] == "confirmed"
    assert r["block"] == 0x1234
    from datetime import datetime, timezone
    assert r["block_time"] == (
        datetime.fromtimestamp(0x691a4f00, timezone.utc)
        .isoformat().replace("+00:00", "Z"))
    assert r["explorer_url"] == f"https://sepolia.basescan.org/tx/{r['tx_hash']}"

    # decode the signed EIP-1559 tx and check the payload + fields
    raw = bytes.fromhex(sent_raw["data"][2:])
    assert raw[0] == 0x02  # typed tx
    import rlp
    fields = rlp.decode(raw[1:])
    chain_id, nonce, _tip, _maxfee, _gas, to, value, data = fields[:8]
    assert int.from_bytes(chain_id, "big") == 84532
    assert "0x" + to.hex() == acct.address.lower()
    assert int.from_bytes(value, "big") == 0
    assert data == b"AEROLOOP1" + bytes.fromhex(root)


def test_base_rejects_unknown_chain(monkeypatch):
    """Any BASE_CHAIN_ID outside Base Sepolia/mainnet -> error, no tx sent."""
    monkeypatch.setenv("BASE_ANCHOR_PRIVATE_KEY", Account.create().key.hex())
    monkeypatch.setenv("BASE_CHAIN_ID", "1")
    calls = []

    def handler(req):
        calls.append(json.loads(req.content)["method"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                         "result": "0x0"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = base_anchor.anchor_root("ab" * 32, client=client)
    assert r["status"] == "error"
    assert "unsupported BASE_CHAIN_ID 1" in r["error"]
    assert calls == []  # no RPC traffic at all


def test_base_rpc_error(monkeypatch):
    key = Account.create().key.hex()
    monkeypatch.setenv("BASE_ANCHOR_PRIVATE_KEY", key)
    monkeypatch.setenv("BASE_RPC_URL", "https://rpc.test")

    def handler(req):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                         "error": {"message": "insufficient funds"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = base_anchor.anchor_root("ab" * 32, client=client)
    assert r["status"] == "error"
    assert key not in r["error"]  # never log the key


def test_build_endpoint_and_verify_flow(temp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORS_DIR", str(tmp_path / "anchors"))
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("BASE_ANCHOR_PRIVATE_KEY", raising=False)
    monkeypatch.setattr(commitments, "_ots_bin", lambda: None)
    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app) as client:
        client.post("/demo-day?hours=6")
        day = db.get_predictions()[0]["committed_at"][:10]
        r = client.post(f"/anchors/build?date={day}&force=true")
        assert r.status_code == 200
        built = r.json()
        assert built["status"] == "built"
        assert built["ots"]["status"] == "unavailable"
        assert built["base"]["status"] == "not_configured"

        v = client.get("/commitments/prediction/1").json()
        assert v["kind"] == "simulated"
        assert v["hash_matches"] is True
        assert v["reading_recorded_after_commit"] is True
        assert "self-reported" in v["committed_at_note"]
        assert v["existed_by"] is None  # base not configured -> no public bound
        assert v["existed_by_source"] is None
        assert v["target_after_existed_by"] is None
        assert v["anchor"]["proof_valid"] is True
        assert v["anchor"]["roots_consistent"] is True
        assert v["anchor"]["published_root"] == v["anchor"]["root"]
        assert v["anchor"]["batch_date"] == day

        listed = client.get("/anchors").json()
        assert listed[0]["batch_date"] == day


def test_admin_token_enforced(temp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORS_DIR", str(tmp_path / "anchors"))
    monkeypatch.setenv("ADMIN_TOKEN", "secret-token")
    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app) as client:
        assert client.post("/anchors/build?force=true").status_code == 401
        assert client.post(
            "/anchors/build?force=true",
            headers={"X-Admin-Token": "wrong"}).status_code == 401
        r = client.post("/anchors/build?force=true",
                        headers={"X-Admin-Token": "secret-token"})
        assert r.status_code == 200  # no commits -> "empty", not 401
        assert client.post("/anchors/upgrade-ots").status_code == 401


def test_blind_reppo_input(temp_db, monkeypatch, llm_spy):
    """The gate's eval text must not name the proposer or model."""
    monkeypatch.delenv("SERV_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("REPPO_API_KEY", raising=False)
    monkeypatch.delenv("TABPFN_ACCESS_TOKEN", raising=False)

    captured = []
    monkeypatch.setattr(
        __import__("reppo"), "run_gate", lambda text: captured.append(text) or
        {"status": "not_configured", "reppo": {"id": None}})

    import agent
    agent.run_tournament(make_pairs(24))
    assert captured  # at least the heuristic was accuracy-eligible
    for text in captured:
        for name in ("serv-nano", "serv-ultra", "open-weight",
                     "nemotron-mini", "tabpfn", "(model"):
            assert name not in text
        assert "PROPOSAL ID:" in text
