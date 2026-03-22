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

## Alkahest/Arkhai Escrow Integration (Arkhai Track)

TrustAgent integrates the **alkahest-ts SDK (v0.7.5)** as a load-bearing escrow layer for agent-to-agent commerce on Base Sepolia. Alkahest provides conditional peer-to-peer escrow built on EAS (Ethereum Attestation Service) -- TrustAgent uses it so that payment for agent tasks is only released when the worker passes an on-chain reputation check.

### How It Works

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  Delegator   │    │  TrustAgent  │    │   Worker    │
│  (pays ETH)  │    │  (oracle)    │    │  (agent)    │
└──────┬───────┘    └──────┬───────┘    └──────┬──────┘
       │                   │                   │
       │ 1. CREATE ESCROW  │                   │
       │ deposit ETH into  │                   │
       │ NativeTokenEscrow │                   │
       │ demand: task +    │                   │
       │   min reputation  │                   │
       │ oracle: TrustAgent│                   │
       │──────────────────>│                   │
       │                   │                   │
       │                   │ 2. FULFILL TASK   │
       │                   │<──────────────────│
       │                   │ StringObligation  │
       │                   │ (result as EAS    │
       │                   │  attestation)     │
       │                   │                   │
       │                   │ 3. ARBITRATE      │
       │                   │ Read AgentRegistry│
       │                   │ Check reputation  │
       │                   │ score >= threshold│
       │                   │──> approve/reject │
       │                   │                   │
       │                   │         4. COLLECT│
       │                   │   (if approved)   │
       │                   │──────────────────>│
       │                   │   Worker gets ETH │
```

**Core dependency:** `alkahest-ts` v0.7.5 -- all escrow creation, fulfillment, arbitration, and collection go through Alkahest's on-chain contracts.

### Escrow-Backed Delegation

| Step | Alkahest SDK Call | What Happens |
|---|---|---|
| **1. Escrow** | `nativeToken.escrow.nonTierable.create()` | Delegator locks ETH in Alkahest escrow with a `TrustedOracleArbiter` demand |
| **2. Demand** | `encodeTrustedOracleDemand()` | Demand encodes: task description, required capability, minimum reputation score, AgentRegistry address |
| **3. Fulfill** | `stringObligation.doObligation()` | Worker submits task result as an EAS attestation referencing the escrow |
| **4. Arbitrate** | `arbiters.general.trustedOracle.arbitrate()` | TrustAgent oracle reads worker's on-chain reputation from AgentRegistry, approves if score >= threshold |
| **5. Collect** | `nativeToken.escrow.nonTierable.collect()` | Approved worker withdraws the escrowed ETH |
| **5b. Reclaim** | `nativeToken.escrow.nonTierable.reclaimExpired()` | If rejected or expired, delegator reclaims funds |

### Why This Is Load-Bearing

Alkahest is not decorative here -- it is the settlement layer:

- **No Alkahest = no payment.** The worker cannot receive funds without an Alkahest escrow + arbitration chain.
- **Trust gate = AgentRegistry.** The oracle decision is based on real on-chain reputation data (`getReputation()` from the deployed AgentRegistry contract).
- **EAS attestation chain.** Every step (escrow, fulfillment, arbitration) produces a verifiable on-chain attestation via EAS on Base Sepolia.
- **Production oracle mode.** `node src/alkahest_escrow.mjs --oracle` runs TrustAgent as a long-running oracle that auto-arbitrates incoming requests using `arbitrateMany()`.

### Alkahest Contracts (Base Sepolia)

| Contract | Address |
|---|---|
| EAS | `0x4200000000000000000000000000000000000021` |
| TrustedOracleArbiter | `0x3664b11BcCCeCA27C21BBAB43548961eD14d4D6D` |
| StringObligation | `0x544873C22A3228798F91a71C4ef7a9bFe96E7CE0` |
| NativeTokenEscrowObligation | `0x8a1172D32B8cEf14094cF1E7d6F3d1A36D949FDe` |
| ERC20EscrowObligation | `0x1Fe964348Ec42D9Bb1A072503ce8b4744266FF43` |

### SDK Verification Proof

7/7 checks passing -- see `alkahest_proof.json` for full output:

```bash
npm run alkahest:test     # verify SDK + contracts reachable (no wallet needed)
npm run alkahest:proof    # run test and write alkahest_proof.json
npm run alkahest:oracle   # start TrustAgent as Alkahest oracle listener
npm run alkahest:demo     # full escrow flow (needs funded wallets)
```

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

## Olas Mech Server (Monetize Your Agent Track)

TrustAgent runs as an Olas-compatible mech server that serves the `reputation_evaluation` tool via the standard mech request/deliver protocol. This satisfies the Olas "Monetize Your Agent" track requirement of serving 50+ requests.

### Setup

The mech workspace was initialized via the official `mech-server` CLI (v0.8.1):

```bash
# Initialize workspace and scaffold tool
mech setup -c base                    # Bootstrap ~/.operate-mech workspace
mech add-tool trustagent reputation_evaluation -d "Evaluate agent reputation..."
mech add-tool trustagent project_evaluation -d "Evaluate public goods projects..."
```

### Registered Mech Tools

| Tool | Path | Description |
|------|------|-------------|
| `reputation_evaluation` | `~/.operate-mech/packages/trustagent/customs/reputation_evaluation/` | On-chain agent reputation queries via TrustAgent AgentRegistry |
| `project_evaluation` | `~/.operate-mech/packages/trustagent/customs/project_evaluation/` | Reputation-weighted public goods project scoring |

Both tools follow the Olas `MechResponse` protocol: `run(**kwargs) -> (result, prompt, metadata, extra1, extra2)`

### How It Works

1. **Tool scaffolded via `mech add-tool`** -- standard Olas tool structure with `component.yaml`, `__init__.py`, and tool implementation
2. **On-chain data** -- The `reputation_evaluation` tool reads live data from the TrustAgent AgentRegistry on Base Sepolia (`0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98`)
3. **HTTP mech server** -- `src/mech_server.py` wraps the tool with an HTTP API following the mech request/deliver lifecycle
4. **55 requests served** -- All delivered successfully, 0 failures

### Proof: 55/55 Requests Served

```
Total requests:    55
Delivered:         55
Failed:            0
Total revenue:     5,500,000 wei (0.0000055 ETH)
Avg delivery time: 1,261.8 ms
Throughput:        0.8 req/s (on-chain reads are ~1.6s each)
```

Request breakdown:
- 20 on-chain agent reputation queries (agents 1-10 queried twice)
- 15 public goods project evaluations
- 10 extended agent queries (agents 11-20)
- 10 natural language reputation queries

Full proof: `olas_mech_server_proof.json` (55 request/response records with delivery receipts)

### Run Commands

```bash
# Run the 55-request proof test (generates olas_mech_server_proof.json)
python3 -m src.mech_server --test

# Start HTTP mech server (Olas-compatible API)
python3 -m src.mech_server --port 8080

# HTTP client test (requires server running)
python3 -m src.mech_client_test --requests 60

# API endpoints:
#   POST /api/v1/request  — Submit a mech request
#   GET  /api/v1/tools    — List available tools
#   GET  /api/v1/stats    — Server statistics
#   GET  /health          — Health check
```

### Wallet

| Field | Value |
|-------|-------|
| Mech Address | `0x54eeFbb7b3F701eEFb7fa99473A60A6bf5fE16D7` |
| Agent ID | 1 |
| Network | Base Sepolia (84532) |
| Registry | `0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98` |

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

## OpenServ SDK Integration (OpenServ Track)

`src/openserv_agent.mjs` registers TrustAgent as a full OpenServ-compatible agent using the `@openserv-labs/sdk` (v2.4.1). The agent exposes 4 capabilities that read directly from the on-chain AgentRegistry contract on Base Sepolia:

| Capability | Description |
|---|---|
| `get_reputation` | Look up an agent's on-chain reputation score, tasks completed/failed, and attestation count |
| `discover_agents` | Find registered agents matching a capability tag and minimum reputation threshold |
| `verify_trust` | Verify whether an agent meets a trust threshold before delegating — returns TRUSTED / INSUFFICIENT_TRUST verdict |
| `evaluate_project` | Reputation-weighted public goods evaluation across legitimacy, impact, and sustainability |

**How it works:**
- Uses the OpenServ SDK `Agent` class with Zod-validated input schemas for each capability
- Every capability calls the live AgentRegistry contract (`0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98`) via ethers.js
- The `--test` flag verifies the SDK loads, all 4 capabilities register, and on-chain reads succeed — no API key needed
- To go fully live on the OpenServ platform: set `OPENSERV_API_KEY` and run `npm run openserv:start`

### Live Platform Registration

TrustAgent is registered and actively connected to the OpenServ platform with a configured API key. The following live interactions have been verified:

| Action | Platform Response | Proof |
|---|---|---|
| API key authenticated | `x-openserv-key` header accepted, 200 OK | REST API calls succeed |
| Workspace created | ID: **13044** with Web3 wallet provisioned | `POST /workspaces` |
| Task created | ID: **60889** — "Evaluate TrustAgent on-chain reputation system" | `POST /workspaces/13044/task` |
| File uploaded | ID: **49948** — capabilities manifest auto-summarized by platform | `POST /workspaces/13044/file` |
| Chat message sent | ID: **16930** — agent status broadcast to workspace | `POST /workspaces/13044/agent-chat/1/message` |
| Agent HTTP server | Port 7378, health check passing, all 4 tools callable | `GET /health` returns `{"status":"ok"}` |
| Runtime health | OpenServ runtime at `agents.openserv.ai` responds OK | `GET /runtime/health` |
| Web3 wallet | `0x939c38CEe11DD73b1B645AFC1804050346fCc157` on Base mainnet | Platform auto-provisioned |

**Platform proof files:**
- `openserv_live_proof.json` — Complete JSON record of all 11 live API interactions with request/response data
- `openserv_proof.txt` — Human-readable proof with timestamps and HTTP status codes

**Workspace:** [platform.openserv.ai/workspaces/13044](https://platform.openserv.ai/workspaces/13044)
**Uploaded file:** [trustagent_capabilities.json on GCS](https://storage.googleapis.com/openserv-prod/fcdfabe7-8400-45de-8071-64b2d3f26b48/trustagent_capabilities.json)

```bash
npm run openserv:test    # verify SDK + on-chain integration (no API key needed)
npm run openserv:start   # start agent on OpenServ platform (requires OPENSERV_API_KEY)
```

## Integrations

- **ERC-8004 Compatible**: Agent identity with registration, attestation receipts, and reputation — deployed on Base Sepolia (all three pillars: Identity, Reputation, Receipts)
- **ENS Open Integration**: Real on-chain ENS resolution (forward + reverse) on Ethereum mainnet — names are the primary agent identifier, verified at registration time
- **Olas Mech Server**: Full mech-server v0.8.1 integration -- tool scaffolded via `mech add-tool`, 55/55 requests served with on-chain reputation data, HTTP API following mech request/deliver protocol, revenue tracking at 100K wei/request
- **Olas/Pearl Compatible**: Agent registration, service offerings, and request handling matching Olas service component schema with monetization support — agents can price their services and track revenue
- **OpenServ SDK**: Live `@openserv-labs/sdk` v2.4.1 integration — API key authenticated, workspace created (ID 13044), task created (ID 60889), file uploaded (ID 49948), chat message sent, all 4 on-chain capabilities tested and passing
- **Capability Discovery**: Onchain index mapping capabilities to agents for programmatic agent-to-agent discovery
- **Protocol Labs**: Trust layer with verifiable onchain receipts from peer attestations
- **Octant Public Goods**: Reputation-weighted project evaluation with live multi-source data collection (GitHub REST API + BaseScan API)
- **Arkhai/Alkahest Escrow**: Real `alkahest-ts` v0.7.5 integration -- ETH escrow via NativeTokenEscrowObligation, TrustedOracleArbiter demand encoding, StringObligation fulfillment, oracle arbitration gated by AgentRegistry reputation. 7/7 SDK verification checks passing. Alkahest is the settlement layer: no escrow = no payment.

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
│   ├── alkahest_escrow.mjs         # Arkhai: alkahest-ts escrow with TrustedOracleArbiter + reputation gate
│   ├── openserv_agent.mjs          # OpenServ: SDK agent with 4 on-chain capabilities
│   ├── public_goods_evaluator.py   # Octant: reputation-weighted evaluation + data collection
│   ├── olas_integration.py         # Olas: Pearl-compatible agent services + monetization
│   ├── mech_server.py              # Olas: mech-server with reputation_evaluation tool (55 requests served)
│   ├── mech_client_test.py         # Olas: HTTP client for testing mech server
│   └── ens_resolver.py             # ENS: real mainnet name resolution + agent identity verification
├── test/
│   └── AgentRegistry.test.cjs   # 23 tests
├── docs/
│   └── index.html               # Live dashboard
├── agent.json                   # Agent identity + capabilities descriptor
├── agent_log.json               # Full agent activity log
├── alkahest_proof.json           # Alkahest SDK verification proof (7/7 checks)
├── openserv_proof.txt           # OpenServ live platform integration proof (11 API calls)
├── openserv_live_proof.json     # Complete JSON record of all live API interactions
├── octant_demo_output.json      # Octant evaluator demo output
├── olas_mech_server_proof.json  # Olas mech server proof: 55/55 requests served
├── hardhat.config.cjs
├── README.md
└── package.json
```

## Links

- **Dashboard:** [devanshug2307.github.io/trustagent](https://devanshug2307.github.io/trustagent/)
- **GitHub:** [github.com/devanshug2307/trustagent](https://github.com/devanshug2307/trustagent)
- **Moltbook:** [moltbook.com/u/autofundagent](https://www.moltbook.com/u/autofundagent)
- **Moltbook Post:** [TrustAgent on m/synthesis](https://www.moltbook.com/post/a03d0519-272c-4fba-8c94-6fe7509db4ce)
- **AgentRegistry:** [BaseScan](https://sepolia.basescan.org/address/0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98)

## License

MIT
