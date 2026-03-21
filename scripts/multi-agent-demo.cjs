/**
 * multi-agent-demo.cjs
 *
 * Demonstrates TrustAgent's multi-agent coordination on Base Sepolia:
 *   1. Registers 2 new agents (ResearchAgent, AuditorAgent) from fresh wallets
 *   2. Creates a delegation from ResearchAgent → AuditorAgent
 *   3. AuditorAgent attests to ResearchAgent's task completion
 *   4. Queries reputation, discovery, and delegation status
 *
 * Uses manual nonce handling throughout to avoid race conditions.
 *
 * Run: npx hardhat --config hardhat.config.cjs run scripts/multi-agent-demo.cjs --network baseSepolia
 */
const hre = require("hardhat");

const CONTRACT = "0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98";

async function main() {
  const provider = hre.ethers.provider;
  const [deployer] = await hre.ethers.getSigners();
  const ar = await hre.ethers.getContractAt("AgentRegistry", CONTRACT);

  console.log("╔══════════════════════════════════════════════════════╗");
  console.log("║   TrustAgent Multi-Agent Onchain Demo (Base Sepolia)  ║");
  console.log("╚══════════════════════════════════════════════════════╝\n");
  console.log("Deployer:", deployer.address);

  // ── 0. Create & fund two fresh wallets ──────────────────────────
  const wallet2 = hre.ethers.Wallet.createRandom().connect(provider);
  const wallet3 = hre.ethers.Wallet.createRandom().connect(provider);

  console.log("\n[0] Funding two fresh wallets...");
  let deployerNonce = await provider.getTransactionCount(deployer.address, "latest");

  const fundAmt = hre.ethers.parseEther("0.0004");
  const tx1 = await deployer.sendTransaction({ to: wallet2.address, value: fundAmt, nonce: deployerNonce });
  const tx2 = await deployer.sendTransaction({ to: wallet3.address, value: fundAmt, nonce: deployerNonce + 1 });
  await Promise.all([tx1.wait(), tx2.wait()]);
  console.log("   Funded wallet2:", wallet2.address, "TX:", tx1.hash);
  console.log("   Funded wallet3:", wallet3.address, "TX:", tx2.hash);

  // ── 1. Register ResearchAgent from wallet2 ─────────────────────
  console.log("\n[1] Registering ResearchAgent...");
  const ar2 = ar.connect(wallet2);
  let nonce2 = await provider.getTransactionCount(wallet2.address, "latest");
  const regTx1 = await ar2.registerAgent(
    "ResearchAgent",
    "research.trustagent.eth",
    ["research", "data-analysis", "public-goods-eval"],
    { nonce: nonce2 }
  );
  const regRcpt1 = await regTx1.wait();
  const regEvent1 = regRcpt1.logs.find(l => {
    try { return ar.interface.parseLog(l)?.name === "AgentRegistered"; } catch { return false; }
  });
  const researchAgentId = regEvent1 ? ar.interface.parseLog(regEvent1).args[0] : null;
  console.log("   TX:", regRcpt1.hash);
  console.log("   Agent ID:", researchAgentId?.toString());

  // ── 2. Register AuditorAgent from wallet3 ──────────────────────
  console.log("\n[2] Registering AuditorAgent...");
  const ar3 = ar.connect(wallet3);
  let nonce3 = await provider.getTransactionCount(wallet3.address, "latest");
  const regTx2 = await ar3.registerAgent(
    "AuditorAgent",
    "auditor.trustagent.eth",
    ["audit", "verification", "public-goods-eval"],
    { nonce: nonce3 }
  );
  const regRcpt2 = await regTx2.wait();
  const regEvent2 = regRcpt2.logs.find(l => {
    try { return ar.interface.parseLog(l)?.name === "AgentRegistered"; } catch { return false; }
  });
  const auditorAgentId = regEvent2 ? ar.interface.parseLog(regEvent2).args[0] : null;
  console.log("   TX:", regRcpt2.hash);
  console.log("   Agent ID:", auditorAgentId?.toString());

  // ── 3. Delegation: ResearchAgent → AuditorAgent ────────────────
  console.log("\n[3] Creating delegation: ResearchAgent → AuditorAgent...");
  nonce2 = await provider.getTransactionCount(wallet2.address, "latest");
  const permissions = [
    hre.ethers.id("VERIFY_DATA"),
    hre.ethers.id("AUDIT_REPORT"),
  ];
  const delegTx = await ar2.delegate(auditorAgentId, permissions, 86400, { nonce: nonce2 });
  const delegRcpt = await delegTx.wait();
  const delegEvent = delegRcpt.logs.find(l => {
    try { return ar.interface.parseLog(l)?.name === "DelegationCreated"; } catch { return false; }
  });
  const delegationId = delegEvent ? ar.interface.parseLog(delegEvent).args[0] : null;
  console.log("   TX:", delegRcpt.hash);
  console.log("   Delegation ID:", delegationId?.toString());
  console.log("   Permissions: VERIFY_DATA, AUDIT_REPORT");
  console.log("   Duration: 24 hours");

  // ── 4. Attestation: AuditorAgent attests ResearchAgent task ────
  console.log("\n[4] AuditorAgent attests ResearchAgent completed task #1001...");
  nonce3 = await provider.getTransactionCount(wallet3.address, "latest");
  const attestTx = await ar3.attestCompletion(researchAgentId, 1001, 9, "Excellent public goods research", { nonce: nonce3 });
  const attestRcpt = await attestTx.wait();
  console.log("   TX:", attestRcpt.hash);

  // ── 5. Query on-chain state ────────────────────────────────────
  console.log("\n[5] Querying on-chain state...");
  const total = await ar.totalAgents();
  console.log("   Total agents registered:", total.toString());

  const [score, completed, failed, attestCount] = await ar.getReputation(researchAgentId);
  console.log("   ResearchAgent reputation:", score.toString(), "/ 10000");
  console.log("   Tasks completed:", completed.toString(), "| failed:", failed.toString());

  const pgAgents = await ar.discoverByCapability("public-goods-eval");
  console.log("   Agents with 'public-goods-eval':", pgAgents.length);

  const active = await ar.isDelegationActive(delegationId);
  console.log("   Delegation", delegationId?.toString(), "active:", active);

  // ── Summary ────────────────────────────────────────────────────
  console.log("\n╔══════════════════════════════════════════════════════╗");
  console.log("║                   DEMO SUMMARY                       ║");
  console.log("╠══════════════════════════════════════════════════════╣");
  console.log("║ Fund wallet2      :", tx1.hash);
  console.log("║ Fund wallet3      :", tx2.hash);
  console.log("║ Register Research :", regRcpt1.hash);
  console.log("║ Register Auditor  :", regRcpt2.hash);
  console.log("║ Delegation        :", delegRcpt.hash);
  console.log("║ Attestation       :", attestRcpt.hash);
  console.log("╚══════════════════════════════════════════════════════╝");
  console.log("\nExplorer: https://sepolia.basescan.org/address/" + CONTRACT);
}

main().catch(e => { console.error("ERROR:", e.message); process.exit(1); });
