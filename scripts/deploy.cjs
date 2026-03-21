const hre = require("hardhat");
async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying AgentRegistry to Base Sepolia with:", deployer.address);
  const AR = await hre.ethers.getContractFactory("AgentRegistry");
  const ar = await AR.deploy();
  await ar.waitForDeployment();
  const addr = await ar.getAddress();
  console.log("AgentRegistry deployed to:", addr);
  console.log("Explorer:", "https://sepolia.basescan.org/address/" + addr);

  // Demo: register an agent
  console.log("\nRegistering demo agent...");
  const tx = await ar.registerAgent("TrustAgent-Demo", "trustagent.eth", ["identity", "reputation", "delegation", "discovery"]);
  const receipt = await tx.wait();
  console.log("Agent registered! TX:", receipt.hash);
}
main().catch(e => { console.error(e.message); process.exit(1); });
