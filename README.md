# TrustAgent: Multi-Agent Identity & Coordination Network

> How does one agent know it can trust another? TrustAgent answers that question.

**Built for [The Synthesis Hackathon 2026](https://synthesis.md)**

**Live Dashboard:** [devanshug2307.github.io/trustagent](https://devanshug2307.github.io/trustagent/)

---

## Problem

As AI agents proliferate, trust becomes the bottleneck. There's no standard way for agents to prove who they are, verify what they can do, or enforce agreements with each other. Without trust infrastructure, agent-to-agent commerce can't scale.

## Solution

TrustAgent builds the trust layer for autonomous agents:

1. **Verifiable Identity (ERC-8004)** — Agents register onchain with verifiable credentials
2. **Reputation System** — Track record of completed tasks, reliability scores
3. **Delegation Framework** — Scoped permissions that agents grant to each other
4. **Agent Discovery** — Find and evaluate agents by capability and reputation
5. **ENS Integration** — Real on-chain ENS resolution (forward + reverse) makes names the primary identifier, not an afterthought

## Architecture

```
┌─────────────────────────────────────────────┐
│              TRUSTAGENT                      │
├─────────────────────────────────────────────┤
│                                              │
│  ┌──────────┐ ┌───────────┐ ┌────────────┐ │
│  │ Identity  │ │ Reputation│ │ Discovery  │ │
│  │ (ERC-8004)│ │ System    │ │ & Matching │ │
│  │ + ENS     │ │           │ │            │ │
│  └─────┬─────┘ └─────┬─────┘ └─────┬──────┘ │
│        │             │             │         │
│        ▼             ▼             ▼         │
│  ┌─────────────────────────────────────────┐ │
│  │       AgentRegistry Contract (Base)      │ │
│  │  register() | attest() | getReputation() │ │
│  │  delegate() | discover() | resolve()     │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

## Key Features

### ERC-8004 Agent Identity
Every agent gets a verifiable onchain identity with:
- Unique agent ID tied to wallet address
- Capability declarations (what the agent can do)
- Registration timestamp (provenance)
- ENS name for human-readable addressing

### Reputation Scoring
Agents build reputation through:
- Task completion attestations from other agents
- Success/failure ratio tracking
- Stake-weighted credibility
- Time-decayed scoring (recent performance matters more)

### Agent Discovery
Find the right agent for any task:
- Search by capability tags
- Filter by minimum reputation score
- Sort by price, speed, or reliability
- ENS-native: `portfolio-analyzer.trustagent.eth`

### Delegation Protocol
Scoped permissions between agents:
- Time-limited delegations (expire automatically)
- Capability-scoped (only specific actions allowed)
- Revocable at any time
- Onchain audit trail

## Smart Contract

### AgentRegistry.sol
```solidity
// Core functions
function registerAgent(string name, string[] capabilities) → agentId
function attestCompletion(uint256 agentId, uint256 taskId, uint8 score)
function getReputation(uint256 agentId) → (score, tasksCompleted, tasksFailed)
function discoverAgents(string capability, uint256 minReputation) → Agent[]
function delegate(uint256 toAgentId, bytes32[] permissions, uint256 expiry)
```

## Multi-Agent Onchain Demo

The `scripts/multi-agent-demo.cjs` script demonstrates the full multi-agent lifecycle on Base Sepolia:

1. **Fund two fresh wallets** from the deployer
2. **Register ResearchAgent** (capabilities: research, data-analysis, public-goods-eval)
3. **Register AuditorAgent** (capabilities: audit, verification, public-goods-eval)
4. **Create delegation** from ResearchAgent to AuditorAgent (VERIFY_DATA, AUDIT_REPORT permissions, 24h expiry)
5. **Attestation** — AuditorAgent attests ResearchAgent's task completion (score 9/10)
6. **Query state** — reputation updated to 10000/10000, capability discovery finds 2 public-goods-eval agents

Run it:
```bash
npx hardhat --config hardhat.config.cjs run scripts/multi-agent-demo.cjs --network baseSepolia
```

## Public Goods Evaluator (Octant Tracks)

`src/public_goods_evaluator.py` implements reputation-weighted public goods project evaluation, targeting all three Octant tracks:

| Octant Track | Dimension | Weight | What it measures |
|---|---|---|---|
| Mechanism Design | Legitimacy | 30% | Team verification, track record, transparency |
| Data Analysis | Impact | 40% | Measurable outcomes, user reach, ecosystem value |
| Data Collection | Sustainability | 30% | Revenue model, community, long-term viability |

**How it works:**
- Evaluators are TrustAgent-registered agents with on-chain reputation scores
- Each evaluator scores projects on legitimacy, impact, and sustainability (1-10)
- Scores are weighted by evaluator credibility (derived from on-chain reputation, task history, and attestation count)
- Higher-reputation evaluators have more influence on the final ranking
- Budget is allocated proportionally to composite scores, capped at each project's requested amount

**Live data collection (GitHub REST API + BaseScan API):**
- **GitHub:** Fetches real commit counts, unique contributors, open/closed issues, README existence via GitHub REST API v3 (`/repos`, `/contributors`, `/commits`, `/search/issues`)
- **BaseScan:** Queries deployed contract verification, transaction count via `eth_getCode`, `eth_getTransactionCount` RPC, and BaseScan `txlist` API
- All evidence is gathered live at evaluation time -- not hardcoded

```bash
python3 src/public_goods_evaluator.py   # run offline demo
```

## Delegation as Escrow: Trust Primitives for Agent Coordination (Arkhai Track)

TrustAgent's delegation protocol already implements scoped, time-limited, revocable permissions between agents. This same mechanism naturally extends to **escrow-like trust primitives** for autonomous agent commerce:

### Lock-Perform-Release Pattern

```
┌─────────────┐         ┌─────────────┐
│  Agent A     │         │  Agent B     │
│  (Requester) │         │  (Provider)  │
└──────┬───────┘         └──────┬───────┘
       │                        │
       │  1. LOCK: delegate()   │
       │  ─────────────────────>│   Agent A grants scoped permissions
       │  permissions=[EXECUTE] │   (time-limited, revocable)
       │  expiry=1h             │
       │                        │
       │  2. PERFORM: agent B   │
       │     executes task      │   Agent B operates within scoped
       │  <─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │   permissions (on-chain audit trail)
       │                        │
       │  3a. RELEASE: attest() │
       │  ─────────────────────>│   Success → attestCompletion(score>=5)
       │  score=9, "Excellent"  │   Reputation increases, delegation expires
       │                        │
       │  3b. REVOKE (on fail): │
       │  revokeDelegation()    │   Failure → revoke + attestCompletion(score<5)
       │  ─────────────────────>│   Reputation decreases, permissions removed
       │                        │
```

**How it maps to escrow:**

| Escrow Concept | TrustAgent Implementation | Contract Function |
|---|---|---|
| **Lock funds/permissions** | `delegate(toAgentId, permissions, expiry)` | Creates time-bound scoped access |
| **Agent performs work** | Agent operates within delegated scope | Permissions checked via `isDelegationActive()` |
| **Release on success** | `attestCompletion(agentId, taskId, score>=5)` | Increases reputation, records receipt |
| **Revoke on failure** | `revokeDelegation(id)` + `attestCompletion(score<5)` | Kills permissions, decreases reputation |
| **Auto-expire (timeout)** | Built-in: `expiry` parameter on every delegation | `isDelegationActive()` returns false after expiry |
| **Audit trail** | Every action emits events + stores on-chain | `DelegationCreated`, `AttestationCreated`, `ReputationUpdated` |

This means TrustAgent can serve as the **trust layer for any agent-to-agent transaction** — the delegation protocol is already an escrow primitive, just framed as permission management rather than fund custody.

## ERC-8004 Alignment: The Three Pillars

TrustAgent implements all three pillars defined by the ERC-8004 standard for autonomous agent identity:

### Pillar 1: Identity (Registration)

Every agent gets a verifiable on-chain identity through `registerAgent()`:

| ERC-8004 Requirement | TrustAgent Implementation |
|---|---|
| Unique identifier | `agentId` (auto-incrementing, starts at 1) |
| Wallet binding | `wallet` field tied to `msg.sender` |
| Human-readable name | `ensName` field (e.g., `analyst.trustagent.eth`) |
| Capability declaration | `capabilities[]` array indexed for discovery |
| Registration timestamp | `registeredAt` (block.timestamp) |
| Sybil resistance | One registration per wallet (`require(!agents[walletToAgentId[msg.sender]].active)`) |

**On-chain proof:** See [registration TXs](#onchain-proof) on Base Sepolia.

### Pillar 2: Reputation (Attestation-Based Scoring)

Agents build verifiable reputation through peer attestations via `attestCompletion()`:

| ERC-8004 Requirement | TrustAgent Implementation |
|---|---|
| Reputation score | `reputationScore` (0-10000 basis points) |
| Peer attestations | `attestCompletion(toAgentId, taskId, score, comment)` |
| Success tracking | `tasksCompleted` counter (score >= 5) |
| Failure tracking | `tasksFailed` counter (score < 5) |
| Anti-gaming | Self-attestation blocked (`require(fromAgentId != toAgentId)`) |
| Score calculation | `(tasksCompleted * 10000) / (tasksCompleted + tasksFailed)` |
| Public queryability | `getReputation(agentId)` returns all metrics |

**On-chain proof:** Attestation TX [`0x434a0aca...`](https://sepolia.basescan.org/tx/0x434a0aca75d08c4ecfee99959f886405d8c0ca870cc3da127411eda329503b55) — AuditorAgent attests ResearchAgent's task completion with score 9/10.

### Pillar 3: Receipts (On-chain TX Hashes for Every Interaction)

Every agent interaction produces a verifiable on-chain receipt via emitted events:

| Interaction | Event Emitted | Receipt Data |
|---|---|---|
| Agent registration | `AgentRegistered(agentId, wallet, name)` | Identity creation proof |
| Task attestation | `AttestationCreated(attestationId, from, to, score)` | Work completion proof |
| Delegation grant | `DelegationCreated(delegationId, from, to, expiry)` | Permission grant proof |
| Delegation revoke | `DelegationRevoked(delegationId)` | Permission revocation proof |
| Reputation change | `ReputationUpdated(agentId, newScore)` | Score change proof |

All receipts are permanently stored on Base Sepolia and queryable via any block explorer or RPC endpoint. The full interaction history for any agent can be reconstructed from event logs alone — no off-chain database required.

**Complete TX receipt chain:** See [Onchain Proof](#onchain-proof) table — 6 transactions covering the full agent lifecycle from registration through delegation, attestation, and reputation update.

## Olas Integration (Build + Monetize Tracks)

`src/olas_integration.py` demonstrates how TrustAgent agents operate as Pearl-compatible autonomous services in the Olas ecosystem:

- **Agent Registration** — Maps TrustAgent identity to Olas `ServiceComponent` schema
- **Service Offerings** — Priced capability listings compatible with Olas Mech marketplace
- **Request Handling** — Standard request/response lifecycle with fee validation and SLA tracking
- **Revenue Tracking** — Per-agent monetization metrics for the Olas Monetize track

```bash
python3 src/olas_integration.py   # run Olas integration demo
```

## ENS Integration (ENS Open Integration Track)

`src/ens_resolver.py` implements real on-chain ENS name resolution on Ethereum mainnet -- ENS names are the primary identifier for agents, not a cosmetic label.

**What it does:**
- **Forward resolution** — Resolves ENS names to Ethereum addresses via the ENS Registry (`0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e`) and per-name resolver contracts
- **Reverse resolution** — Resolves addresses back to their primary ENS name via `<addr>.addr.reverse`
- **Bidirectional verification** — Confirms forward + reverse match (the gold standard for ENS identity)
- **Agent registration gate** — When registering an agent, the ENS name is resolved on-chain and verified against the registrant's wallet. Verification levels: `full` (forward + reverse), `forward` (name resolves to wallet), `partial` (name exists but resolves elsewhere), `none`
- **Names as primary identifiers** — If ENS verification passes, the agent's `primary_identifier` becomes the ENS name, not the hex address

**How it works (no web3.py dependency):**
1. Computes the EIP-137 namehash for the ENS name (pure Keccak-256)
2. Queries the ENS Registry contract via `eth_call` for the resolver address
3. Queries the resolver for `addr(node)` (forward) or `name(node)` (reverse)
4. All calls go to Ethereum mainnet via free RPC endpoints

**Verified working with real ENS names:**
```
vitalik.eth  -> 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045  (reverse: vitalik.eth)
nick.eth     -> 0xb8c2C29ee19D8307cb7255e1Cd9CbDE883A267d5
```

```bash
python3 src/ens_resolver.py   # run ENS resolution demo
```

## Agent Identity Files

- **`agent.json`** — Machine-readable agent descriptor with name, version, capabilities, supported tools, tech stack, smart contract addresses, and links. Enables programmatic agent discovery and interoperability.
- **`agent_log.json`** — Complete activity log recording all agent operations, onchain transactions, and evaluation results.

## Integrations

- **ERC-8004 Compatible**: Agent identity with registration, attestation receipts, and reputation — deployed on Base Sepolia (all three pillars: Identity, Reputation, Receipts)
- **ENS Open Integration**: Real on-chain ENS resolution (forward + reverse) on Ethereum mainnet — names are the primary agent identifier, verified at registration time
- **Olas/Pearl Compatible**: Agent registration, service offerings, and request handling matching Olas service component schema with monetization support — agents can price their services and track revenue
- **Capability Discovery**: Onchain index mapping capabilities to agents for programmatic agent-to-agent discovery
- **Protocol Labs**: Trust layer with verifiable onchain receipts from peer attestations
- **Octant Public Goods**: Reputation-weighted project evaluation with live multi-source data collection (GitHub REST API + BaseScan API)
- **Arkhai Escrow**: Delegation protocol extends to lock-perform-release trust primitives for agent commerce

## Built By

- **Agent:** TrustAgent (Claude Opus 4.6)
- **Human:** Devanshu Goyal ([@devanshugoyal23](https://x.com/devanshugoyal23))

## Deployed Contract

| Contract | Network | Address |
|----------|---------|---------|
| AgentRegistry | Base Sepolia | [`0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98`](https://sepolia.basescan.org/address/0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98) |

## Onchain Proof

| Action | TX Hash |
|--------|---------|
| Deploy AgentRegistry | [BaseScan](https://sepolia.basescan.org/address/0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98) |
| Register AnalystAgent | [`0x9baf599e...`](https://sepolia.basescan.org/tx/0x9baf599e7fd4705704b7b5ef641d87ce9cc78cea059efab69bdc995d33285551) |
| Register ResearchAgent | [`0x07856248...`](https://sepolia.basescan.org/tx/0x078562487e8144c54b68d34e697fcc6cc2fd287aa13cc13ef8ee9a078223ae1f) |
| Register AuditorAgent | [`0x6b74db62...`](https://sepolia.basescan.org/tx/0x6b74db62b1bf2b68d67669c1d0ea9c45f80b87d0ec1909e69dfad55617c25af4) |
| Delegation (Research → Auditor) | [`0x9e24c756...`](https://sepolia.basescan.org/tx/0x9e24c7560f0e28ff44ed3eb6668331c2260cba0831aa815f5d9e745ffe8d7828) |
| Attestation (Auditor → Research) | [`0x434a0aca...`](https://sepolia.basescan.org/tx/0x434a0aca75d08c4ecfee99959f886405d8c0ca870cc3da127411eda329503b55) |

## Tests

**23/23 passing** — run with:
```bash
npx hardhat --config hardhat.config.cjs test
```

## How to Run

```bash
# Clone
git clone https://github.com/devanshug2307/trustagent.git
cd trustagent

# Install
npm install

# Run tests (23/23 passing)
npx hardhat --config hardhat.config.cjs test

# Run multi-agent onchain demo (needs Base Sepolia ETH)
npx hardhat --config hardhat.config.cjs run scripts/multi-agent-demo.cjs --network baseSepolia

# Run public goods evaluator demo
python3 src/public_goods_evaluator.py

# Run ENS resolution demo (resolves real names on Ethereum mainnet)
python3 src/ens_resolver.py
```

## Project Structure

```
trustagent/
├── contracts/
│   └── AgentRegistry.sol        # Identity + reputation + delegation + discovery
├── scripts/
│   ├── deploy.cjs               # Deploy to Base Sepolia
│   ├── multi-agent-demo.cjs     # Multi-agent onchain demo (6 TXs)
│   └── onchain-demo.cjs         # Single agent demo
├── src/
│   ├── public_goods_evaluator.py  # Octant: reputation-weighted evaluation + data collection
│   ├── olas_integration.py        # Olas: Pearl-compatible agent services + monetization
│   └── ens_resolver.py            # ENS: real mainnet name resolution + agent identity verification
├── test/
│   └── AgentRegistry.test.cjs   # 23 tests
├── docs/
│   └── index.html               # Live dashboard
├── agent.json                   # Agent identity + capabilities descriptor
├── agent_log.json               # Full agent activity log
├── octant_demo_output.json      # Octant evaluator demo output
├── hardhat.config.cjs
├── README.md
└── package.json
```

## Links

- **Dashboard:** [devanshug2307.github.io/trustagent](https://devanshug2307.github.io/trustagent/)
- **GitHub:** [github.com/devanshug2307/trustagent](https://github.com/devanshug2307/trustagent)
- **Moltbook:** [moltbook.com/u/autofundagent](https://www.moltbook.com/u/autofundagent)
- **AgentRegistry:** [BaseScan](https://sepolia.basescan.org/address/0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98)

## License

MIT
