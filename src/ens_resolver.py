"""
ens_resolver.py -- Real ENS Name Resolution for TrustAgent

Provides forward resolution (ENS name -> Ethereum address) and reverse
resolution (address -> ENS name) by making raw eth_call RPC requests to
the Ethereum mainnet ENS contracts.

ENS architecture (on-chain):
  1. ENS Registry (0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e)
     - owner(bytes32 node) -> address          (who controls this name)
     - resolver(bytes32 node) -> address       (which resolver holds records)
  2. Public Resolver (varies per name)
     - addr(bytes32 node) -> address           (forward resolution)
  3. Reverse Registrar
     - Reverse node for address X is namehash("<addr>.addr.reverse")
     - name(bytes32 node) -> string            (reverse resolution)

This module uses httpx to make JSON-RPC calls to a free Ethereum mainnet
RPC endpoint.  No web3.py dependency -- raw ABI encoding only.

Usage:
    from ens_resolver import ENSResolver

    resolver = ENSResolver()

    # Forward: name -> address
    addr = resolver.resolve("vitalik.eth")

    # Reverse: address -> name
    name = resolver.reverse_resolve("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")

    # Verify an ENS name matches a wallet before agent registration
    ok = resolver.verify_ens_ownership("myagent.eth", "0x1234...")
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"

# Free, reliable Ethereum mainnet RPC endpoints (fallback chain)
RPC_ENDPOINTS = [
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth",
    "https://ethereum-rpc.publicnode.com",
]

# ABI function selectors (first 4 bytes of keccak256 of the signature)
# resolver(bytes32 node) -> address
RESOLVER_SELECTOR = "0x0178b8bf"
# addr(bytes32 node) -> address
ADDR_SELECTOR = "0x3b3b57de"
# name(bytes32 node) -> string
NAME_SELECTOR = "0x691f3431"


# ---------------------------------------------------------------------------
# Namehash implementation (EIP-137)
# ---------------------------------------------------------------------------

def _keccak256(data: bytes) -> bytes:
    """Keccak-256 hash, implemented via hashlib (available in Python 3.6+)."""
    k = hashlib.new("sha3_256")
    # Python's sha3_256 is the FIPS-202 SHA-3, not Ethereum's keccak.
    # We need actual keccak-256.  Use pysha3 if available, else fall back
    # to a pure approach via the _pysha3 shim below.
    return _keccak256_impl(data)


def _keccak256_impl(data: bytes) -> bytes:
    """
    Keccak-256 using pycryptodome or pysha3, with a tiny pure-Python
    fallback for environments where neither is installed.
    """
    # Try pycryptodome first (most common in crypto projects)
    try:
        from Crypto.Hash import keccak as _ck
        k = _ck.new(digest_bits=256)
        k.update(data)
        return k.digest()
    except ImportError:
        pass

    # Try pysha3
    try:
        import sha3 as _sha3  # type: ignore
        k = _sha3.keccak_256()
        k.update(data)
        return k.digest()
    except ImportError:
        pass

    # Try the built-in hashlib (Python 3.11+ sometimes has keccak)
    try:
        import hashlib as _hl
        k = _hl.new("keccak_256")
        k.update(data)
        return k.digest()
    except (ValueError, AttributeError):
        pass

    # Pure-Python keccak-256 (compact reference implementation)
    return _keccak256_pure(data)


def _keccak256_pure(data: bytes) -> bytes:
    """
    Minimal pure-Python Keccak-256 so the module works without any
    external crypto library.  Based on the Keccak reference.
    """
    # Keccak-256: rate = 1088 bits = 136 bytes, capacity = 512 bits
    rate = 136
    output_len = 32

    # Padding: Keccak uses pad10*1 with domain byte 0x01
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    # State: 5x5 matrix of 64-bit lanes
    state = [0] * 25

    # Round constants
    RC = [
        0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
        0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
        0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
        0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
        0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
        0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
        0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
        0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
    ]

    ROT = [
        [0, 36, 3, 41, 18], [1, 44, 10, 45, 2],
        [62, 6, 43, 15, 61], [28, 55, 25, 21, 56],
        [27, 20, 39, 8, 14],
    ]

    MASK64 = (1 << 64) - 1

    def rot64(x: int, n: int) -> int:
        return ((x << n) | (x >> (64 - n))) & MASK64

    def keccak_f(st: list[int]) -> list[int]:
        for rc in RC:
            # Theta
            C = [st[x] ^ st[x + 5] ^ st[x + 10] ^ st[x + 15] ^ st[x + 20] for x in range(5)]
            D = [C[(x - 1) % 5] ^ rot64(C[(x + 1) % 5], 1) for x in range(5)]
            st = [(st[i] ^ D[i % 5]) & MASK64 for i in range(25)]
            # Rho and Pi
            B = [0] * 25
            for x in range(5):
                for y in range(5):
                    B[y * 5 + ((2 * x + 3 * y) % 5)] = rot64(st[x + y * 5], ROT[x][y])
            # Chi
            st = [(B[i] ^ ((~B[(i // 5) * 5 + (i % 5 + 1) % 5] & MASK64) & B[(i // 5) * 5 + (i % 5 + 2) % 5])) & MASK64 for i in range(25)]
            # Iota
            st[0] ^= rc
        return st

    # Absorb
    for offset in range(0, len(padded), rate):
        block = padded[offset:offset + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8:(i + 1) * 8], "little")
            state[i] ^= lane
        state = keccak_f(state)

    # Squeeze
    out = b""
    while len(out) < output_len:
        for i in range(rate // 8):
            out += state[i].to_bytes(8, "little")
            if len(out) >= output_len:
                break
        if len(out) < output_len:
            state = keccak_f(state)

    return out[:output_len]


def namehash(name: str) -> bytes:
    """
    Compute the EIP-137 namehash for an ENS name.

    namehash("") = 0x00...00  (32 zero bytes)
    namehash("eth") = keccak256(namehash("") + keccak256("eth"))
    namehash("foo.eth") = keccak256(namehash("eth") + keccak256("foo"))
    """
    if not name:
        return b"\x00" * 32
    labels = name.split(".")
    node = b"\x00" * 32
    for label in reversed(labels):
        label_hash = _keccak256(label.encode("utf-8"))
        node = _keccak256(node + label_hash)
    return node


# ---------------------------------------------------------------------------
# RPC helper
# ---------------------------------------------------------------------------

def _eth_call(to: str, data: str, rpc_url: str | None = None) -> str:
    """
    Make an eth_call to the given contract and return the hex result.

    Tries multiple RPC endpoints on failure.
    """
    endpoints = [rpc_url] if rpc_url else RPC_ENDPOINTS

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {"to": to, "data": data},
            "latest",
        ],
    }

    last_error: Exception | None = None
    for endpoint in endpoints:
        try:
            resp = httpx.post(
                endpoint,
                json=payload,
                timeout=15.0,
                headers={"Content-Type": "application/json"},
            )
            body = resp.json()
            if "error" in body:
                last_error = RuntimeError(f"RPC error: {body['error']}")
                continue
            return body.get("result", "0x")
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(f"All RPC endpoints failed. Last error: {last_error}")


# ---------------------------------------------------------------------------
# ABI encoding/decoding helpers
# ---------------------------------------------------------------------------

def _encode_bytes32(b: bytes) -> str:
    """Encode a bytes32 value as hex (no 0x prefix, 64 chars)."""
    return b.hex().ljust(64, "0")[:64]


def _decode_address(hex_result: str) -> str | None:
    """Decode an address from an eth_call result (last 20 bytes of 32-byte word)."""
    raw = hex_result.replace("0x", "")
    if len(raw) < 64 or raw == "0" * 64:
        return None
    addr = "0x" + raw[-40:]
    if addr == "0x" + "0" * 40:
        return None
    return addr


def _decode_string(hex_result: str) -> str | None:
    """Decode a Solidity string return value from an eth_call result."""
    raw = hex_result.replace("0x", "")
    if len(raw) < 128 or raw == "0" * len(raw):
        return None
    try:
        # ABI-encoded string: offset (32 bytes) + length (32 bytes) + data
        offset = int(raw[0:64], 16) * 2  # offset in hex chars
        length = int(raw[offset:offset + 64], 16)
        if length == 0:
            return None
        data_start = offset + 64
        data_hex = raw[data_start:data_start + length * 2]
        return bytes.fromhex(data_hex).decode("utf-8")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ENS Resolver class
# ---------------------------------------------------------------------------

class ENSResolver:
    """
    Resolves ENS names on Ethereum mainnet using raw JSON-RPC calls.

    Forward resolution:
        1. Query the ENS Registry for the resolver address of a name
        2. Query the resolver for the ETH address (addr record)

    Reverse resolution:
        1. Compute the reverse node for an address
        2. Query the ENS Registry for the resolver of that reverse node
        3. Query the resolver for the name record
    """

    def __init__(self, rpc_url: str | None = None):
        self.rpc_url = rpc_url
        self._cache: dict[str, tuple[str | None, float]] = {}
        self._cache_ttl = 300  # 5-minute cache

    def _get_resolver(self, node: bytes) -> str | None:
        """Get the resolver contract address for a given namehash node."""
        call_data = RESOLVER_SELECTOR + _encode_bytes32(node)
        result = _eth_call(ENS_REGISTRY, call_data, self.rpc_url)
        return _decode_address(result)

    def resolve(self, name: str) -> str | None:
        """
        Resolve an ENS name to an Ethereum address.

        Parameters
        ----------
        name : str
            The ENS name to resolve (e.g. "vitalik.eth")

        Returns
        -------
        str or None
            The checksummed Ethereum address, or None if the name
            does not resolve.
        """
        name = name.lower().strip()

        # Check cache
        if name in self._cache:
            cached_addr, cached_at = self._cache[name]
            if time.time() - cached_at < self._cache_ttl:
                return cached_addr

        node = namehash(name)

        # Step 1: get the resolver for this name
        resolver_addr = self._get_resolver(node)
        if not resolver_addr:
            self._cache[name] = (None, time.time())
            return None

        # Step 2: call addr(node) on the resolver
        call_data = ADDR_SELECTOR + _encode_bytes32(node)
        result = _eth_call(resolver_addr, call_data, self.rpc_url)
        address = _decode_address(result)

        # Checksum the address
        if address:
            address = _to_checksum_address(address)

        self._cache[name] = (address, time.time())
        return address

    def reverse_resolve(self, address: str) -> str | None:
        """
        Reverse-resolve an Ethereum address to its primary ENS name.

        Parameters
        ----------
        address : str
            The Ethereum address (with or without 0x prefix)

        Returns
        -------
        str or None
            The primary ENS name, or None if no reverse record exists.
        """
        address = address.lower().replace("0x", "")
        reverse_name = f"{address}.addr.reverse"
        node = namehash(reverse_name)

        # Step 1: get the resolver for the reverse node
        resolver_addr = self._get_resolver(node)
        if not resolver_addr:
            return None

        # Step 2: call name(node) on the resolver
        call_data = NAME_SELECTOR + _encode_bytes32(node)
        result = _eth_call(resolver_addr, call_data, self.rpc_url)
        return _decode_string(result)

    def verify_ens_ownership(self, ens_name: str, expected_address: str) -> bool:
        """
        Verify that an ENS name resolves to the expected address.

        Used during agent registration to confirm the registrant actually
        controls the ENS name they claim.

        Parameters
        ----------
        ens_name : str
            The ENS name (e.g. "myagent.eth")
        expected_address : str
            The wallet address that should own this name

        Returns
        -------
        bool
            True if the ENS name resolves to the expected address
        """
        resolved = self.resolve(ens_name)
        if resolved is None:
            return False
        return resolved.lower() == expected_address.lower()

    def resolve_agent_identity(self, ens_name: str) -> dict:
        """
        Full ENS identity resolution for an agent.

        Returns a rich identity object with forward resolution, reverse
        verification, and metadata -- suitable for display in the
        TrustAgent dashboard.

        Parameters
        ----------
        ens_name : str
            The ENS name to resolve (e.g. "trustagent.eth")

        Returns
        -------
        dict
            Identity object with address, reverse-verified status, and
            resolution metadata.
        """
        address = self.resolve(ens_name)

        result = {
            "ens_name": ens_name,
            "resolved_address": address,
            "resolution_status": "resolved" if address else "not_found",
            "reverse_verified": False,
            "reverse_name": None,
        }

        if address:
            reverse_name = self.reverse_resolve(address)
            result["reverse_name"] = reverse_name
            result["reverse_verified"] = (
                reverse_name is not None
                and reverse_name.lower() == ens_name.lower()
            )

        return result

    def batch_resolve(self, names: list[str]) -> dict[str, str | None]:
        """
        Resolve multiple ENS names.

        Parameters
        ----------
        names : list[str]
            List of ENS names to resolve

        Returns
        -------
        dict
            Mapping of name -> address (or None)
        """
        return {name: self.resolve(name) for name in names}


# ---------------------------------------------------------------------------
# EIP-55 checksum address
# ---------------------------------------------------------------------------

def _to_checksum_address(address: str) -> str:
    """Convert an address to EIP-55 checksummed format."""
    address = address.lower().replace("0x", "")
    addr_hash = _keccak256(address.encode("ascii")).hex()

    checksummed = "0x"
    for i, char in enumerate(address):
        if char in "0123456789":
            checksummed += char
        elif int(addr_hash[i], 16) >= 8:
            checksummed += char.upper()
        else:
            checksummed += char

    return checksummed


# ---------------------------------------------------------------------------
# ENS Verification Error
# ---------------------------------------------------------------------------

class ENSVerificationError(Exception):
    """
    Raised when ENS verification fails during agent registration.

    The AgentRegistry contract on-chain accepts any string as an ensName,
    so this off-chain error provides the enforcement layer that prevents
    agents from claiming ENS names they do not control.
    """
    pass


# ---------------------------------------------------------------------------
# Integration with AgentRegistry
# ---------------------------------------------------------------------------

class ENSAgentRegistry:
    """
    Wraps ENS resolution into the TrustAgent agent registration flow.

    When an agent registers with an ENS name, this class:
      1. Resolves the name to verify it exists on-chain
      2. Checks forward resolution matches the registrant's wallet
      3. Checks reverse resolution for bidirectional verification
      4. Returns an enriched registration object with ENS metadata

    This makes ENS names the primary identifier for agents, not just a
    cosmetic label.
    """

    def __init__(self, rpc_url: str | None = None):
        self.resolver = ENSResolver(rpc_url=rpc_url)

    def register_with_ens(
        self,
        agent_name: str,
        ens_name: str,
        wallet_address: str,
        capabilities: list[str],
        *,
        strict: bool = True,
    ) -> dict:
        """
        Register an agent with ENS verification.

        Off-chain enforcement: the on-chain AgentRegistry contract accepts
        any string as ensName, so this method provides a critical validation
        layer.  When ``strict=True`` (the default), registration is REJECTED
        if the ENS name does not resolve to the agent's wallet address.  This
        prevents agents from claiming ENS names they do not control.

        Parameters
        ----------
        agent_name : str
            Human-readable agent name
        ens_name : str
            ENS name to associate with the agent
        wallet_address : str
            Wallet address of the agent
        capabilities : list[str]
            List of agent capabilities
        strict : bool, default True
            If True, raise ``ENSVerificationError`` when the ENS name does
            not resolve to ``wallet_address``.  If False, registration
            proceeds with a warning (backward-compatible behaviour).

        Returns
        -------
        dict
            Registration result with ENS verification status

        Raises
        ------
        ENSVerificationError
            If ``strict=True`` and ENS verification fails.  The error
            message explains *why* the registration was rejected so the
            caller can take corrective action.
        """
        # Step 1: Resolve the ENS name
        identity = self.resolver.resolve_agent_identity(ens_name)

        # Step 2: Verify ownership if the name resolves
        ownership_verified = False
        if identity["resolved_address"]:
            ownership_verified = self.resolver.verify_ens_ownership(
                ens_name, wallet_address
            )

        # Step 2b: Enforce ENS ownership (off-chain guard for on-chain gap)
        if strict and not ownership_verified:
            if identity["resolved_address"] is None:
                raise ENSVerificationError(
                    f"Registration rejected: ENS name '{ens_name}' does not "
                    f"resolve to any address on Ethereum mainnet.  The agent "
                    f"cannot claim an unregistered or expired ENS name.  "
                    f"Register '{ens_name}' on ENS (https://app.ens.domains) "
                    f"and point it to {wallet_address} before retrying."
                )
            else:
                raise ENSVerificationError(
                    f"Registration rejected: ENS name '{ens_name}' resolves "
                    f"to {identity['resolved_address']}, but the agent wallet "
                    f"is {wallet_address}.  The resolved address does not "
                    f"match the registrant's wallet.  Only the address that "
                    f"controls the ENS name may register with it."
                )

        # Step 3: Build the registration record
        verification_level = _compute_verification_level(
            identity, ownership_verified
        )

        registration = {
            "agent_name": agent_name,
            "ens_name": ens_name,
            "wallet_address": wallet_address,
            "capabilities": capabilities,
            "ens_verification": {
                "name_resolved": identity["resolution_status"] == "resolved",
                "resolved_address": identity["resolved_address"],
                "ownership_match": ownership_verified,
                "reverse_verified": identity["reverse_verified"],
                "reverse_name": identity["reverse_name"],
                "verification_level": verification_level,
                "enforcement": "strict" if strict else "permissive",
            },
            "registration_status": "approved" if ownership_verified else "warning",
            "primary_identifier": ens_name if ownership_verified else wallet_address,
            "timestamp": time.time(),
        }

        # Non-strict mode: attach a warning instead of raising
        if not strict and not ownership_verified:
            registration["warning"] = (
                f"ENS verification failed for '{ens_name}'. The name "
                f"{'does not resolve' if not identity['resolved_address'] else 'resolves to a different address'}. "
                f"Registration proceeded in permissive mode but the agent "
                f"will not receive ENS-verified trust status."
            )

        return registration


def _compute_verification_level(identity: dict, ownership_verified: bool) -> str:
    """
    Compute ENS verification level for display.

    Levels:
      - "full"     -- forward + reverse both match (gold standard)
      - "forward"  -- forward resolves to the claimed address
      - "partial"  -- name resolves but to a different address
      - "none"     -- name does not resolve
    """
    if not identity["resolved_address"]:
        return "none"
    if ownership_verified and identity["reverse_verified"]:
        return "full"
    if ownership_verified:
        return "forward"
    return "partial"


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo():
    """Demonstrate real ENS resolution for TrustAgent."""
    print("=" * 72)
    print("  TrustAgent ENS Resolver")
    print("  Real Ethereum Mainnet ENS Name Resolution")
    print("=" * 72)

    resolver = ENSResolver()

    # --- Forward Resolution ---
    print("\n--- Forward Resolution (name -> address) ---")
    test_names = ["vitalik.eth", "nick.eth", "trustagent.eth"]
    for name in test_names:
        try:
            addr = resolver.resolve(name)
            if addr:
                print(f"  {name:30s} -> {addr}")
            else:
                print(f"  {name:30s} -> [not found]")
        except Exception as e:
            print(f"  {name:30s} -> [error: {e}]")

    # --- Reverse Resolution ---
    print("\n--- Reverse Resolution (address -> name) ---")
    # Vitalik's known address
    vitalik_addr = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    try:
        reverse_name = resolver.reverse_resolve(vitalik_addr)
        if reverse_name:
            print(f"  {vitalik_addr} -> {reverse_name}")
        else:
            print(f"  {vitalik_addr} -> [no reverse record]")
    except Exception as e:
        print(f"  {vitalik_addr} -> [error: {e}]")

    # --- Full Identity Resolution ---
    print("\n--- Full Agent Identity Resolution ---")
    identity = resolver.resolve_agent_identity("vitalik.eth")
    print(json.dumps(identity, indent=2))

    # --- Agent Registration with ENS Verification (strict mode) ---
    print("\n--- Agent Registration with ENS Verification (strict) ---")
    registry = ENSAgentRegistry()
    registration = registry.register_with_ens(
        agent_name="ResearchAgent",
        ens_name="vitalik.eth",
        wallet_address=vitalik_addr,
        capabilities=["research", "analysis", "public-goods-eval"],
    )
    print(json.dumps(registration, indent=2, default=str))

    # --- Demonstrate ENS enforcement: mismatched address ---
    print("\n--- ENS Enforcement: Mismatched Address (strict) ---")
    try:
        registry.register_with_ens(
            agent_name="FakeAgent",
            ens_name="vitalik.eth",
            wallet_address="0x0000000000000000000000000000000000001234",
            capabilities=["fraud"],
        )
        print("  ERROR: registration should have been rejected!")
    except ENSVerificationError as e:
        print(f"  REJECTED: {e}")

    # --- Demonstrate ENS enforcement: unregistered name ---
    print("\n--- ENS Enforcement: Unregistered Name (strict) ---")
    try:
        registry.register_with_ens(
            agent_name="GhostAgent",
            ens_name="nonexistent-name-xyz-12345.eth",
            wallet_address="0x0000000000000000000000000000000000005678",
            capabilities=["ghost"],
        )
        print("  ERROR: registration should have been rejected!")
    except ENSVerificationError as e:
        print(f"  REJECTED: {e}")

    # --- Demonstrate permissive mode (backward compatible) ---
    print("\n--- ENS Registration: Permissive Mode (strict=False) ---")
    permissive_result = registry.register_with_ens(
        agent_name="TestAgent",
        ens_name="vitalik.eth",
        wallet_address="0x0000000000000000000000000000000000001234",
        capabilities=["test"],
        strict=False,
    )
    print(f"  Status: {permissive_result['registration_status']}")
    print(f"  Warning: {permissive_result.get('warning', 'none')}")

    # --- Batch Resolution ---
    print("\n--- Batch Resolution ---")
    results = resolver.batch_resolve(["vitalik.eth", "nick.eth", "nonexistent12345.eth"])
    for name, addr in results.items():
        status = addr if addr else "[not found]"
        print(f"  {name:30s} -> {status}")

    print("\n" + "=" * 72)
    print("  ENS is core to TrustAgent identity:")
    print("  - Names replace addresses as the primary identifier")
    print("  - Forward + reverse resolution verifies ownership")
    print("  - Registration ENFORCES ENS verification (off-chain guard)")
    print("  - Mismatched addresses are REJECTED with clear error messages")
    print("=" * 72)


if __name__ == "__main__":
    demo()
