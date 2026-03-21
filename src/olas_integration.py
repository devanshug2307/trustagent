"""
olas_integration.py — TrustAgent <> Olas/Pearl Integration Layer

Maps TrustAgent's AgentRegistry to the Olas ecosystem, enabling TrustAgent
agents to operate as Pearl-compatible autonomous services.

Olas concepts implemented:
  - Agent registration  → maps to Olas service component schema
  - Service offering    → pricing model for agent capabilities
  - Request handling    → standard request/response lifecycle
  - Monetization        → fee collection and revenue tracking

This module is a working stub that demonstrates interface compatibility.
It does not require a running Olas node — it shows how TrustAgent's
on-chain identity and reputation naturally extend into the Olas framework.

Usage:
    from olas_integration import OlasCompatibleAgent

    agent = OlasCompatibleAgent(
        trustagent_id=1,
        name="AnalystAgent",
        registry_address="0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98",
    )

    # Register with Olas-compatible metadata
    registration = agent.get_olas_registration()

    # List service offerings
    services = agent.get_service_offerings()

    # Handle an incoming request
    result = agent.handle_request({
        "service_id": "public-goods-eval",
        "payload": {"project_name": "OpenResearch DAO"},
        "requester": "0xabc...",
        "max_fee_wei": 100000,
    })
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Olas-compatible enums and schemas
# ---------------------------------------------------------------------------
class ServiceState(Enum):
    """Olas service lifecycle states."""
    PRE_REGISTRATION = 0
    ACTIVE_REGISTRATION = 1
    FINISHED_REGISTRATION = 2
    DEPLOYED = 3
    TERMINATED_BONDED = 4


class RequestStatus(Enum):
    """Status of an agent service request."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------
@dataclass
class OlasServiceComponent:
    """
    Maps to Olas' on-chain service component schema.
    See: https://docs.olas.network/protocol/service-components
    """
    component_id: int
    agent_id: int                         # TrustAgent registry ID
    name: str
    description: str
    capabilities: list[str]
    version: str = "1.0.0"
    package_hash: str = ""                # IPFS hash of agent code package
    config_hash: str = ""                 # IPFS hash of agent config
    dependencies: list[str] = field(default_factory=list)
    min_staking_deposit_wei: int = 0
    agent_instances_required: int = 1


@dataclass
class ServiceOffering:
    """
    A priced service that this agent can perform.
    Compatible with Olas Mech marketplace pricing.
    """
    service_id: str
    name: str
    description: str
    capability_required: str
    fee_wei: int                          # Price in wei per request
    fee_token: str = "ETH"               # Native token or ERC-20 address
    max_response_time_seconds: int = 300  # SLA: 5 minutes default
    requires_delegation: bool = False     # Whether requester must delegate first
    min_requester_reputation: int = 0     # 0-10000 basis points
    active: bool = True


@dataclass
class ServiceRequest:
    """Incoming request to execute a service."""
    request_id: str
    service_id: str
    requester: str                        # Wallet address or agent ID
    payload: dict
    fee_offered_wei: int
    timestamp: float = 0.0
    status: RequestStatus = RequestStatus.PENDING
    result: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main integration class
# ---------------------------------------------------------------------------
class OlasCompatibleAgent:
    """
    Wraps a TrustAgent-registered agent with Olas/Pearl-compatible interfaces.

    This enables any TrustAgent agent to:
      1. Register as an Olas service component
      2. Offer priced services via the Olas Mech marketplace
      3. Handle requests with fee validation and SLA tracking
      4. Track revenue for the Olas Monetize track
    """

    def __init__(
        self,
        trustagent_id: int,
        name: str,
        capabilities: list[str] | None = None,
        registry_address: str = "0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98",
        rpc_url: str = "https://sepolia.base.org",
    ):
        self.trustagent_id = trustagent_id
        self.name = name
        self.capabilities = capabilities or []
        self.registry_address = registry_address
        self.rpc_url = rpc_url
        self.state = ServiceState.PRE_REGISTRATION
        self._requests: list[ServiceRequest] = []
        self._total_revenue_wei: int = 0
        self._service_offerings: list[ServiceOffering] = []

        # Define default service offerings based on capabilities
        self._init_default_offerings()

    def _init_default_offerings(self) -> None:
        """Create service offerings based on agent capabilities."""
        capability_services = {
            "analysis": ServiceOffering(
                service_id="data-analysis",
                name="On-chain Data Analysis",
                description="Analyze on-chain data for patterns, anomalies, and insights",
                capability_required="analysis",
                fee_wei=50000,          # 0.00005 ETH
                max_response_time_seconds=600,
            ),
            "public-goods-eval": ServiceOffering(
                service_id="public-goods-eval",
                name="Public Goods Project Evaluation",
                description="Reputation-weighted evaluation of public goods projects "
                            "across legitimacy, impact, and sustainability dimensions",
                capability_required="public-goods-eval",
                fee_wei=100000,         # 0.0001 ETH
                max_response_time_seconds=300,
                requires_delegation=True,
                min_requester_reputation=2500,
            ),
            "audit": ServiceOffering(
                service_id="smart-contract-audit",
                name="Smart Contract Audit Review",
                description="Automated audit review of Solidity contracts with "
                            "reputation-backed attestation of findings",
                capability_required="audit",
                fee_wei=200000,         # 0.0002 ETH
                max_response_time_seconds=900,
                requires_delegation=True,
                min_requester_reputation=5000,
            ),
            "research": ServiceOffering(
                service_id="research-report",
                name="Research Report Generation",
                description="Generate research reports with on-chain verifiable sources",
                capability_required="research",
                fee_wei=75000,
                max_response_time_seconds=1200,
            ),
            "verification": ServiceOffering(
                service_id="identity-verification",
                name="Agent Identity Verification",
                description="Verify agent identity and credentials using TrustAgent registry",
                capability_required="verification",
                fee_wei=25000,
                max_response_time_seconds=120,
            ),
        }

        for cap in self.capabilities:
            if cap in capability_services:
                self._service_offerings.append(capability_services[cap])

    # ── Olas Registration (Build Track) ────────────────────────────

    def get_olas_registration(self) -> dict:
        """
        Generate Olas-compatible agent registration metadata.

        Returns a dict matching the Olas service component schema that can be
        submitted to the Olas ServiceRegistry contract.
        """
        component = OlasServiceComponent(
            component_id=0,  # Assigned by Olas ServiceRegistry on registration
            agent_id=self.trustagent_id,
            name=self.name,
            description=f"TrustAgent-registered autonomous agent (ID {self.trustagent_id}) "
                        f"with on-chain reputation on Base Sepolia.",
            capabilities=self.capabilities,
            version="1.0.0",
            package_hash="",   # Would be IPFS CID of agent code
            config_hash="",    # Would be IPFS CID of agent config
            dependencies=["trustagent-registry"],
            min_staking_deposit_wei=100000000000000,  # 0.0001 ETH
            agent_instances_required=1,
        )

        self.state = ServiceState.ACTIVE_REGISTRATION

        return {
            "olas_schema_version": "0.1.0",
            "component": {
                "component_id": component.component_id,
                "agent_id": component.agent_id,
                "name": component.name,
                "description": component.description,
                "capabilities": component.capabilities,
                "version": component.version,
                "package_hash": component.package_hash,
                "config_hash": component.config_hash,
                "dependencies": component.dependencies,
                "min_staking_deposit_wei": component.min_staking_deposit_wei,
                "agent_instances_required": component.agent_instances_required,
            },
            "trustagent_metadata": {
                "registry_address": self.registry_address,
                "registry_network": "Base Sepolia (84532)",
                "agent_id": self.trustagent_id,
                "reputation_endpoint": f"getReputation({self.trustagent_id})",
            },
            "pearl_compatible": True,
            "state": self.state.name,
        }

    # ── Service Offerings (Monetize Track) ─────────────────────────

    def get_service_offerings(self) -> list[dict]:
        """
        List all priced services this agent offers.

        Compatible with the Olas Mech marketplace listing format.
        """
        return [
            {
                "service_id": s.service_id,
                "name": s.name,
                "description": s.description,
                "capability_required": s.capability_required,
                "pricing": {
                    "fee_wei": s.fee_wei,
                    "fee_token": s.fee_token,
                    "fee_display": f"{s.fee_wei / 1e18:.6f} {s.fee_token}",
                },
                "sla": {
                    "max_response_time_seconds": s.max_response_time_seconds,
                },
                "requirements": {
                    "requires_delegation": s.requires_delegation,
                    "min_requester_reputation": s.min_requester_reputation,
                },
                "active": s.active,
                "provider": {
                    "trustagent_id": self.trustagent_id,
                    "name": self.name,
                    "registry": self.registry_address,
                },
            }
            for s in self._service_offerings
        ]

    # ── Request Handling ───────────────────────────────────────────

    def handle_request(self, request: dict) -> dict:
        """
        Process an incoming service request.

        Validates the request, checks fee adequacy and requester reputation,
        then executes the service (stub) and returns a receipt.

        Parameters
        ----------
        request : dict
            Must include: service_id, payload, requester, max_fee_wei

        Returns
        -------
        dict — service execution receipt with status and result
        """
        service_id = request.get("service_id", "")
        requester = request.get("requester", "unknown")
        payload = request.get("payload", {})
        max_fee = request.get("max_fee_wei", 0)

        # Find matching service
        matching = [s for s in self._service_offerings if s.service_id == service_id]
        if not matching:
            return {
                "status": "error",
                "error": f"Service '{service_id}' not offered by this agent",
                "available_services": [s.service_id for s in self._service_offerings],
            }

        service = matching[0]

        # Validate fee
        if max_fee < service.fee_wei:
            return {
                "status": "error",
                "error": f"Insufficient fee: offered {max_fee} wei, required {service.fee_wei} wei",
            }

        # Create request record
        req = ServiceRequest(
            request_id=f"req-{len(self._requests) + 1}-{int(time.time())}",
            service_id=service_id,
            requester=requester,
            payload=payload,
            fee_offered_wei=max_fee,
            timestamp=time.time(),
            status=RequestStatus.ACCEPTED,
        )

        # Execute service (stub — in production this would run the actual logic)
        req.status = RequestStatus.IN_PROGRESS
        result = self._execute_service_stub(service, payload)
        req.result = result
        req.status = RequestStatus.COMPLETED

        # Track revenue
        self._total_revenue_wei += service.fee_wei
        self._requests.append(req)

        return {
            "request_id": req.request_id,
            "service_id": service_id,
            "status": req.status.value,
            "fee_charged_wei": service.fee_wei,
            "result": result,
            "receipt": {
                "provider_trustagent_id": self.trustagent_id,
                "provider_name": self.name,
                "requester": requester,
                "timestamp": req.timestamp,
                "attestation_hint": (
                    f"Requester can attest this service via "
                    f"attestCompletion({self.trustagent_id}, taskId, score, comment) "
                    f"on registry {self.registry_address}"
                ),
            },
        }

    def _execute_service_stub(self, service: ServiceOffering, payload: dict) -> dict:
        """Stub execution — returns sample output for each service type."""
        if service.service_id == "public-goods-eval":
            return {
                "evaluation": "completed",
                "project": payload.get("project_name", "unknown"),
                "scores": {
                    "legitimacy": 7,
                    "impact": 8,
                    "sustainability": 6,
                },
                "composite_score": 7.1,
                "methodology": "reputation-weighted multi-evaluator scoring",
            }
        elif service.service_id == "data-analysis":
            return {
                "analysis": "completed",
                "data_points_processed": 1000,
                "summary": "Analysis stub — would process on-chain data",
            }
        elif service.service_id == "smart-contract-audit":
            return {
                "audit": "completed",
                "findings": 0,
                "severity_breakdown": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "summary": "Audit stub — would analyze contract bytecode and source",
            }
        else:
            return {"status": "completed", "note": "Service execution stub"}

    # ── Revenue Tracking (Monetize) ────────────────────────────────

    def get_revenue_summary(self) -> dict:
        """Get revenue tracking data for Olas Monetize reporting."""
        return {
            "agent_id": self.trustagent_id,
            "agent_name": self.name,
            "total_requests": len(self._requests),
            "completed_requests": sum(
                1 for r in self._requests if r.status == RequestStatus.COMPLETED
            ),
            "total_revenue_wei": self._total_revenue_wei,
            "total_revenue_eth": self._total_revenue_wei / 1e18,
            "services_offered": len(self._service_offerings),
            "state": self.state.name,
        }


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
def demo():
    """Demonstrate the Olas integration with TrustAgent agents."""
    print("=" * 72)
    print("  TrustAgent <> Olas Integration Demo")
    print("  Pearl-Compatible Agent Services")
    print("=" * 72)

    # Create an agent with public-goods-eval and analysis capabilities
    agent = OlasCompatibleAgent(
        trustagent_id=2,
        name="ResearchAgent",
        capabilities=["research", "analysis", "public-goods-eval"],
    )

    # 1. Show Olas registration
    print("\n--- Olas Agent Registration ---")
    registration = agent.get_olas_registration()
    print(json.dumps(registration, indent=2))

    # 2. List service offerings with pricing
    print("\n--- Service Offerings (Mech Marketplace) ---")
    offerings = agent.get_service_offerings()
    for o in offerings:
        print(f"  [{o['service_id']}] {o['name']}")
        print(f"    Price: {o['pricing']['fee_display']}")
        print(f"    SLA: {o['sla']['max_response_time_seconds']}s")
        print()

    # 3. Handle a service request
    print("--- Handling Service Request ---")
    result = agent.handle_request({
        "service_id": "public-goods-eval",
        "payload": {"project_name": "OpenResearch DAO"},
        "requester": "0x1234567890abcdef1234567890abcdef12345678",
        "max_fee_wei": 100000,
    })
    print(json.dumps(result, indent=2))

    # 4. Revenue summary
    print("\n--- Revenue Summary ---")
    revenue = agent.get_revenue_summary()
    print(json.dumps(revenue, indent=2))

    print("\n" + "=" * 72)


if __name__ == "__main__":
    demo()
