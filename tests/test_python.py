"""
test_python.py — Offline pytest tests for TrustAgent (Project 2)

Tests pure logic only — no API keys, no network access required.
"""

import math
import sys
import os

import pytest

# Ensure the project root is on sys.path so we can import from src.*
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# 1. public_goods_evaluator.py tests
# ---------------------------------------------------------------------------

from src.public_goods_evaluator import (
    reputation_to_weight,
    PublicGoodsEvaluator,
    ScoredProject,
    Project,
    Evaluation,
)


class TestReputationToWeight:
    """Test the reputation_to_weight() helper."""

    def test_zero_reputation_returns_zero(self):
        """Score of 0 should produce weight of 0 regardless of other factors."""
        assert reputation_to_weight(0, 100, 100) == 0.0

    def test_max_reputation_basic(self):
        """Score=10000, no tasks, no attestations -> 1.0 * 1.0 * 1.0 = 1.0."""
        w = reputation_to_weight(10000, 0, 0)
        assert w == pytest.approx(1.0)

    def test_experience_log_scale(self):
        """completed=1 -> log2(2)+1 = 2.0 experience factor."""
        w = reputation_to_weight(10000, 1, 0)
        expected = 1.0 * (math.log2(2) + 1) * math.sqrt(1)
        assert w == pytest.approx(expected)

    def test_experience_cap_at_4x(self):
        """Very high completed count should cap experience factor at 4.0."""
        # log2(1000+1)+1 ≈ 10.97, capped at 4.0
        w = reputation_to_weight(10000, 1000, 0)
        expected = 1.0 * 4.0 * 1.0
        assert w == pytest.approx(expected)

    def test_social_proof_sqrt(self):
        """attestation_count=8 -> sqrt(9) = 3.0 social factor (at cap)."""
        w = reputation_to_weight(10000, 0, 8)
        expected = 1.0 * 1.0 * 3.0
        assert w == pytest.approx(expected)

    def test_social_proof_cap_at_3x(self):
        """Very high attestation count should cap social factor at 3.0."""
        w = reputation_to_weight(10000, 0, 1000)
        expected = 1.0 * 1.0 * 3.0
        assert w == pytest.approx(expected)

    def test_half_reputation(self):
        """score=5000 -> rep_factor = 0.5."""
        w = reputation_to_weight(5000, 0, 0)
        assert w == pytest.approx(0.5)

    def test_combined_factors(self):
        """Verify all three factors combine multiplicatively."""
        score, completed, attestations = 7500, 3, 3
        rep = score / 10_000
        exp = min(math.log2(completed + 1) + 1, 4.0)
        soc = min(math.sqrt(attestations + 1), 3.0)
        expected = rep * exp * soc
        assert reputation_to_weight(score, completed, attestations) == pytest.approx(expected)


class TestDimensionWeights:
    """Verify the 30/40/30 dimension weights."""

    def test_weights_sum_to_one(self):
        weights = PublicGoodsEvaluator.DIMENSION_WEIGHTS
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_individual_weights(self):
        weights = PublicGoodsEvaluator.DIMENSION_WEIGHTS
        assert weights["legitimacy"] == pytest.approx(0.30)
        assert weights["impact"] == pytest.approx(0.40)
        assert weights["sustainability"] == pytest.approx(0.30)


class TestProjectScoring:
    """Test rank_projects() with known offline inputs."""

    def _make_evaluator(self):
        """Create an evaluator in offline mode (no web3)."""
        return PublicGoodsEvaluator(
            registry_address="0x0000000000000000000000000000000000000000",
            rpc_url="http://localhost:9999",  # unused
        )

    def test_single_project_single_evaluator(self):
        """A single project scored by a single evaluator with known reputation."""
        ev = self._make_evaluator()
        projects = [{"name": "TestDAO", "category": "test", "funding_requested": 10000}]
        evaluations = [
            {"evaluator_agent_id": 1, "project_name": "TestDAO",
             "legitimacy": 8, "impact": 9, "sustainability": 7},
        ]
        # Provide known reputation for agent 1
        reputations = {1: (8000, 5, 3)}

        results = ev.rank_projects(
            projects, evaluations, total_budget=10000,
            online=False, evaluator_reputations=reputations,
        )

        assert len(results) == 1
        sp = results[0]
        assert sp.rank == 1
        assert sp.name == "TestDAO"
        # With a single evaluator, weighted scores should equal raw scores
        assert sp.weighted_legitimacy == pytest.approx(8.0)
        assert sp.weighted_impact == pytest.approx(9.0)
        assert sp.weighted_sustainability == pytest.approx(7.0)
        # Composite = 0.3*8 + 0.4*9 + 0.3*7 = 2.4 + 3.6 + 2.1 = 8.1
        assert sp.composite_score == pytest.approx(8.1)

    def test_ranking_order(self):
        """Two projects: the one with higher composite score should rank first."""
        ev = self._make_evaluator()
        projects = [
            {"name": "Low", "category": "a", "funding_requested": 5000},
            {"name": "High", "category": "b", "funding_requested": 5000},
        ]
        evaluations = [
            {"evaluator_agent_id": 1, "project_name": "Low",
             "legitimacy": 3, "impact": 3, "sustainability": 3},
            {"evaluator_agent_id": 1, "project_name": "High",
             "legitimacy": 9, "impact": 9, "sustainability": 9},
        ]
        reputations = {1: (5000, 0, 0)}
        results = ev.rank_projects(
            projects, evaluations, total_budget=10000,
            online=False, evaluator_reputations=reputations,
        )
        assert results[0].name == "High"
        assert results[0].rank == 1
        assert results[1].name == "Low"
        assert results[1].rank == 2

    def test_no_evaluations_gives_minimum_scores(self):
        """A project with no evaluations should get minimum scores (1.0)."""
        ev = self._make_evaluator()
        projects = [{"name": "Unreviewed", "category": "x", "funding_requested": 1000}]
        results = ev.rank_projects(projects, [], total_budget=1000, online=False)
        assert len(results) == 1
        sp = results[0]
        assert sp.weighted_legitimacy == pytest.approx(1.0)
        assert sp.weighted_impact == pytest.approx(1.0)
        assert sp.weighted_sustainability == pytest.approx(1.0)
        assert sp.composite_score == pytest.approx(1.0)


class TestBudgetAllocation:
    """Test _allocate_budget with cap redistribution."""

    def test_allocation_respects_cap(self):
        """If a project requests less than its proportional share, excess is redistributed."""
        ev = PublicGoodsEvaluator(
            registry_address="0x0000000000000000000000000000000000000000",
        )
        projects = [
            {"name": "Small", "category": "a", "funding_requested": 1000},
            {"name": "Big", "category": "b", "funding_requested": 50000},
        ]
        evaluations = [
            {"evaluator_agent_id": 1, "project_name": "Small",
             "legitimacy": 10, "impact": 10, "sustainability": 10},
            {"evaluator_agent_id": 1, "project_name": "Big",
             "legitimacy": 10, "impact": 10, "sustainability": 10},
        ]
        reputations = {1: (5000, 0, 0)}
        results = ev.rank_projects(
            projects, evaluations, total_budget=10000,
            online=False, evaluator_reputations=reputations,
        )
        # Both have equal scores. With budget=10000 and equal composite:
        # Each would get 5000 proportionally, but Small caps at 1000.
        # Remaining 4000 goes to Big. Big total = 5000+4000 = 9000.
        small = [r for r in results if r.name == "Small"][0]
        big = [r for r in results if r.name == "Big"][0]
        assert small.recommended_allocation == pytest.approx(1000.0)
        assert big.recommended_allocation == pytest.approx(9000.0)

    def test_total_allocation_does_not_exceed_budget(self):
        """Sum of all allocations should not exceed total budget."""
        ev = PublicGoodsEvaluator(
            registry_address="0x0000000000000000000000000000000000000000",
        )
        projects = [
            {"name": f"P{i}", "category": "c", "funding_requested": 20000}
            for i in range(5)
        ]
        evaluations = [
            {"evaluator_agent_id": 1, "project_name": f"P{i}",
             "legitimacy": 5 + i, "impact": 6 + i, "sustainability": 4 + i}
            for i in range(5)
        ]
        reputations = {1: (5000, 0, 0)}
        results = ev.rank_projects(
            projects, evaluations, total_budget=50000,
            online=False, evaluator_reputations=reputations,
        )
        total_allocated = sum(r.recommended_allocation for r in results)
        assert total_allocated <= 50000 + 0.01  # floating point tolerance


# ---------------------------------------------------------------------------
# 2. ens_resolver.py tests
# ---------------------------------------------------------------------------

from src.ens_resolver import (
    _keccak256,
    namehash,
    ENSVerificationError,
    _compute_verification_level,
    _encode_bytes32,
    _decode_address,
    _decode_string,
)


class TestKeccak256:
    """Test the _keccak256() implementation."""

    def test_empty_input(self):
        """keccak256 of empty bytes should produce a known 32-byte hash."""
        h = _keccak256(b"")
        assert len(h) == 32

    def test_deterministic(self):
        """Same input should always produce the same output."""
        h1 = _keccak256(b"hello")
        h2 = _keccak256(b"hello")
        assert h1 == h2

    def test_different_inputs_differ(self):
        """Different inputs should produce different hashes."""
        h1 = _keccak256(b"hello")
        h2 = _keccak256(b"world")
        assert h1 != h2

    def test_output_is_32_bytes(self):
        """Output should always be exactly 32 bytes."""
        for data in [b"", b"a", b"test data" * 100]:
            assert len(_keccak256(data)) == 32


class TestNamehash:
    """Test EIP-137 namehash computation."""

    def test_empty_name_returns_zero_bytes(self):
        """namehash('') should be 32 zero bytes per EIP-137."""
        result = namehash("")
        assert result == b"\x00" * 32

    def test_namehash_eth(self):
        """namehash('eth') = keccak256(namehash('') + keccak256('eth'))."""
        expected = _keccak256(b"\x00" * 32 + _keccak256(b"eth"))
        assert namehash("eth") == expected

    def test_namehash_foo_eth(self):
        """namehash('foo.eth') = keccak256(namehash('eth') + keccak256('foo'))."""
        eth_node = _keccak256(b"\x00" * 32 + _keccak256(b"eth"))
        expected = _keccak256(eth_node + _keccak256(b"foo"))
        assert namehash("foo.eth") == expected

    def test_namehash_is_bytes(self):
        """Namehash should return bytes, not hex string."""
        assert isinstance(namehash("test.eth"), bytes)
        assert len(namehash("test.eth")) == 32


class TestENSVerificationError:
    """Test the ENSVerificationError exception class."""

    def test_raises_with_message(self):
        with pytest.raises(ENSVerificationError, match="test error"):
            raise ENSVerificationError("test error")

    def test_proof_attribute_none_by_default(self):
        try:
            raise ENSVerificationError("msg")
        except ENSVerificationError as e:
            assert e.proof is None

    def test_proof_attribute_set(self):
        proof = {"verified": False, "block_number": 12345}
        try:
            raise ENSVerificationError("msg", proof=proof)
        except ENSVerificationError as e:
            assert e.proof == proof
            assert e.proof["block_number"] == 12345

    def test_inherits_from_exception(self):
        assert issubclass(ENSVerificationError, Exception)


class TestComputeVerificationLevel:
    """Test _compute_verification_level() logic."""

    def test_level_none_when_no_resolved_address(self):
        identity = {"resolved_address": None, "reverse_verified": False}
        assert _compute_verification_level(identity, ownership_verified=False) == "none"

    def test_level_full_with_forward_and_reverse(self):
        identity = {"resolved_address": "0xabc", "reverse_verified": True}
        assert _compute_verification_level(identity, ownership_verified=True) == "full"

    def test_level_forward_when_no_reverse(self):
        identity = {"resolved_address": "0xabc", "reverse_verified": False}
        assert _compute_verification_level(identity, ownership_verified=True) == "forward"

    def test_level_partial_when_resolved_but_wrong_address(self):
        identity = {"resolved_address": "0xother", "reverse_verified": False}
        assert _compute_verification_level(identity, ownership_verified=False) == "partial"

    def test_level_partial_even_with_reverse(self):
        """If forward doesn't match but address resolves, it's partial."""
        identity = {"resolved_address": "0xother", "reverse_verified": True}
        assert _compute_verification_level(identity, ownership_verified=False) == "partial"


class TestEncodeBytes32:
    """Test the _encode_bytes32 helper."""

    def test_zero_bytes(self):
        result = _encode_bytes32(b"\x00" * 32)
        assert result == "0" * 64

    def test_short_input_padded(self):
        result = _encode_bytes32(b"\x01")
        assert len(result) == 64
        assert result.startswith("01")

    def test_full_32_bytes(self):
        data = bytes(range(32))
        result = _encode_bytes32(data)
        assert len(result) == 64
        assert result == data.hex()[:64]


class TestDecodeAddress:
    """Test the _decode_address helper."""

    def test_zero_address_returns_none(self):
        result = _decode_address("0x" + "0" * 64)
        assert result is None

    def test_valid_address(self):
        # Last 40 hex chars are the address
        hex_result = "0x" + "0" * 24 + "d8da6bf26964af9d7eed9e03e53415d37aa96045"
        result = _decode_address(hex_result)
        assert result is not None
        assert result.lower() == "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"


# ---------------------------------------------------------------------------
# 3. olas_integration.py tests
# ---------------------------------------------------------------------------

from src.olas_integration import (
    OlasCompatibleAgent,
    OlasServiceComponent,
    ServiceOffering,
    ServiceRequest,
    ServiceState,
    RequestStatus,
    OlasOnChainClient,
    KNOWN_TX_HASHES,
)


class TestOlasServiceComponent:
    """Test OlasServiceComponent dataclass."""

    def test_create_component(self):
        comp = OlasServiceComponent(
            component_id=1,
            agent_id=1,
            name="TestAgent",
            description="A test agent",
            capabilities=["analysis", "audit"],
        )
        assert comp.component_id == 1
        assert comp.name == "TestAgent"
        assert comp.version == "1.0.0"
        assert comp.agent_instances_required == 1
        assert len(comp.capabilities) == 2

    def test_default_fields(self):
        comp = OlasServiceComponent(
            component_id=1, agent_id=1, name="X",
            description="Y", capabilities=[],
        )
        assert comp.package_hash == ""
        assert comp.config_hash == ""
        assert comp.dependencies == []
        assert comp.min_staking_deposit_wei == 0


class TestOlasCompatibleAgentOffline:
    """Test OlasCompatibleAgent methods that don't require network."""

    def test_init_with_capabilities(self):
        agent = OlasCompatibleAgent(
            trustagent_id=1,
            name="TestAgent",
            capabilities=["analysis", "verification"],
        )
        assert agent.trustagent_id == 1
        assert agent.name == "TestAgent"
        assert agent.state == ServiceState.PRE_REGISTRATION
        # Should have created service offerings for the 2 capabilities
        assert len(agent._service_offerings) == 2
        service_ids = [s.service_id for s in agent._service_offerings]
        assert "data-analysis" in service_ids
        assert "identity-verification" in service_ids

    def test_init_no_capabilities(self):
        agent = OlasCompatibleAgent(trustagent_id=1, name="Bare")
        assert agent._service_offerings == []

    def test_get_service_offerings_format(self):
        agent = OlasCompatibleAgent(
            trustagent_id=1, name="A", capabilities=["analysis"],
        )
        offerings = agent.get_service_offerings()
        assert len(offerings) == 1
        o = offerings[0]
        assert "service_id" in o
        assert "pricing" in o
        assert "fee_wei" in o["pricing"]
        assert "provider" in o
        assert o["provider"]["trustagent_id"] == 1

    def test_execute_service_unknown_returns_basic(self):
        """_execute_service with unknown service_id returns basic mode."""
        agent = OlasCompatibleAgent(trustagent_id=1, name="A")
        fake_service = ServiceOffering(
            service_id="nonexistent",
            name="Fake",
            description="",
            capability_required="x",
            fee_wei=100,
        )
        result = agent._execute_service(fake_service, {})
        assert result["status"] == "completed"
        assert result["execution_mode"] == "basic"

    def test_handle_request_unknown_service(self):
        """Requesting an unknown service should return an error."""
        agent = OlasCompatibleAgent(trustagent_id=1, name="A", capabilities=["analysis"])
        resp = agent.handle_request({
            "service_id": "nonexistent",
            "payload": {},
            "requester": "0x123",
            "max_fee_wei": 1000000,
        })
        assert resp["status"] == "error"
        assert "not offered" in resp["error"]

    def test_handle_request_insufficient_fee(self):
        """Offering a fee below the required amount should return an error."""
        agent = OlasCompatibleAgent(trustagent_id=1, name="A", capabilities=["analysis"])
        resp = agent.handle_request({
            "service_id": "data-analysis",
            "payload": {},
            "requester": "0x123",
            "max_fee_wei": 1,  # way too low
        })
        assert resp["status"] == "error"
        assert "Insufficient fee" in resp["error"]


class TestOlasOnChainClientHelpers:
    """Test pure encoding/decoding helpers on OlasOnChainClient."""

    def test_encode_uint256(self):
        client = OlasOnChainClient()
        assert client._encode_uint256(0) == "0" * 64
        assert client._encode_uint256(1) == "0" * 63 + "1"
        assert client._encode_uint256(255) == "0" * 62 + "ff"

    def test_decode_uint256(self):
        client = OlasOnChainClient()
        hex_data = "0" * 63 + "a"  # = 10
        assert client._decode_uint256(hex_data, 0) == 10

    def test_decode_address(self):
        client = OlasOnChainClient()
        # Address is in the last 20 bytes (40 hex chars) of a 32-byte word
        hex_data = "0" * 24 + "abcdef1234567890abcdef1234567890abcdef12"
        result = client._decode_address(hex_data, 0)
        assert result == "0xabcdef1234567890abcdef1234567890abcdef12"


class TestKnownTxHashes:
    """Test the KNOWN_TX_HASHES constant."""

    def test_hashes_exist(self):
        assert len(KNOWN_TX_HASHES) > 0

    def test_hashes_are_valid_hex(self):
        for agent_id, tx_hash in KNOWN_TX_HASHES.items():
            assert tx_hash.startswith("0x"), f"TX hash for agent {agent_id} missing 0x prefix"
            assert len(tx_hash) == 66, f"TX hash for agent {agent_id} wrong length"
            # Verify it's valid hex after 0x
            int(tx_hash[2:], 16)


# ---------------------------------------------------------------------------
# 4. mech_server.py tests
# ---------------------------------------------------------------------------

# mech_server.py imports reputation_evaluation which is not available
# in test environment, so we test its constants and data structures
# by importing selectively and using mock-based approach.

from src.mech_server import (
    REAL_TX_HASHES,
    RequestStatus as MechRequestStatus,
    MechRequest,
    FEE_WEI,
    REGISTRY_ADDRESS,
    TOOL_NAME,
)


class TestRealTxHashes:
    """Test the REAL_TX_HASHES list from mech_server."""

    def test_list_has_entries(self):
        assert len(REAL_TX_HASHES) >= 6

    def test_all_valid_hex(self):
        for i, tx in enumerate(REAL_TX_HASHES):
            assert tx.startswith("0x"), f"Hash at index {i} missing 0x prefix"
            assert len(tx) == 66, f"Hash at index {i} has wrong length: {len(tx)}"
            int(tx[2:], 16)  # should not raise

    def test_all_unique(self):
        assert len(set(REAL_TX_HASHES)) == len(REAL_TX_HASHES)


class TestMechRequestDataclass:
    """Test MechRequest data structure."""

    def test_create_request(self):
        req = MechRequest(
            request_id="test-1",
            sender="0xabc",
            prompt="evaluate agent 1",
            tool="reputation_evaluation",
            fee_wei=100000,
            timestamp=1000.0,
        )
        assert req.request_id == "test-1"
        assert req.status == MechRequestStatus.PENDING
        assert req.result is None
        assert req.delivery_time_ms == 0.0
        assert req.tx_hash == ""

    def test_to_dict(self):
        req = MechRequest(
            request_id="test-2",
            sender="0xdef",
            prompt="test",
            tool="reputation_evaluation",
            fee_wei=50000,
            timestamp=2000.0,
            status=MechRequestStatus.DELIVERED,
            result='{"score": 85}',
            delivery_time_ms=42.5,
            tx_hash="0xabc123",
        )
        d = req.to_dict()
        assert d["request_id"] == "test-2"
        assert d["status"] == "delivered"
        assert d["result"] == '{"score": 85}'
        assert d["delivery_time_ms"] == 42.5
        assert d["tx_hash"] == "0xabc123"
        assert d["fee_wei"] == 50000


class TestMechServerConstants:
    """Test mech_server module-level constants."""

    def test_fee_wei_positive(self):
        assert FEE_WEI > 0

    def test_registry_address_format(self):
        assert REGISTRY_ADDRESS.startswith("0x")
        assert len(REGISTRY_ADDRESS) == 42

    def test_tool_name(self):
        assert TOOL_NAME == "reputation_evaluation"


class TestMechRequestStatusEnum:
    """Test the RequestStatus enum from mech_server."""

    def test_all_statuses_exist(self):
        assert MechRequestStatus.PENDING.value == "pending"
        assert MechRequestStatus.PROCESSING.value == "processing"
        assert MechRequestStatus.DELIVERED.value == "delivered"
        assert MechRequestStatus.FAILED.value == "failed"

    def test_status_count(self):
        assert len(MechRequestStatus) == 4
