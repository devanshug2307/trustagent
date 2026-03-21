# TrustAgent: Multi-Agent Identity & Coordination Network

> How does one agent know it can trust another? TrustAgent answers that question.

**Built for [The Synthesis Hackathon 2026](https://synthesis.md)**

---

## Problem

As AI agents proliferate, trust becomes the bottleneck. There's no standard way for agents to prove who they are, verify what they can do, or enforce agreements with each other. Without trust infrastructure, agent-to-agent commerce can't scale.

## Solution

TrustAgent builds the trust layer for autonomous agents:

1. **Verifiable Identity (ERC-8004)** — Agents register onchain with verifiable credentials
2. **Reputation System** — Track record of completed tasks, reliability scores
3. **Delegation Framework** — Scoped permissions that agents grant to each other
4. **Agent Discovery** — Find and evaluate agents by capability and reputation
5. **ENS Integration** — Human-readable names for all agent interactions

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

```bash
python3 src/public_goods_evaluator.py   # run offline demo
```

## Integrations

- **ERC-8004 Compatible**: Agent identity with registration, attestation receipts, and reputation — deployed on Base Sepolia
- **Capability Discovery**: Onchain index mapping capabilities to agents for programmatic agent-to-agent discovery
- **Protocol Labs**: Trust layer with verifiable onchain receipts from peer attestations
- **Octant Public Goods**: Reputation-weighted project evaluation across mechanism design, data analysis, and data collection

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

## License

MIT
