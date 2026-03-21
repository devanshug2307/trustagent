// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title AgentRegistry
 * @notice Onchain registry for AI agent identity, reputation, and discovery.
 * @dev Implements ERC-8004 compatible agent identity with reputation scoring,
 *      capability-based discovery, and delegation protocol.
 *
 * Built for The Synthesis Hackathon — Protocol Labs ERC-8004 + ENS tracks.
 */
contract AgentRegistry is Ownable {
    struct Agent {
        uint256 id;
        address wallet;
        string name;
        string ensName;
        string[] capabilities;
        uint256 registeredAt;
        uint256 reputationScore;    // 0-10000 (basis points, so 10000 = 100%)
        uint256 tasksCompleted;
        uint256 tasksFailed;
        bool active;
    }

    struct Attestation {
        uint256 fromAgentId;
        uint256 toAgentId;
        uint256 taskId;
        uint8 score;    // 1-10
        string comment;
        uint256 timestamp;
    }

    struct Delegation {
        uint256 fromAgentId;
        uint256 toAgentId;
        bytes32[] permissions;
        uint256 expiry;
        bool revoked;
        uint256 createdAt;
    }

    uint256 public nextAgentId = 1; // Start at 1 so 0 means "not registered"
    uint256 public nextAttestationId;
    uint256 public nextDelegationId;

    mapping(uint256 => Agent) public agents;
    mapping(address => uint256) public walletToAgentId;
    mapping(uint256 => Attestation) public attestations;
    mapping(uint256 => Delegation) public delegations;
    mapping(uint256 => uint256[]) public agentAttestations;    // agentId => attestation IDs
    mapping(uint256 => uint256[]) public agentDelegations;     // agentId => delegation IDs

    // Capability index for discovery
    mapping(string => uint256[]) public capabilityIndex;       // capability => agent IDs

    // --- Events ---
    event AgentRegistered(uint256 indexed agentId, address indexed wallet, string name);
    event AttestationCreated(uint256 indexed attestationId, uint256 indexed fromAgent, uint256 indexed toAgent, uint8 score);
    event DelegationCreated(uint256 indexed delegationId, uint256 indexed fromAgent, uint256 indexed toAgent, uint256 expiry);
    event DelegationRevoked(uint256 indexed delegationId);
    event ReputationUpdated(uint256 indexed agentId, uint256 newScore);

    constructor() Ownable(msg.sender) {}

    /**
     * @notice Register a new agent with verifiable onchain identity
     */
    function registerAgent(
        string calldata name,
        string calldata ensName,
        string[] calldata capabilities
    ) external returns (uint256 agentId) {
        require(walletToAgentId[msg.sender] == 0 || !agents[walletToAgentId[msg.sender]].active,
            "Already registered");

        agentId = nextAgentId++;
        agents[agentId] = Agent({
            id: agentId,
            wallet: msg.sender,
            name: name,
            ensName: ensName,
            capabilities: capabilities,
            registeredAt: block.timestamp,
            reputationScore: 5000, // Start at 50% (neutral)
            tasksCompleted: 0,
            tasksFailed: 0,
            active: true
        });

        walletToAgentId[msg.sender] = agentId;

        // Index capabilities for discovery
        for (uint256 i = 0; i < capabilities.length; i++) {
            capabilityIndex[capabilities[i]].push(agentId);
        }

        emit AgentRegistered(agentId, msg.sender, name);
    }

    /**
     * @notice Attest to another agent's task completion (builds reputation)
     */
    function attestCompletion(
        uint256 toAgentId,
        uint256 taskId,
        uint8 score,
        string calldata comment
    ) external returns (uint256 attestationId) {
        uint256 fromAgentId = walletToAgentId[msg.sender];
        require(agents[fromAgentId].active, "Attester not registered");
        require(agents[toAgentId].active, "Target agent not registered");
        require(fromAgentId != toAgentId, "Cannot self-attest");
        require(score >= 1 && score <= 10, "Score must be 1-10");

        attestationId = nextAttestationId++;
        attestations[attestationId] = Attestation({
            fromAgentId: fromAgentId,
            toAgentId: toAgentId,
            taskId: taskId,
            score: score,
            comment: comment,
            timestamp: block.timestamp
        });

        agentAttestations[toAgentId].push(attestationId);

        // Update reputation
        if (score >= 5) {
            agents[toAgentId].tasksCompleted++;
        } else {
            agents[toAgentId].tasksFailed++;
        }
        _updateReputation(toAgentId);

        emit AttestationCreated(attestationId, fromAgentId, toAgentId, score);
    }

    /**
     * @notice Delegate scoped permissions to another agent
     */
    function delegate(
        uint256 toAgentId,
        bytes32[] calldata permissions,
        uint256 duration
    ) external returns (uint256 delegationId) {
        uint256 fromAgentId = walletToAgentId[msg.sender];
        require(agents[fromAgentId].active, "Delegator not registered");
        require(agents[toAgentId].active, "Delegatee not registered");

        delegationId = nextDelegationId++;
        delegations[delegationId] = Delegation({
            fromAgentId: fromAgentId,
            toAgentId: toAgentId,
            permissions: permissions,
            expiry: block.timestamp + duration,
            revoked: false,
            createdAt: block.timestamp
        });

        agentDelegations[toAgentId].push(delegationId);
        emit DelegationCreated(delegationId, fromAgentId, toAgentId, block.timestamp + duration);
    }

    /**
     * @notice Revoke a delegation
     */
    function revokeDelegation(uint256 delegationId) external {
        Delegation storage d = delegations[delegationId];
        uint256 fromAgentId = walletToAgentId[msg.sender];
        require(d.fromAgentId == fromAgentId, "Not delegator");
        require(!d.revoked, "Already revoked");
        d.revoked = true;
        emit DelegationRevoked(delegationId);
    }

    /**
     * @notice Check if a delegation is active
     */
    function isDelegationActive(uint256 delegationId) public view returns (bool) {
        Delegation storage d = delegations[delegationId];
        return !d.revoked && block.timestamp < d.expiry;
    }

    /**
     * @notice Get agent reputation score
     */
    function getReputation(uint256 agentId) external view returns (
        uint256 score,
        uint256 completed,
        uint256 failed,
        uint256 totalAttestations
    ) {
        Agent storage a = agents[agentId];
        return (a.reputationScore, a.tasksCompleted, a.tasksFailed, agentAttestations[agentId].length);
    }

    /**
     * @notice Discover agents by capability
     */
    function discoverByCapability(string calldata capability) external view returns (uint256[] memory) {
        return capabilityIndex[capability];
    }

    /**
     * @notice Get total registered agents
     */
    function totalAgents() external view returns (uint256) {
        return nextAgentId;
    }

    // --- Internal ---

    function _updateReputation(uint256 agentId) internal {
        Agent storage a = agents[agentId];
        uint256 total = a.tasksCompleted + a.tasksFailed;
        if (total == 0) return;
        // Reputation = (completed / total) * 10000
        a.reputationScore = (a.tasksCompleted * 10000) / total;
        emit ReputationUpdated(agentId, a.reputationScore);
    }
}
