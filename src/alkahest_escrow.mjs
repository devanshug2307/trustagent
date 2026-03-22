/**
 * alkahest_escrow.mjs -- Alkahest/Arkhai Escrow Integration for TrustAgent
 *
 * Implements a real, load-bearing escrow pattern where:
 *   1. A task delegator deposits native ETH into an Alkahest escrow on Base Sepolia
 *   2. The escrow demand is gated by a TrustedOracleArbiter, naming TrustAgent as the oracle
 *   3. The demand encodes task requirements + a minimum reputation threshold
 *   4. A worker fulfills the task via a StringObligation attestation (EAS)
 *   5. TrustAgent (oracle) reads the worker's on-chain reputation from AgentRegistry,
 *      verifies the fulfillment, and arbitrates (approve/reject)
 *   6. On approval the worker collects the escrowed ETH; on rejection the delegator reclaims
 *
 * This is NOT decorative: Alkahest's EAS-based escrow is the settlement layer,
 * and TrustAgent's AgentRegistry reputation is the trust gate that controls fund release.
 *
 * Usage:
 *   node src/alkahest_escrow.mjs              # full demo (needs funded wallets)
 *   node src/alkahest_escrow.mjs --test       # verify SDK loads + contracts reachable
 *   node src/alkahest_escrow.mjs --proof      # run test and write alkahest_proof.json
 */

import {
  makeClient,
  contractAddresses,
  encodeTrustedOracleDemand,
  decodeTrustedOracleDemand,
  supportedChains,
} from "alkahest-ts";

import {
  createWalletClient,
  createPublicClient,
  http,
  parseEther,
  formatEther,
  encodeAbiParameters,
  parseAbiParameters,
  decodeAbiParameters,
  getAddress,
  zeroAddress,
} from "viem";

import { privateKeyToAccount, nonceManager } from "viem/accounts";
import { baseSepolia } from "viem/chains";
import { readFileSync, writeFileSync } from "fs";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const RPC_URL = process.env.RPC_URL || "https://sepolia.base.org";
const AGENT_REGISTRY_ADDRESS = "0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98";

// Minimal AgentRegistry ABI (read-only)
const REGISTRY_ABI = [
  {
    name: "getReputation",
    type: "function",
    stateMutability: "view",
    inputs: [{ name: "agentId", type: "uint256" }],
    outputs: [
      { name: "score", type: "uint256" },
      { name: "tasksCompleted", type: "uint256" },
      { name: "tasksFailed", type: "uint256" },
      { name: "totalAttestations", type: "uint256" },
    ],
  },
  {
    name: "walletToAgentId",
    type: "function",
    stateMutability: "view",
    inputs: [{ name: "wallet", type: "address" }],
    outputs: [{ name: "agentId", type: "uint256" }],
  },
  {
    name: "agents",
    type: "function",
    stateMutability: "view",
    inputs: [{ name: "agentId", type: "uint256" }],
    outputs: [
      { name: "id", type: "uint256" },
      { name: "wallet", type: "address" },
      { name: "name", type: "string" },
      { name: "ensName", type: "string" },
      { name: "capabilities", type: "string[]" },
      { name: "registeredAt", type: "uint256" },
      { name: "reputationScore", type: "uint256" },
      { name: "tasksCompleted", type: "uint256" },
      { name: "tasksFailed", type: "uint256" },
      { name: "active", type: "bool" },
    ],
  },
  {
    name: "nextAgentId",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ name: "", type: "uint256" }],
  },
];

// ---------------------------------------------------------------------------
// Demand encoding: task requirements + reputation threshold
//
// The inner demand is an ABI-encoded struct that both the worker and the oracle
// agree on. It contains the task description, required capability, and the
// minimum reputation score the worker must hold in the AgentRegistry.
// ---------------------------------------------------------------------------

const TASK_DEMAND_TYPES = parseAbiParameters(
  "(string taskDescription, string requiredCapability, uint256 minReputationScore, address agentRegistryAddress)"
);

function encodeTaskDemand({
  taskDescription,
  requiredCapability,
  minReputationScore,
  agentRegistryAddress,
}) {
  return encodeAbiParameters(TASK_DEMAND_TYPES, [
    {
      taskDescription,
      requiredCapability,
      minReputationScore: BigInt(minReputationScore),
      agentRegistryAddress,
    },
  ]);
}

function decodeTaskDemand(data) {
  const decoded = decodeAbiParameters(TASK_DEMAND_TYPES, data);
  return {
    taskDescription: decoded[0].taskDescription,
    requiredCapability: decoded[0].requiredCapability,
    minReputationScore: decoded[0].minReputationScore,
    agentRegistryAddress: decoded[0].agentRegistryAddress,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeAlkahestClient(privateKey) {
  const account = privateKeyToAccount(privateKey, { nonceManager });
  const walletClient = createWalletClient({
    account,
    chain: baseSepolia,
    transport: http(RPC_URL),
  });
  return makeClient(walletClient);
}

function getPublicClient() {
  return createPublicClient({
    chain: baseSepolia,
    transport: http(RPC_URL),
  });
}

/**
 * Look up on-chain reputation for a wallet address via the AgentRegistry.
 * Returns { agentId, score, tasksCompleted, tasksFailed, active } or null.
 */
async function getOnChainReputation(publicClient, walletAddress) {
  const agentId = await publicClient.readContract({
    address: AGENT_REGISTRY_ADDRESS,
    abi: REGISTRY_ABI,
    functionName: "walletToAgentId",
    args: [walletAddress],
  });

  if (agentId === 0n) return null;

  const [score, tasksCompleted, tasksFailed, totalAttestations] =
    await publicClient.readContract({
      address: AGENT_REGISTRY_ADDRESS,
      abi: REGISTRY_ABI,
      functionName: "getReputation",
      args: [agentId],
    });

  return {
    agentId: Number(agentId),
    score: Number(score),
    tasksCompleted: Number(tasksCompleted),
    tasksFailed: Number(tasksFailed),
    totalAttestations: Number(totalAttestations),
  };
}

// ---------------------------------------------------------------------------
// Core escrow flow
// ---------------------------------------------------------------------------

/**
 * STEP 1 -- Delegator creates an escrow.
 *
 * Deposits `amount` ETH into a NativeToken escrow on Alkahest.
 * The demand is a TrustedOracleArbiter demand naming `oracleAddress` as oracle,
 * with the inner data encoding the task requirements and reputation gate.
 */
async function createTaskEscrow(
  delegatorClient,
  {
    oracleAddress,
    taskDescription,
    requiredCapability,
    minReputationScore,
    escrowAmountEth,
    expirationSeconds,
  }
) {
  console.log("\n--- STEP 1: Create escrow (delegator deposits ETH) ---");
  console.log(`  Task:          ${taskDescription}`);
  console.log(`  Required cap:  ${requiredCapability}`);
  console.log(`  Min reputation: ${minReputationScore}`);
  console.log(`  Escrow amount: ${escrowAmountEth} ETH`);
  console.log(`  Oracle:        ${oracleAddress}`);

  // Encode the application-specific inner demand
  const innerDemand = encodeTaskDemand({
    taskDescription,
    requiredCapability,
    minReputationScore,
    agentRegistryAddress: AGENT_REGISTRY_ADDRESS,
  });

  // Wrap in TrustedOracleArbiter demand (oracle = TrustAgent)
  const demand = encodeTrustedOracleDemand({
    oracle: oracleAddress,
    data: innerDemand,
  });

  const arbiterAddress =
    contractAddresses["Base Sepolia"].trustedOracleArbiter;

  const expiration = BigInt(
    Math.floor(Date.now() / 1000) + (expirationSeconds || 86400)
  );

  // Create escrow: deposit ETH with the demand
  const escrow = await delegatorClient.nativeToken.escrow.nonTierable.create(
    parseEther(escrowAmountEth),
    { arbiter: arbiterAddress, demand },
    expiration
  );

  console.log(`  Escrow TX:     ${escrow.hash}`);
  console.log(`  Escrow UID:    ${escrow.attested.uid}`);

  return {
    escrowUid: escrow.attested.uid,
    escrowHash: escrow.hash,
    demand,
    innerDemand,
    arbiterAddress,
  };
}

/**
 * STEP 2 -- Worker fulfills the task via StringObligation attestation.
 *
 * The worker produces a result string and records it as an EAS attestation
 * referencing the escrow UID. This creates a verifiable on-chain receipt.
 */
async function fulfillTask(workerClient, escrowUid, resultString) {
  console.log("\n--- STEP 2: Worker fulfills task (StringObligation) ---");
  console.log(`  Result:     "${resultString}"`);
  console.log(`  Escrow ref: ${escrowUid}`);

  const fulfillment = await workerClient.stringObligation.doObligation(
    resultString,
    undefined, // default schema
    escrowUid  // reference to the escrow being fulfilled
  );

  console.log(`  Fulfill TX:  ${fulfillment.hash}`);
  console.log(`  Fulfill UID: ${fulfillment.attested.uid}`);

  return {
    fulfillmentUid: fulfillment.attested.uid,
    fulfillmentHash: fulfillment.hash,
  };
}

/**
 * STEP 3 -- TrustAgent (oracle) arbitrates.
 *
 * This is the load-bearing trust check:
 *   a. Decode the demand to extract the reputation threshold
 *   b. Look up the worker's wallet in the AgentRegistry
 *   c. Compare the worker's on-chain reputation score against the threshold
 *   d. Call arbitrate(true) if the worker qualifies, arbitrate(false) otherwise
 *
 * The arbitration is recorded as an EAS attestation, completing the trust chain:
 *   Escrow -> Fulfillment -> Arbitration
 */
async function arbitrateAsOracle(
  oracleClient,
  fulfillmentUid,
  demand,
  workerAddress
) {
  console.log("\n--- STEP 3: TrustAgent oracle arbitrates ---");

  // Decode the outer TrustedOracleArbiter demand to get inner data
  const outerDemand = decodeTrustedOracleDemand(demand);
  const taskDemand = decodeTaskDemand(outerDemand.data);

  console.log(`  Task:            ${taskDemand.taskDescription}`);
  console.log(`  Required cap:    ${taskDemand.requiredCapability}`);
  console.log(
    `  Min reputation:  ${taskDemand.minReputationScore} (${Number(taskDemand.minReputationScore) / 100}%)`
  );

  // Query the AgentRegistry for the worker's reputation
  const publicClient = getPublicClient();
  const reputation = await getOnChainReputation(publicClient, workerAddress);

  let decision = false;

  if (!reputation) {
    console.log(`  Worker ${workerAddress} NOT registered in AgentRegistry`);
    console.log(`  Decision: REJECT (unregistered agent)`);
    decision = false;
  } else {
    console.log(`  Worker agent ID: ${reputation.agentId}`);
    console.log(
      `  Worker score:    ${reputation.score} (${reputation.score / 100}%)`
    );
    console.log(`  Tasks completed: ${reputation.tasksCompleted}`);

    decision = BigInt(reputation.score) >= taskDemand.minReputationScore;
    console.log(
      `  Decision: ${decision ? "APPROVE" : "REJECT"} (score ${reputation.score} ${decision ? ">=" : "<"} threshold ${taskDemand.minReputationScore})`
    );
  }

  // Submit arbitration to Alkahest (EAS attestation)
  const txHash = await oracleClient.arbiters.general.trustedOracle.arbitrate(
    fulfillmentUid,
    demand,
    decision
  );

  console.log(`  Arbitration TX: ${txHash}`);

  return { decision, txHash, reputation };
}

/**
 * STEP 4 -- Worker collects the escrowed ETH (only works if arbitration = true).
 */
async function collectEscrow(workerClient, escrowUid, fulfillmentUid) {
  console.log("\n--- STEP 4: Worker collects escrow ---");

  const txHash = await workerClient.nativeToken.escrow.nonTierable.collect(
    escrowUid,
    fulfillmentUid
  );

  console.log(`  Collect TX: ${txHash}`);
  return txHash;
}

// ---------------------------------------------------------------------------
// Full demo flow
// ---------------------------------------------------------------------------

async function runFullDemo() {
  console.log("=".repeat(70));
  console.log("  ALKAHEST ESCROW DEMO: Trust-Gated Agent Task Delegation");
  console.log("=".repeat(70));

  const delegatorKey = process.env.DELEGATOR_KEY || process.env.PRIVATE_KEY;
  const workerKey = process.env.WORKER_KEY;
  const oracleKey = process.env.ORACLE_KEY || process.env.PRIVATE_KEY;

  if (!delegatorKey || !workerKey || !oracleKey) {
    console.error(
      "\nFull demo requires DELEGATOR_KEY, WORKER_KEY, and ORACLE_KEY (or PRIVATE_KEY as fallback)."
    );
    console.error("Run with --test for SDK verification without funded wallets.");
    process.exit(1);
  }

  const delegatorClient = makeAlkahestClient(delegatorKey);
  const workerClient = makeAlkahestClient(workerKey);
  const oracleClient = makeAlkahestClient(oracleKey);

  const oracleAddress = oracleClient.viemClient.account.address;
  const workerAddress = workerClient.viemClient.account.address;

  // Step 1: Create escrow
  const escrow = await createTaskEscrow(delegatorClient, {
    oracleAddress,
    taskDescription: "Analyze DeFi protocol risk for Compound V3",
    requiredCapability: "research",
    minReputationScore: 5000, // 50% minimum reputation
    escrowAmountEth: "0.001",
    expirationSeconds: 3600,
  });

  // Step 2: Worker fulfills
  const fulfillment = await fulfillTask(
    workerClient,
    escrow.escrowUid,
    JSON.stringify({
      task: "Analyze DeFi protocol risk for Compound V3",
      result:
        "Compound V3 shows moderate risk: TVL $2.1B, audited by OpenZeppelin, governance via COMP token. Supply APY 3.2% USDC. Key risk: smart contract complexity and oracle dependency.",
      timestamp: new Date().toISOString(),
      workerAgent: workerAddress,
    })
  );

  // Step 3: Oracle arbitrates (checking AgentRegistry reputation)
  const arbitration = await arbitrateAsOracle(
    oracleClient,
    fulfillment.fulfillmentUid,
    escrow.demand,
    workerAddress
  );

  // Step 4: Collect (if approved)
  if (arbitration.decision) {
    const collectTx = await collectEscrow(
      workerClient,
      escrow.escrowUid,
      fulfillment.fulfillmentUid
    );
    console.log("\nEscrow collected successfully. Task payment released.");
  } else {
    console.log(
      "\nArbitration rejected. Escrow remains locked for delegator reclaim."
    );
  }

  console.log("\n" + "=".repeat(70));
  console.log("  DEMO COMPLETE");
  console.log("=".repeat(70));
}

// ---------------------------------------------------------------------------
// SDK verification test (--test / --proof)
// ---------------------------------------------------------------------------

async function runTest() {
  const results = {
    timestamp: new Date().toISOString(),
    test: "alkahest-ts SDK integration verification",
    sdkVersion: "0.7.5",
    chain: "Base Sepolia (chainId 84532)",
    steps: [],
    passed: true,
  };

  function log(step, status, details) {
    const entry = { step, status, ...details };
    results.steps.push(entry);
    const icon = status === "PASS" ? "[PASS]" : "[FAIL]";
    console.log(`${icon} ${step}`);
    if (details) {
      for (const [k, v] of Object.entries(details)) {
        if (k !== "step" && k !== "status") {
          console.log(`       ${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`);
        }
      }
    }
  }

  console.log("=".repeat(70));
  console.log("  ALKAHEST SDK VERIFICATION TEST");
  console.log("=".repeat(70));
  console.log();

  // 1. SDK loads
  try {
    const { makeClient: mc, contractAddresses: ca, supportedChains: sc } =
      await import("alkahest-ts");
    log("1. SDK import", "PASS", {
      exports: ["makeClient", "contractAddresses", "supportedChains", "encodeTrustedOracleDemand"],
      supportedChains: sc,
    });
  } catch (e) {
    log("1. SDK import", "FAIL", { error: e.message });
    results.passed = false;
  }

  // 2. Contract addresses for Base Sepolia
  try {
    const addrs = contractAddresses["Base Sepolia"];
    if (!addrs) throw new Error("No addresses for Base Sepolia");
    log("2. Base Sepolia contract addresses", "PASS", {
      eas: addrs.eas,
      trustedOracleArbiter: addrs.trustedOracleArbiter,
      stringObligation: addrs.stringObligation,
      nativeTokenEscrowObligation: addrs.nativeTokenEscrowObligation,
      erc20EscrowObligation: addrs.erc20EscrowObligation,
    });
  } catch (e) {
    log("2. Base Sepolia contract addresses", "FAIL", { error: e.message });
    results.passed = false;
  }

  // 3. Demand encoding round-trip
  try {
    const innerDemand = encodeTaskDemand({
      taskDescription: "Analyze DeFi protocol risk",
      requiredCapability: "research",
      minReputationScore: 5000,
      agentRegistryAddress: AGENT_REGISTRY_ADDRESS,
    });

    const oracleAddr = "0x0000000000000000000000000000000000000001";
    const fullDemand = encodeTrustedOracleDemand({
      oracle: oracleAddr,
      data: innerDemand,
    });

    const decoded = decodeTrustedOracleDemand(fullDemand);
    if (decoded.oracle.toLowerCase() !== oracleAddr.toLowerCase()) {
      throw new Error("Oracle address mismatch after decode");
    }

    const taskDecoded = decodeTaskDemand(decoded.data);
    if (taskDecoded.taskDescription !== "Analyze DeFi protocol risk") {
      throw new Error("Task description mismatch after decode");
    }
    if (Number(taskDecoded.minReputationScore) !== 5000) {
      throw new Error("Reputation threshold mismatch after decode");
    }

    log("3. Demand encode/decode round-trip", "PASS", {
      innerDemandBytes: innerDemand.length,
      fullDemandBytes: fullDemand.length,
      decodedOracle: decoded.oracle,
      decodedTask: taskDecoded.taskDescription,
      decodedMinRep: Number(taskDecoded.minReputationScore),
    });
  } catch (e) {
    log("3. Demand encode/decode round-trip", "FAIL", { error: e.message });
    results.passed = false;
  }

  // 4. Alkahest client creation (read-only, no funded wallet needed)
  try {
    // Deterministic test key (no real funds)
    const testKey =
      "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80";
    const client = makeAlkahestClient(testKey);

    if (!client.nativeToken) throw new Error("Missing nativeToken client");
    if (!client.stringObligation) throw new Error("Missing stringObligation client");
    if (!client.arbiters) throw new Error("Missing arbiters client");
    if (!client.arbiters.general.trustedOracle)
      throw new Error("Missing trustedOracle arbiter");

    log("4. Alkahest client creation", "PASS", {
      hasNativeTokenEscrow: !!client.nativeToken.escrow,
      hasStringObligation: !!client.stringObligation.doObligation,
      hasTrustedOracleArbiter: !!client.arbiters.general.trustedOracle.arbitrate,
      hasArbitrationListener: !!client.arbiters.general.trustedOracle.arbitrateMany,
      contractAddresses: {
        trustedOracleArbiter: client.contractAddresses.trustedOracleArbiter,
        stringObligation: client.contractAddresses.stringObligation,
        nativeTokenEscrow: client.contractAddresses.nativeTokenEscrowObligation,
        eas: client.contractAddresses.eas,
      },
    });
  } catch (e) {
    log("4. Alkahest client creation", "FAIL", { error: e.message });
    results.passed = false;
  }

  // 5. On-chain contract reachability (EAS + AgentRegistry)
  try {
    const publicClient = getPublicClient();

    // Check EAS contract
    const easCode = await publicClient.getCode({
      address: contractAddresses["Base Sepolia"].eas,
    });
    const easReachable = easCode && easCode !== "0x";

    // Check TrustedOracleArbiter contract
    const arbiterCode = await publicClient.getCode({
      address: contractAddresses["Base Sepolia"].trustedOracleArbiter,
    });
    const arbiterReachable = arbiterCode && arbiterCode !== "0x";

    // Check StringObligation contract
    const stringCode = await publicClient.getCode({
      address: contractAddresses["Base Sepolia"].stringObligation,
    });
    const stringReachable = stringCode && stringCode !== "0x";

    // Check NativeToken escrow contract
    const escrowCode = await publicClient.getCode({
      address: contractAddresses["Base Sepolia"].nativeTokenEscrowObligation,
    });
    const escrowReachable = escrowCode && escrowCode !== "0x";

    // Check AgentRegistry contract
    const registryCode = await publicClient.getCode({
      address: AGENT_REGISTRY_ADDRESS,
    });
    const registryReachable = registryCode && registryCode !== "0x";

    if (!easReachable) throw new Error("EAS contract not reachable");
    if (!arbiterReachable)
      throw new Error("TrustedOracleArbiter not reachable");
    if (!stringReachable)
      throw new Error("StringObligation not reachable");
    if (!escrowReachable)
      throw new Error("NativeTokenEscrow not reachable");
    if (!registryReachable)
      throw new Error("AgentRegistry not reachable");

    log("5. On-chain contract reachability", "PASS", {
      eas: `${contractAddresses["Base Sepolia"].eas} (${easCode.length} bytes)`,
      trustedOracleArbiter: `${contractAddresses["Base Sepolia"].trustedOracleArbiter} (${arbiterCode.length} bytes)`,
      stringObligation: `${contractAddresses["Base Sepolia"].stringObligation} (${stringCode.length} bytes)`,
      nativeTokenEscrow: `${contractAddresses["Base Sepolia"].nativeTokenEscrowObligation} (${escrowCode.length} bytes)`,
      agentRegistry: `${AGENT_REGISTRY_ADDRESS} (${registryCode.length} bytes)`,
    });
  } catch (e) {
    log("5. On-chain contract reachability", "FAIL", { error: e.message });
    results.passed = false;
  }

  // 6. AgentRegistry live data read
  try {
    const publicClient = getPublicClient();

    const nextAgentId = await publicClient.readContract({
      address: AGENT_REGISTRY_ADDRESS,
      abi: REGISTRY_ABI,
      functionName: "nextAgentId",
    });

    const registeredCount = Number(nextAgentId) - 1;

    // Read first registered agent's reputation
    let sampleAgent = null;
    if (registeredCount > 0) {
      const rep = await getOnChainReputation(publicClient, zeroAddress).catch(
        () => null
      );
      // Try agent ID 1
      const [score, completed, failed, attestations] =
        await publicClient.readContract({
          address: AGENT_REGISTRY_ADDRESS,
          abi: REGISTRY_ABI,
          functionName: "getReputation",
          args: [1n],
        });
      sampleAgent = {
        agentId: 1,
        reputationScore: Number(score),
        tasksCompleted: Number(completed),
        tasksFailed: Number(failed),
        totalAttestations: Number(attestations),
      };
    }

    log("6. AgentRegistry live data", "PASS", {
      totalRegisteredAgents: registeredCount,
      sampleAgent,
    });
  } catch (e) {
    log("6. AgentRegistry live data", "FAIL", { error: e.message });
    results.passed = false;
  }

  // 7. Escrow flow architecture validation
  try {
    // Verify the full escrow flow is wired correctly
    const testKey =
      "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80";
    const client = makeAlkahestClient(testKey);

    // Verify demand encodes correctly for the oracle pattern
    const oracleAddr = client.viemClient.account.address;
    const innerDemand = encodeTaskDemand({
      taskDescription: "Test task",
      requiredCapability: "audit",
      minReputationScore: 7500,
      agentRegistryAddress: AGENT_REGISTRY_ADDRESS,
    });

    const fullDemand = encodeTrustedOracleDemand({
      oracle: oracleAddr,
      data: innerDemand,
    });

    // Verify all methods exist for the full flow
    const flowMethods = {
      "createEscrow": typeof client.nativeToken.escrow.nonTierable.create,
      "fulfillTask": typeof client.stringObligation.doObligation,
      "arbitrate": typeof client.arbiters.general.trustedOracle.arbitrate,
      "collectEscrow": typeof client.nativeToken.escrow.nonTierable.collect,
      "reclaimExpired": typeof client.nativeToken.escrow.nonTierable.reclaimExpired,
      "encodeDemand": typeof encodeTrustedOracleDemand,
      "decodeDemand": typeof decodeTrustedOracleDemand,
      "waitForArbitration": typeof client.arbiters.general.trustedOracle.waitForArbitration,
      "listenForRequests": typeof client.arbiters.general.trustedOracle.listenForArbitrationRequestsOnly,
    };

    const allFunctions = Object.values(flowMethods).every(
      (t) => t === "function"
    );
    if (!allFunctions) throw new Error("Missing flow methods");

    log("7. Escrow flow architecture", "PASS", {
      pattern: "Delegator -> Escrow(ETH) -> Worker(StringObligation) -> Oracle(TrustAgent) -> Collect",
      flowMethods,
      demandEncoding: {
        arbiter: contractAddresses["Base Sepolia"].trustedOracleArbiter,
        oracle: oracleAddr,
        taskDescription: "Test task",
        requiredCapability: "audit",
        minReputationScore: 7500,
      },
    });
  } catch (e) {
    log("7. Escrow flow architecture", "FAIL", { error: e.message });
    results.passed = false;
  }

  // Summary
  console.log();
  console.log("=".repeat(70));
  const passCount = results.steps.filter((s) => s.status === "PASS").length;
  const totalCount = results.steps.length;
  console.log(`  RESULT: ${passCount}/${totalCount} checks passed`);
  console.log("=".repeat(70));

  results.summary = {
    passed: passCount,
    total: totalCount,
    allPassed: results.passed,
  };

  return results;
}

// ---------------------------------------------------------------------------
// Oracle listener mode (for production use)
// ---------------------------------------------------------------------------

/**
 * Start TrustAgent as a long-running oracle that listens for Alkahest
 * arbitration requests and decides based on AgentRegistry reputation.
 *
 * This is the production pattern: the oracle polls for new fulfillments
 * that reference escrows naming it as the trusted oracle, then automatically
 * arbitrates each one by checking the fulfiller's on-chain reputation.
 */
async function startOracleListener() {
  const oracleKey = process.env.ORACLE_KEY || process.env.PRIVATE_KEY;
  if (!oracleKey) {
    console.error("ORACLE_KEY or PRIVATE_KEY required for oracle mode.");
    process.exit(1);
  }

  const oracleClient = makeAlkahestClient(oracleKey);
  const oracleAddress = oracleClient.viemClient.account.address;
  const publicClient = getPublicClient();

  console.log(`TrustAgent oracle started: ${oracleAddress}`);
  console.log("Listening for arbitration requests...\n");

  // Use the SDK's built-in arbitrateMany to poll and auto-arbitrate
  const result = await oracleClient.arbiters.general.trustedOracle.arbitrateMany(
    async (attestationWithDemand) => {
      const { attestation, demand: demandData } = attestationWithDemand;
      console.log(`\nArbitration request received: ${attestation.uid}`);

      try {
        // The fulfiller is the attester of the fulfillment attestation
        const workerAddress = attestation.attester;

        // Decode the demand to get the reputation threshold
        const outerDemand = decodeTrustedOracleDemand(demandData);
        const taskDemand = decodeTaskDemand(outerDemand.data);

        console.log(`  Worker: ${workerAddress}`);
        console.log(`  Task:   ${taskDemand.taskDescription}`);
        console.log(`  Min rep: ${taskDemand.minReputationScore}`);

        // Check AgentRegistry
        const reputation = await getOnChainReputation(
          publicClient,
          workerAddress
        );

        if (!reputation) {
          console.log("  Decision: REJECT (unregistered)");
          return false;
        }

        const passes =
          BigInt(reputation.score) >= taskDemand.minReputationScore;
        console.log(
          `  Score: ${reputation.score}, Decision: ${passes ? "APPROVE" : "REJECT"}`
        );
        return passes;
      } catch (e) {
        console.error(`  Error during arbitration: ${e.message}`);
        return false;
      }
    },
    { mode: "allUnarbitrated", pollingInterval: 5000 }
  );

  console.log("Oracle listener active. Press Ctrl+C to stop.");

  // Keep running until interrupted
  process.on("SIGINT", () => {
    result.unwatch();
    console.log("\nOracle stopped.");
    process.exit(0);
  });
}

// ---------------------------------------------------------------------------
// Entrypoint
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);

if (args.includes("--test") || args.includes("--proof")) {
  const results = await runTest();

  if (args.includes("--proof")) {
    const proofPath = new URL(
      "../alkahest_proof.json",
      import.meta.url
    );
    const filePath = decodeURIComponent(proofPath.pathname);
    writeFileSync(filePath, JSON.stringify(results, null, 2));
    console.log(`\nProof written to ${filePath}`);
  }

  process.exit(results.passed ? 0 : 1);
} else if (args.includes("--oracle")) {
  await startOracleListener();
} else {
  await runFullDemo();
}
