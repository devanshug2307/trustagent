"""
mech_client_test.py — TrustAgent Mech Client Test

Sends requests to the TrustAgent mech server via HTTP to demonstrate
the full mech request/deliver lifecycle over the network.

Usage:
    # First start the server in another terminal:
    #   python3 -m src.mech_server --port 8080
    #
    # Then run this client:
    #   python3 -m src.mech_client_test
    #   python3 -m src.mech_client_test --requests 60
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import urllib.request
import urllib.error


MECH_SERVER_URL = "http://localhost:8080"
TOOL_NAME = "reputation_evaluation"
FEE_WEI = 100000


def send_request(prompt: str, sender: str = "0x" + "0" * 40) -> Dict[str, Any]:
    """Send a single request to the mech server."""
    payload = json.dumps({
        "prompt": prompt,
        "tool": TOOL_NAME,
        "sender": sender,
        "fee_wei": FEE_WEI,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{MECH_SERVER_URL}/api/v1/request",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_tools() -> List[Dict[str, Any]]:
    """Get available tools from the mech server."""
    req = urllib.request.Request(f"{MECH_SERVER_URL}/api/v1/tools")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_stats() -> Dict[str, Any]:
    """Get server statistics."""
    req = urllib.request.Request(f"{MECH_SERVER_URL}/api/v1/stats")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    import argparse

    parser = argparse.ArgumentParser(description="TrustAgent Mech Client Test")
    parser.add_argument("--requests", type=int, default=55, help="Number of requests")
    parser.add_argument("--url", type=str, default=MECH_SERVER_URL, help="Server URL")
    args = parser.parse_args()

    global MECH_SERVER_URL
    MECH_SERVER_URL = args.url

    print("=" * 60)
    print("  TrustAgent Mech Client — HTTP Request Test")
    print(f"  Server: {MECH_SERVER_URL}")
    print(f"  Requests: {args.requests}")
    print("=" * 60)

    # Check server health
    try:
        tools = get_tools()
        print(f"\n  Tools available: {[t['name'] for t in tools]}")
    except Exception as e:
        print(f"\n  ERROR: Cannot reach server at {MECH_SERVER_URL}")
        print(f"  Start server with: python3 -m src.mech_server --port 8080")
        print(f"  Error: {e}")
        sys.exit(1)

    # Send requests
    results = []
    total_start = time.time()

    for i in range(1, args.requests + 1):
        if i <= 10:
            prompt = json.dumps({"action": "reputation", "agent_id": i})
            desc = f"Agent {i} reputation"
        elif i <= 25:
            proj = {"action": "project", "name": f"Project-{i}", "category": "general",
                    "funding_requested": i * 1000, "team_size": i % 5 + 1}
            prompt = json.dumps(proj)
            desc = f"Project-{i} eval"
        else:
            prompt = f"Evaluate agent {(i % 10) + 1} reputation"
            desc = f"NL agent query #{i}"

        try:
            delivery = send_request(prompt, sender=f"0x{'f' * 38}{i:02x}")
            status = delivery["status"]
            time_ms = delivery["delivery"]["delivery_time_ms"]
            mark = "OK" if status == "delivered" else "FAIL"
            print(f"  [{i:3d}/{args.requests}] {mark} | {time_ms:7.1f}ms | {desc}")
            results.append(delivery)
        except Exception as e:
            print(f"  [{i:3d}/{args.requests}] ERR | {desc}: {e}")

    total_time = time.time() - total_start

    # Final stats
    stats = get_stats()
    print(f"\n{'='*60}")
    print(f"  Server stats: {stats['delivered']} delivered, {stats['failed']} failed")
    print(f"  Total revenue: {stats['total_revenue_eth']:.6f} ETH")
    print(f"  Wall time: {total_time:.2f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
