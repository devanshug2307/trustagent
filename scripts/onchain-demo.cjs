const hre = require("hardhat");
async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const ar = await hre.ethers.getContractAt("AgentRegistry", "0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98");
  console.log("Running TrustAgent onchain demo...\n");

  // Register Agent 1
  console.log("[1] Registering AnalystAgent...");
  let tx = await ar.registerAgent("AnalystAgent", "analyst.trustagent.eth", ["portfolio-analysis", "market-research", "defi"]);
  let r = await tx.wait();
  console.log("   TX:", r.hash);

  // Register Agent 2 (from same wallet since we only have one)
  // Instead, do attestation and delegation demos
  console.log("\n[2] Checking total agents...");
  const total = await ar.totalAgents();
  console.log("   Total registered:", total.toString());

  // Check reputation
  console.log("\n[3] Checking reputation of Agent 1...");
  const [score, completed, failed, attestCount] = await ar.getReputation(1);
  console.log("   Score:", score.toString(), "/ 10000");
  console.log("   Tasks completed:", completed.toString());
  console.log("   Tasks failed:", failed.toString());

  // Discover by capability
  console.log("\n[4] Discovering agents with 'defi' capability...");
  const defiAgents = await ar.discoverByCapability("defi");
  console.log("   Found:", defiAgents.length, "agents");

  console.log("\n=== TrustAgent Onchain Demo Complete ===");
  console.log("AgentRegistry:", "0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98");
  console.log("Explorer: https://sepolia.basescan.org/address/0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98");
}
main().catch(e => { console.error(e.message); process.exit(1); });
