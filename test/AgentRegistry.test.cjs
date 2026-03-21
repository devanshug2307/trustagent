const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("AgentRegistry", function () {
  let registry;
  let owner, agent1, agent2, agent3;

  beforeEach(async function () {
    [owner, agent1, agent2, agent3] = await ethers.getSigners();
    const AgentRegistry = await ethers.getContractFactory("AgentRegistry");
    registry = await AgentRegistry.deploy();
  });

  describe("Agent Registration", function () {
    it("should register a new agent", async function () {
      await registry.connect(agent1).registerAgent("AnalystBot", "analyst.eth", ["analysis"]);
      const a = await registry.agents(1);
      expect(a.name).to.equal("AnalystBot");
      expect(a.wallet).to.equal(agent1.address);
      expect(a.active).to.be.true;
      expect(a.reputationScore).to.equal(5000);
    });

    it("should emit AgentRegistered event", async function () {
      await expect(registry.connect(agent1).registerAgent("Bot", "b.eth", ["x"]))
        .to.emit(registry, "AgentRegistered");
    });

    it("should prevent double registration", async function () {
      await registry.connect(agent1).registerAgent("B1", "b1.eth", ["a"]);
      await expect(registry.connect(agent1).registerAgent("B2", "b2.eth", ["b"]))
        .to.be.revertedWith("Already registered");
    });

    it("should register multiple agents", async function () {
      await registry.connect(agent1).registerAgent("B1", "b1.eth", ["a"]);
      await registry.connect(agent2).registerAgent("B2", "b2.eth", ["b"]);
      await registry.connect(agent3).registerAgent("B3", "b3.eth", ["c"]);
      expect(await registry.totalAgents()).to.equal(4); // nextAgentId starts at 1, so 4 after 3 registrations
    });

    it("should index capabilities", async function () {
      await registry.connect(agent1).registerAgent("T", "t.eth", ["trading", "defi"]);
      await registry.connect(agent2).registerAgent("A", "a.eth", ["analysis", "defi"]);
      expect((await registry.discoverByCapability("defi")).length).to.equal(2);
      expect((await registry.discoverByCapability("trading")).length).to.equal(1);
    });
  });

  describe("Reputation System", function () {
    beforeEach(async function () {
      await registry.connect(agent1).registerAgent("Provider", "p.eth", ["svc"]);
      await registry.connect(agent2).registerAgent("Client", "c.eth", ["buy"]);
      await registry.connect(agent3).registerAgent("Verifier", "v.eth", ["audit"]);
    });

    it("should update reputation on positive attestation", async function () {
      await registry.connect(agent2).attestCompletion(1, 100, 8, "Great");
      const [score, completed, failed] = await registry.getReputation(1);
      expect(completed).to.equal(1);
      expect(failed).to.equal(0);
      expect(score).to.equal(10000);
    });

    it("should update reputation on negative attestation", async function () {
      await registry.connect(agent2).attestCompletion(1, 100, 3, "Poor");
      const [score, , failed] = await registry.getReputation(1);
      expect(failed).to.equal(1);
      expect(score).to.equal(0);
    });

    it("should calculate blended reputation (75%)", async function () {
      await registry.connect(agent2).attestCompletion(1, 1, 9, "Great");
      await registry.connect(agent3).attestCompletion(1, 2, 7, "Good");
      await registry.connect(agent2).attestCompletion(1, 3, 8, "Nice");
      await registry.connect(agent3).attestCompletion(1, 4, 2, "Bad");
      const [score, completed, failed, total] = await registry.getReputation(1);
      expect(completed).to.equal(3);
      expect(failed).to.equal(1);
      expect(score).to.equal(7500);
      expect(total).to.equal(4);
    });

    it("should prevent self-attestation", async function () {
      await expect(registry.connect(agent1).attestCompletion(1, 1, 8, "Self"))
        .to.be.revertedWith("Cannot self-attest");
    });

    it("should reject invalid scores", async function () {
      await expect(registry.connect(agent2).attestCompletion(1, 1, 0, "Zero"))
        .to.be.revertedWith("Score must be 1-10");
      await expect(registry.connect(agent2).attestCompletion(1, 1, 11, "High"))
        .to.be.revertedWith("Score must be 1-10");
    });

    it("should emit AttestationCreated", async function () {
      await expect(registry.connect(agent2).attestCompletion(1, 1, 8, "OK"))
        .to.emit(registry, "AttestationCreated");
    });

    it("should emit ReputationUpdated", async function () {
      await expect(registry.connect(agent2).attestCompletion(1, 1, 8, "OK"))
        .to.emit(registry, "ReputationUpdated");
    });
  });

  describe("Delegation Protocol", function () {
    beforeEach(async function () {
      await registry.connect(agent1).registerAgent("Del", "d.eth", ["admin"]);
      await registry.connect(agent2).registerAgent("Dee", "e.eth", ["exec"]);
    });

    it("should create delegation", async function () {
      await registry.connect(agent1).delegate(2, [ethers.id("READ")], 3600);
      const d = await registry.delegations(0);
      expect(d.fromAgentId).to.equal(1);
      expect(d.toAgentId).to.equal(2);
      expect(d.revoked).to.be.false;
    });

    it("should check active delegation", async function () {
      await registry.connect(agent1).delegate(2, [ethers.id("READ")], 3600);
      expect(await registry.isDelegationActive(0)).to.be.true;
    });

    it("should revoke delegation", async function () {
      await registry.connect(agent1).delegate(2, [ethers.id("READ")], 3600);
      await registry.connect(agent1).revokeDelegation(0);
      expect(await registry.isDelegationActive(0)).to.be.false;
    });

    it("should reject revocation by non-delegator", async function () {
      await registry.connect(agent1).delegate(2, [ethers.id("READ")], 3600);
      await expect(registry.connect(agent2).revokeDelegation(0)).to.be.revertedWith("Not delegator");
    });

    it("should reject double revocation", async function () {
      await registry.connect(agent1).delegate(2, [ethers.id("READ")], 3600);
      await registry.connect(agent1).revokeDelegation(0);
      await expect(registry.connect(agent1).revokeDelegation(0)).to.be.revertedWith("Already revoked");
    });

    it("should emit DelegationCreated", async function () {
      await expect(registry.connect(agent1).delegate(2, [ethers.id("READ")], 3600))
        .to.emit(registry, "DelegationCreated");
    });

    it("should emit DelegationRevoked", async function () {
      await registry.connect(agent1).delegate(2, [ethers.id("READ")], 3600);
      await expect(registry.connect(agent1).revokeDelegation(0))
        .to.emit(registry, "DelegationRevoked").withArgs(0);
    });
  });

  describe("Agent Discovery", function () {
    beforeEach(async function () {
      await registry.connect(agent1).registerAgent("T", "t.eth", ["trading", "defi", "arb"]);
      await registry.connect(agent2).registerAgent("A", "a.eth", ["analysis", "defi"]);
      await registry.connect(agent3).registerAgent("M", "m.eth", ["monitor", "defi"]);
    });

    it("should find all defi agents", async function () {
      expect((await registry.discoverByCapability("defi")).length).to.equal(3);
    });

    it("should return empty for unknown", async function () {
      expect((await registry.discoverByCapability("unknown")).length).to.equal(0);
    });

    it("should find specific capability", async function () {
      const arb = await registry.discoverByCapability("arb");
      expect(arb.length).to.equal(1);
      expect(arb[0]).to.equal(1);
    });
  });

  describe("Full Lifecycle", function () {
    it("should handle register -> discover -> delegate -> attest -> revoke", async function () {
      await registry.connect(agent1).registerAgent("SP", "sp.eth", ["portfolio"]);
      await registry.connect(agent2).registerAgent("SC", "sc.eth", ["trading"]);

      const found = await registry.discoverByCapability("portfolio");
      expect(found.length).to.equal(1);

      let [score] = await registry.getReputation(1);
      expect(score).to.equal(5000);

      await registry.connect(agent2).delegate(1, [ethers.id("READ")], 86400);
      expect(await registry.isDelegationActive(0)).to.be.true;

      await registry.connect(agent2).attestCompletion(1, 1, 9, "Excellent");
      [score] = await registry.getReputation(1);
      expect(score).to.equal(10000);

      await registry.connect(agent2).revokeDelegation(0);
      expect(await registry.isDelegationActive(0)).to.be.false;
    });
  });
});
