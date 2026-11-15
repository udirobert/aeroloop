"""Anchor a Merkle root on Base via raw JSON-RPC — no web3.py.

Tx: self-send, value 0, calldata = b"AEROLOOP1" + 32 root bytes, EIP-1559.
Env: BASE_RPC_URL (default Base Sepolia), BASE_CHAIN_ID (default 84532;
mainnet 8453 only when explicitly set), BASE_ANCHOR_PRIVATE_KEY (dedicated
low-balance wallet — never logged).
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from eth_account import Account

BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://sepolia.base.org")
DATA_PREFIX = b"AEROLOOP1"
RECEIPT_TIMEOUT_S = 120.0
RECEIPT_POLL_S = 2.0


def configured() -> bool:
    return bool(os.getenv("BASE_ANCHOR_PRIVATE_KEY"))


def _chain_id() -> int:
    return int(os.getenv("BASE_CHAIN_ID", "84532"))


ALLOWED_CHAIN_IDS = {84532: "base-sepolia", 8453: "base"}


def _network(chain_id: int) -> str:
    return ALLOWED_CHAIN_IDS.get(chain_id, f"unsupported-{chain_id}")


def _explorer_url(chain_id: int, tx: Optional[str]) -> Optional[str]:
    if not tx:
        return None
    host = "sepolia.basescan.org" if chain_id == 84532 else "basescan.org"
    return f"https://{host}/tx/{tx}"


def _client() -> httpx.Client:
    return httpx.Client(timeout=30)


def _rpc(client: httpx.Client, method: str, params: list) -> Any:
    url = os.getenv("BASE_RPC_URL", BASE_RPC_URL)
    r = client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method,
                               "params": params})
    body = r.json()
    if r.status_code != 200 or "error" in body:
        raise RuntimeError(f"{method} -> HTTP {r.status_code} {body.get('error')}")
    return body["result"]


def anchor_root(
    root_hex: str,
    receipt_timeout_s: float = RECEIPT_TIMEOUT_S,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Send the self-send anchor tx and poll for a receipt.

    Returns {status, network, chain_id, tx_hash, block, block_time, error,
    explorer_url} with status in confirmed|submitted|failed|error|not_configured.
    block_time is the confirmed block's UTC timestamp (ISO 8601, Z) — the
    publicly provable "existed by" bound for the anchor.
    """
    chain_id = _chain_id()
    out: Dict[str, Any] = {
        "status": "error", "network": _network(chain_id), "chain_id": chain_id,
        "tx_hash": None, "block": None, "block_time": None, "error": None,
        "explorer_url": None,
    }
    if chain_id not in ALLOWED_CHAIN_IDS:
        out["error"] = (
            f"unsupported BASE_CHAIN_ID {chain_id}; "
            "allowed: 84532 (base-sepolia), 8453 (base)"
        )
        return out
    key = os.getenv("BASE_ANCHOR_PRIVATE_KEY")
    if not key:
        out["status"] = "not_configured"
        return out

    own = client is None
    client = client or _client()
    try:
        account = Account.from_key(key)
        tip = int(_rpc(client, "eth_maxPriorityFeePerGas", []), 16)
        hist = _rpc(client, "eth_feeHistory", ["0x1", "latest", [50]])
        base_fee = int(hist["baseFeePerGas"][-1], 16)
        nonce = int(_rpc(client, "eth_getTransactionCount",
                         [account.address, "pending"]), 16)
        data = DATA_PREFIX + bytes.fromhex(root_hex)
        tx = {
            "type": 2,
            "chainId": chain_id,
            "nonce": nonce,
            "to": account.address,
            "value": 0,
            "data": data,
            "maxFeePerGas": 2 * base_fee + tip,
            "maxPriorityFeePerGas": tip,
        }
        est_params = {}
        for k, v in tx.items():
            if k == "type":
                continue
            est_params[k] = hex(v) if isinstance(v, int) else (
                "0x" + v.hex() if isinstance(v, bytes) else v)
        est = _rpc(client, "eth_estimateGas", [est_params])
        tx["gas"] = int(est, 16) if isinstance(est, str) else int(est)

        signed = Account.sign_transaction(tx, key)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = _rpc(client, "eth_sendRawTransaction",
                       ["0x" + raw.hex() if isinstance(raw, bytes) else raw])
        out["tx_hash"] = tx_hash
        out["explorer_url"] = _explorer_url(chain_id, tx_hash)

        deadline = time.monotonic() + receipt_timeout_s
        while time.monotonic() < deadline:
            receipt = _rpc(client, "eth_getTransactionReceipt", [tx_hash])
            if receipt is not None:
                out["block"] = int(receipt["blockNumber"], 16)
                out["status"] = ("confirmed"
                                 if int(receipt.get("status", "0x1"), 16) == 1
                                 else "failed")
                if out["status"] == "confirmed":
                    try:
                        blk = _rpc(client, "eth_getBlockByNumber",
                                   [hex(out["block"]), False])
                        ts = int(blk["timestamp"], 16)
                        out["block_time"] = (
                            datetime.fromtimestamp(ts, timezone.utc)
                            .isoformat().replace("+00:00", "Z")
                        )
                    except Exception:  # noqa: BLE001 — keep confirmed status
                        pass
                return out
            time.sleep(RECEIPT_POLL_S)
        out["status"] = "submitted"
        return out
    except Exception as e:  # noqa: BLE001 — the key is never included in errors
        out["status"] = "error"
        out["error"] = repr(e)[:300]
        return out
    finally:
        if own:
            client.close()
