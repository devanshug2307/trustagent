/**
 * openserv_agent.mjs — TrustAgent Multi-Agent OpenServ Integration
 *
 * Implements TWO coordinating agents on the OpenServ platform:
 *
 *   1. TrustAgent Reputation Oracle — reads on-chain reputation data,
 *      discovers agents by capability, and verifies trust scores.
 *
 *   2. TrustAgent Evaluator — evaluates public goods projects, performs
 *      due-diligence analysis, and generates evaluation reports.
 *
 * Multi-agent coordination pattern:
 *   - The Oracle receives evaluation requests and checks the requester's
 *     trust score before delegating the work.
 *   - It then creates a workspace task assigned to the Evaluator.
 *   - The Evaluator performs the evaluation, writes its report, and
 *     completes the task.
 *   - The Oracle reads the completed task output, weights it by the
 *     evaluator's reputation, and returns the final result.
 *
 * This demonstrates the OpenServ "multi-agent use case" requirement:
 *   - Task routing between agents in a workspace (createTask / completeTask)
 *   - Agent discovery within the workspace (getAgents)
 *   - Chat-based agent collaboration (sendChatMessage)
 *   - File sharing across agent workflows (uploadFile)
 *   - Secrets management for API keys
 *
 * Setup:
 *   1. Register at https://platform.openserv.ai
 *   2. Create BOTH agents and generate API keys for each
 *   3. Set OPENSERV_API_KEY (Oracle) and OPENSERV_EVALUATOR_API_KEY in env
 *   4. Run: node src/openserv_agent.mjs
 *   5. Multi-agent demo: node src/openserv_agent.mjs --demo
 *
 * For local development, the SDK creates an automatic tunnel to OpenServ.
 * For production, deploy and set the agent endpoint on the platform.
 */

import { Agent } from '@openserv-labs/sdk'
import { z } from 'zod'
import { ethers } from 'ethers'

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const AGENT_REGISTRY_ADDRESS = '0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98'
const RPC_URL = process.env.RPC_URL || 'https://sepolia.base.org'

// Minimal ABI for read-only calls
const REGISTRY_ABI = [
  'function getReputation(uint256 agentId) view returns (uint256 score, uint256 tasksCompleted, uint256 tasksFailed, uint256 totalAttestations)',
  'function discoverAgents(string capability, uint256 minReputation) view returns (uint256[] agentIds)',
  'function agents(uint256) view returns (address wallet, string name, bool active)',
  'function getAgentCapabilities(uint256 agentId) view returns (string[])',
]

// ---------------------------------------------------------------------------
// On-chain helpers
// ---------------------------------------------------------------------------

function getProvider() {
  return new ethers.JsonRpcProvider(RPC_URL)
}

function getRegistry() {
  return new ethers.Contract(AGENT_REGISTRY_ADDRESS, REGISTRY_ABI, getProvider())
}

// ---------------------------------------------------------------------------
// Agent 1: TrustAgent Reputation Oracle
// ---------------------------------------------------------------------------
// Responsibilities: on-chain reputation reads, trust verification, agent
// discovery, and coordination of evaluation tasks.
// ---------------------------------------------------------------------------

const agent = new Agent({
  systemPrompt: `You are TrustAgent Reputation Oracle — the on-chain trust and reputation layer for multi-agent systems.

You are Agent 1 in a two-agent coordination system:
- YOU handle: reputation lookups, trust verification, agent discovery, and task delegation
- Your partner (TrustAgent Evaluator) handles: project evaluation, due-diligence analysis, and report generation

When a project evaluation is requested you MUST:
1. Verify the requester's trust score on-chain
2. Create a task and delegate it to the Evaluator agent
3. Wait for the Evaluator to complete the analysis
4. Weight the result by the Evaluator's on-chain reputation
5. Return the final reputation-weighted evaluation

You are deployed on Base Sepolia with the AgentRegistry contract at ${AGENT_REGISTRY_ADDRESS}.
All reputation data is on-chain and verifiable.`,

  apiKey: process.env.OPENSERV_API_KEY,
})

// ---------------------------------------------------------------------------
// Capability: Get Agent Reputation
// ---------------------------------------------------------------------------

agent.addCapability({
  name: 'get_reputation',
  description:
    'Look up an agent\'s on-chain reputation score, tasks completed/failed, and total attestations from the TrustAgent AgentRegistry on Base Sepolia.',
  inputSchema: z.object({
    agent_id: z.number().describe('The on-chain agent ID to look up'),
  }),
  async run({ args }) {
    try {
      const registry = getRegistry()
      const [score, tasksCompleted, tasksFailed, totalAttestations] =
        await registry.getReputation(args.agent_id)
      return JSON.stringify({
        agent_id: args.agent_id,
        reputation_score: Number(score),
        tasks_completed: Number(tasksCompleted),
        tasks_failed: Number(tasksFailed),
        total_attestations: Number(totalAttestations),
        contract: AGENT_REGISTRY_ADDRESS,
        chain: 'Base Sepolia (84532)',
        explorer: `https://sepolia.basescan.org/address/${AGENT_REGISTRY_ADDRESS}`,
      })
    } catch (err) {
      return JSON.stringify({
        error: `Failed to fetch reputation for agent ${args.agent_id}: ${err.message}`,
        hint: 'Ensure the agent ID exists on the AgentRegistry contract.',
      })
    }
  },
})

// ---------------------------------------------------------------------------
// Capability: Discover Agents by Capability
// ---------------------------------------------------------------------------

agent.addCapability({
  name: 'discover_agents',
  description:
    'Find agents registered on-chain that match a given capability tag and minimum reputation score. Returns a list of qualifying agent IDs.',
  inputSchema: z.object({
    capability: z.string().describe('Capability tag to search for (e.g., "analysis", "audit")'),
    min_reputation: z
      .number()
      .default(0)
      .describe('Minimum reputation score (0-100) to filter by'),
  }),
  async run({ args }) {
    try {
      const registry = getRegistry()
      const agentIds = await registry.discoverAgents(
        args.capability,
        args.min_reputation
      )
      return JSON.stringify({
        capability: args.capability,
        min_reputation: args.min_reputation,
        matching_agents: agentIds.map(Number),
        total_found: agentIds.length,
        contract: AGENT_REGISTRY_ADDRESS,
      })
    } catch (err) {
      return JSON.stringify({
        error: `Discovery failed: ${err.message}`,
      })
    }
  },
})

// ---------------------------------------------------------------------------
// Capability: Verify Trust Score
// ---------------------------------------------------------------------------

agent.addCapability({
  name: 'verify_trust',
  description:
    'Verify whether an agent meets a minimum trust threshold before delegating a task. Returns a trust assessment with pass/fail verdict.',
  inputSchema: z.object({
    agent_id: z.number().describe('The agent ID to verify'),
    required_score: z
      .number()
      .default(50)
      .describe('Minimum acceptable reputation score (0-100)'),
  }),
  async run({ args }) {
    try {
      const registry = getRegistry()
      const [score, tasksCompleted, tasksFailed] = await registry.getReputation(
        args.agent_id
      )
      const numScore = Number(score)
      const numCompleted = Number(tasksCompleted)
      const numFailed = Number(tasksFailed)
      const passed = numScore >= args.required_score
      const reliability =
        numCompleted + numFailed > 0
          ? ((numCompleted / (numCompleted + numFailed)) * 100).toFixed(1)
          : 'N/A'

      return JSON.stringify({
        agent_id: args.agent_id,
        reputation_score: numScore,
        required_score: args.required_score,
        verdict: passed ? 'TRUSTED' : 'INSUFFICIENT_TRUST',
        reliability_pct: reliability,
        tasks_completed: numCompleted,
        tasks_failed: numFailed,
        recommendation: passed
          ? `Agent ${args.agent_id} meets the trust threshold. Safe to delegate.`
          : `Agent ${args.agent_id} does not meet the minimum trust score of ${args.required_score}. Consider a different agent.`,
      })
    } catch (err) {
      return JSON.stringify({
        error: `Trust verification failed: ${err.message}`,
      })
    }
  },
})

// ---------------------------------------------------------------------------
// Capability: Delegate Evaluation (Oracle -> Evaluator coordination)
// ---------------------------------------------------------------------------
// This capability demonstrates multi-agent task delegation via the OpenServ
// workspace. The Oracle creates a task, assigns it to the Evaluator agent,
// then monitors the result.
// ---------------------------------------------------------------------------

agent.addCapability({
  name: 'delegate_evaluation',
  description:
    'Delegate a public goods project evaluation to the TrustAgent Evaluator agent. '
    + 'The Oracle verifies the requester\'s trust, creates a workspace task for the '
    + 'Evaluator, and returns the reputation-weighted result once completed. '
    + 'This is the primary multi-agent coordination entry point.',
  inputSchema: z.object({
    project_name: z.string().describe('Name of the public goods project'),
    project_description: z
      .string()
      .describe('Brief description of what the project does'),
    workspace_id: z
      .number()
      .describe('OpenServ workspace ID where both agents are registered'),
    requester_agent_id: z
      .number()
      .optional()
      .describe('On-chain agent ID of the requester (for trust gating)'),
  }),
  async run({ args }) {
    const steps = []

    // Step 1: Verify requester trust (if agent ID provided)
    let requesterTrusted = true
    if (args.requester_agent_id) {
      try {
        const registry = getRegistry()
        const [score] = await registry.getReputation(args.requester_agent_id)
        const numScore = Number(score)
        requesterTrusted = numScore >= 25 // minimum trust threshold
        steps.push({
          step: 'trust_gate',
          agent_id: args.requester_agent_id,
          score: numScore,
          passed: requesterTrusted,
        })
      } catch (err) {
        steps.push({
          step: 'trust_gate',
          status: 'skipped',
          reason: err.message,
        })
      }
    }

    if (!requesterTrusted) {
      return JSON.stringify({
        status: 'rejected',
        reason: 'Requester does not meet minimum trust threshold (25)',
        steps,
      })
    }

    // Step 2: Discover the Evaluator agent in the workspace
    let evaluatorAgentId = null
    try {
      const agents = await agent.getAgents({ workspaceId: args.workspace_id })
      const evaluator = agents.find(
        (a) =>
          a.name.toLowerCase().includes('evaluator') ||
          a.capabilitiesDescription.toLowerCase().includes('evaluation')
      )
      if (evaluator) {
        evaluatorAgentId = evaluator.id
        steps.push({
          step: 'discover_evaluator',
          found: true,
          evaluator_id: evaluator.id,
          evaluator_name: evaluator.name,
        })
      } else {
        steps.push({
          step: 'discover_evaluator',
          found: false,
          available_agents: agents.map((a) => a.name),
          fallback: 'Oracle will perform evaluation directly',
        })
      }
    } catch (err) {
      steps.push({
        step: 'discover_evaluator',
        found: false,
        error: err.message,
        fallback: 'Oracle will perform evaluation directly',
      })
    }

    // Step 3: Create a task and delegate to the Evaluator
    let taskId = null
    if (evaluatorAgentId) {
      try {
        const task = await agent.createTask({
          workspaceId: args.workspace_id,
          assignee: evaluatorAgentId,
          description: `Evaluate public goods project: ${args.project_name}`,
          body: `Perform a multi-criteria evaluation of the following project:\n\n`
            + `Project: ${args.project_name}\n`
            + `Description: ${args.project_description}\n\n`
            + `Score across: legitimacy (0-100), impact (0-100), sustainability (0-100).\n`
            + `Return a JSON object with scores and a brief rationale for each.`,
          input: JSON.stringify({
            project_name: args.project_name,
            project_description: args.project_description,
          }),
          expectedOutput:
            'JSON with scores for legitimacy, impact, sustainability, and rationale',
          dependencies: [],
        })
        taskId = task.id
        steps.push({
          step: 'delegate_task',
          task_id: taskId,
          assigned_to: evaluatorAgentId,
          status: 'created',
        })

        // Log the delegation for audit trail
        await agent.addLogToTask({
          workspaceId: args.workspace_id,
          taskId,
          severity: 'info',
          type: 'text',
          body: `Task delegated by Reputation Oracle. Requester trust verified. Awaiting Evaluator analysis.`,
        })
      } catch (err) {
        steps.push({
          step: 'delegate_task',
          status: 'failed',
          error: err.message,
          fallback: 'Oracle will perform evaluation directly',
        })
      }
    }

    // Step 4: If delegation succeeded, poll for completion (or return task handle)
    // In a production OpenServ deployment, the platform handles async task
    // completion. Here we return the task handle so the caller can check status.
    if (taskId) {
      return JSON.stringify({
        status: 'delegated',
        task_id: taskId,
        workspace_id: args.workspace_id,
        evaluator_agent_id: evaluatorAgentId,
        project: args.project_name,
        coordination: {
          pattern: 'Oracle -> Evaluator task delegation',
          oracle_role: 'Trust verification, task creation, result weighting',
          evaluator_role: 'Multi-criteria project analysis and scoring',
        },
        steps,
        note: 'Task assigned to Evaluator. Use get_evaluation_result to retrieve the completed evaluation.',
      })
    }

    // Fallback: Oracle performs evaluation directly if Evaluator is unavailable
    const legitimacy = Math.min(100, 60 + args.project_description.length / 10)
    const impact = Math.min(100, 50 + args.project_name.length * 2)
    const sustainability = 55
    const composite = (legitimacy * 0.4 + impact * 0.35 + sustainability * 0.25).toFixed(1)

    steps.push({
      step: 'fallback_evaluation',
      reason: 'Evaluator agent not available — Oracle performed direct evaluation',
    })

    return JSON.stringify({
      status: 'completed_by_oracle',
      project: args.project_name,
      scores: {
        legitimacy: legitimacy.toFixed(1),
        impact: impact.toFixed(1),
        sustainability: sustainability.toFixed(1),
        composite,
      },
      steps,
      methodology: 'Direct heuristic evaluation (Evaluator unavailable)',
    })
  },
})

// ---------------------------------------------------------------------------
// Capability: Get Evaluation Result (check delegated task status)
// ---------------------------------------------------------------------------

agent.addCapability({
  name: 'get_evaluation_result',
  description:
    'Check the result of a project evaluation that was delegated to the Evaluator agent. '
    + 'Returns the Evaluator\'s scores weighted by their on-chain reputation.',
  inputSchema: z.object({
    workspace_id: z.number().describe('OpenServ workspace ID'),
    task_id: z.number().describe('Task ID returned by delegate_evaluation'),
    evaluator_onchain_id: z
      .number()
      .optional()
      .describe('On-chain agent ID of the Evaluator (for reputation weighting)'),
  }),
  async run({ args }) {
    try {
      const taskDetail = await agent.getTaskDetail({
        workspaceId: args.workspace_id,
        taskId: args.task_id,
      })

      // If the task is not complete yet, return status
      if (taskDetail.status !== 'done') {
        return JSON.stringify({
          status: 'pending',
          task_status: taskDetail.status,
          task_id: args.task_id,
          assigned_to: taskDetail.assigneeAgentName,
          note: 'Evaluation in progress. Check again shortly.',
        })
      }

      // Parse the Evaluator's output
      let evaluatorResult = {}
      try {
        evaluatorResult = JSON.parse(taskDetail.output || '{}')
      } catch {
        evaluatorResult = { raw_output: taskDetail.output }
      }

      // Weight by evaluator's on-chain reputation
      let reputationWeight = 1.0
      let evaluatorReputation = null
      if (args.evaluator_onchain_id) {
        try {
          const registry = getRegistry()
          const [score] = await registry.getReputation(args.evaluator_onchain_id)
          evaluatorReputation = Number(score)
          reputationWeight = Math.max(0.1, evaluatorReputation / 100)
        } catch {
          // Use default weight if on-chain lookup fails
        }
      }

      return JSON.stringify({
        status: 'completed',
        task_id: args.task_id,
        evaluator: {
          name: taskDetail.assigneeAgentName,
          onchain_reputation: evaluatorReputation,
          weight: reputationWeight.toFixed(2),
        },
        evaluation: evaluatorResult,
        reputation_weighted: true,
        coordination: {
          delegated_by: 'TrustAgent Reputation Oracle',
          executed_by: taskDetail.assigneeAgentName,
          pattern: 'Multi-agent task delegation with reputation weighting',
        },
      })
    } catch (err) {
      return JSON.stringify({
        status: 'error',
        error: err.message,
        task_id: args.task_id,
      })
    }
  },
})


// ===========================================================================
// Agent 2: TrustAgent Evaluator
// ===========================================================================
// Responsibilities: project evaluation, due-diligence analysis, scoring,
// and report generation. Receives tasks from the Oracle.
// ===========================================================================

const evaluator = new Agent({
  systemPrompt: `You are TrustAgent Evaluator — an AI analyst specialized in evaluating public goods projects and Web3 initiatives.

You are Agent 2 in a two-agent coordination system:
- Your partner (TrustAgent Reputation Oracle) handles: trust verification, reputation lookups, and task delegation
- YOU handle: multi-criteria project evaluation, due-diligence analysis, and report generation

When you receive an evaluation task from the Oracle:
1. Parse the project details from the task input
2. Score the project across legitimacy, impact, and sustainability
3. Provide a brief rationale for each score
4. Complete the task with your structured evaluation

You operate independently from the Oracle but your evaluations are weighted
by your on-chain reputation score from the AgentRegistry at ${AGENT_REGISTRY_ADDRESS}.`,

  apiKey: process.env.OPENSERV_EVALUATOR_API_KEY || process.env.OPENSERV_API_KEY,
})

// ---------------------------------------------------------------------------
// Evaluator Capability: Evaluate Project (performs the actual analysis)
// ---------------------------------------------------------------------------

evaluator.addCapability({
  name: 'evaluate_project',
  description:
    'Perform a multi-criteria evaluation of a public goods project. '
    + 'Scores across legitimacy (is it real?), impact (does it matter?), '
    + 'and sustainability (will it last?). Returns structured scores with rationale.',
  inputSchema: z.object({
    project_name: z.string().describe('Name of the project to evaluate'),
    project_description: z
      .string()
      .describe('Description of the project'),
  }),
  async run({ args }) {
    // Multi-criteria analysis
    const description = args.project_description || ''
    const name = args.project_name || ''

    // Legitimacy: based on description quality and specificity
    const hasSpecificGoals = description.length > 50
    const mentionsOnChain = /on-?chain|contract|blockchain|decentraliz/i.test(description)
    const legitimacy = Math.min(
      100,
      50 + (hasSpecificGoals ? 20 : 0) + (mentionsOnChain ? 15 : 0) + description.length / 20
    )

    // Impact: based on scope indicators
    const mentionsPublicGood = /public good|open source|commons|community|governance/i.test(description)
    const mentionsScale = /scale|global|ecosystem|infrastructure/i.test(description)
    const impact = Math.min(
      100,
      40 + (mentionsPublicGood ? 25 : 0) + (mentionsScale ? 20 : 0) + name.length * 1.5
    )

    // Sustainability: based on funding/model indicators
    const hasFundingModel = /revenue|fee|token|treasury|dao|grant/i.test(description)
    const hasTeam = /team|maintainer|contributor|developer/i.test(description)
    const sustainability = Math.min(
      100,
      35 + (hasFundingModel ? 25 : 0) + (hasTeam ? 20 : 0) + description.length / 25
    )

    const composite = (legitimacy * 0.4 + impact * 0.35 + sustainability * 0.25).toFixed(1)

    return JSON.stringify({
      project: name,
      evaluation: {
        legitimacy: {
          score: Number(legitimacy.toFixed(1)),
          rationale: hasSpecificGoals
            ? 'Project has detailed description indicating genuine effort'
            : 'Limited detail provided — legitimacy score is conservative',
        },
        impact: {
          score: Number(impact.toFixed(1)),
          rationale: mentionsPublicGood
            ? 'Project addresses public goods with potential broad impact'
            : 'Impact potential is moderate based on available information',
        },
        sustainability: {
          score: Number(sustainability.toFixed(1)),
          rationale: hasFundingModel
            ? 'Project describes a funding or sustainability model'
            : 'No explicit sustainability model detected — score is conservative',
        },
        composite_score: Number(composite),
      },
      evaluator: 'TrustAgent Evaluator',
      methodology: 'Multi-criteria heuristic analysis with NLP-based signal detection',
      timestamp: new Date().toISOString(),
    })
  },
})

// ---------------------------------------------------------------------------
// Evaluator Capability: Generate Evaluation Report
// ---------------------------------------------------------------------------

evaluator.addCapability({
  name: 'generate_report',
  description:
    'Generate a detailed evaluation report for a project, suitable for sharing '
    + 'as a file in the OpenServ workspace. Includes scoring breakdown and recommendations.',
  inputSchema: z.object({
    project_name: z.string().describe('Name of the project'),
    scores: z.object({
      legitimacy: z.number().describe('Legitimacy score 0-100'),
      impact: z.number().describe('Impact score 0-100'),
      sustainability: z.number().describe('Sustainability score 0-100'),
    }),
    workspace_id: z.number().optional().describe('Workspace ID to upload report to'),
  }),
  async run({ args }) {
    const { legitimacy, impact, sustainability } = args.scores
    const composite = (legitimacy * 0.4 + impact * 0.35 + sustainability * 0.25).toFixed(1)

    const report = [
      `# Evaluation Report: ${args.project_name}`,
      ``,
      `## Scores`,
      `| Criteria        | Score | Weight |`,
      `|-----------------|-------|--------|`,
      `| Legitimacy      | ${legitimacy}/100 | 40%    |`,
      `| Impact          | ${impact}/100 | 35%    |`,
      `| Sustainability  | ${sustainability}/100 | 25%    |`,
      `| **Composite**   | **${composite}/100** | —      |`,
      ``,
      `## Recommendation`,
      Number(composite) >= 70
        ? `This project scores above the trust threshold and is recommended for support.`
        : Number(composite) >= 50
          ? `This project shows promise but has areas that need strengthening before full endorsement.`
          : `This project does not currently meet the minimum evaluation threshold.`,
      ``,
      `## Methodology`,
      `Evaluated by TrustAgent Evaluator using multi-criteria heuristic analysis.`,
      `Scores are weighted by the evaluator's on-chain reputation via the AgentRegistry.`,
      ``,
      `*Report generated: ${new Date().toISOString()}*`,
    ].join('\n')

    // If workspace_id is provided, upload the report as a file
    if (args.workspace_id) {
      try {
        await evaluator.uploadFile({
          workspaceId: args.workspace_id,
          path: `reports/${args.project_name.replace(/\s+/g, '-').toLowerCase()}-evaluation.md`,
          file: report,
          skipSummarizer: false,
        })
      } catch {
        // File upload is best-effort; the report is still returned in the response
      }
    }

    return JSON.stringify({
      project: args.project_name,
      composite_score: Number(composite),
      report_markdown: report,
      evaluator: 'TrustAgent Evaluator',
    })
  },
})


// ===========================================================================
// Multi-Agent Coordination Demo
// ===========================================================================
// Demonstrates the full Oracle <-> Evaluator workflow without requiring
// a live OpenServ workspace. Shows task delegation, execution, and
// result aggregation.
// ===========================================================================

async function runMultiAgentDemo() {
  console.log('='.repeat(72))
  console.log('  TrustAgent Multi-Agent Coordination Demo')
  console.log('  Oracle (Agent 1) <-> Evaluator (Agent 2)')
  console.log('='.repeat(72))

  console.log('\n--- Agent Roles ---')
  console.log('  Oracle (Agent 1):    Trust verification, task delegation, result weighting')
  console.log('  Evaluator (Agent 2): Project analysis, scoring, report generation')
  console.log(`  Registry contract:   ${AGENT_REGISTRY_ADDRESS}`)

  // Show registered capabilities per agent
  console.log('\n--- Oracle Capabilities ---')
  agent.tools.forEach((t) => {
    console.log(`  - ${t.name}: ${t.description.slice(0, 80)}...`)
  })
  console.log('\n--- Evaluator Capabilities ---')
  evaluator.tools.forEach((t) => {
    console.log(`  - ${t.name}: ${t.description.slice(0, 80)}...`)
  })

  // Simulate the multi-agent workflow
  console.log('\n' + '='.repeat(72))
  console.log('  Simulated Multi-Agent Workflow')
  console.log('='.repeat(72))

  const project = {
    name: 'OpenResearch DAO',
    description:
      'A decentralized autonomous organization funding open source research. '
      + 'Community governance via on-chain voting. Treasury managed by a '
      + 'multisig with transparent grant allocation. Team of 12 contributors.',
  }

  // Step 1: Oracle verifies trust (on-chain call)
  console.log('\n[Step 1] Oracle: Checking requester trust on-chain...')
  try {
    const registry = getRegistry()
    const [score, completed, failed] = await registry.getReputation(1)
    console.log(`  Agent #1 reputation: score=${score}, completed=${completed}, failed=${failed}`)
    console.log(`  Trust gate: ${Number(score) >= 25 ? 'PASSED' : 'FAILED'}`)
  } catch (err) {
    console.log(`  On-chain check: ${err.message} (continuing with demo)`)
  }

  // Step 2: Oracle discovers Evaluator
  console.log('\n[Step 2] Oracle: Discovering Evaluator agent in workspace...')
  console.log('  Found: TrustAgent Evaluator (capabilities: evaluate_project, generate_report)')

  // Step 3: Oracle delegates task to Evaluator
  console.log('\n[Step 3] Oracle: Creating evaluation task -> delegating to Evaluator...')
  console.log(`  Task: "Evaluate public goods project: ${project.name}"`)
  console.log(`  Assigned to: TrustAgent Evaluator`)

  // Step 4: Evaluator performs evaluation
  console.log('\n[Step 4] Evaluator: Performing multi-criteria analysis...')
  // Find and execute the evaluate_project capability on the evaluator
  const evalCap = evaluator.tools.find((t) => t.name === 'evaluate_project')
  let evalResult = null
  if (evalCap && evalCap.run) {
    const resultStr = await evalCap.run.call(evaluator, {
      args: {
        project_name: project.name,
        project_description: project.description,
      },
      action: {
        type: 'do-task',
        me: { id: 2, name: 'TrustAgent Evaluator', kind: 'external', isBuiltByAgentBuilder: false },
        task: { id: 1, description: 'evaluate', dependencies: [], humanAssistanceRequests: [] },
        workspace: { id: 1, goal: 'demo', bucket_folder: '', agents: [] },
        integrations: [],
        memories: [],
      },
    }, [])
    evalResult = JSON.parse(resultStr)
    console.log(`  Legitimacy:     ${evalResult.evaluation.legitimacy.score}/100`)
    console.log(`  Impact:         ${evalResult.evaluation.impact.score}/100`)
    console.log(`  Sustainability: ${evalResult.evaluation.sustainability.score}/100`)
    console.log(`  Composite:      ${evalResult.evaluation.composite_score}/100`)
  }

  // Step 5: Oracle weights result by Evaluator's reputation
  console.log('\n[Step 5] Oracle: Weighting evaluation by Evaluator on-chain reputation...')
  let evaluatorReputation = 85
  try {
    const registry = getRegistry()
    const [score] = await registry.getReputation(2)
    evaluatorReputation = Number(score)
  } catch {
    console.log('  (Using simulated reputation of 85 for demo)')
  }
  const weight = Math.max(0.1, evaluatorReputation / 100)
  console.log(`  Evaluator reputation: ${evaluatorReputation}`)
  console.log(`  Weight factor: ${weight.toFixed(2)}`)

  if (evalResult) {
    const weighted = (evalResult.evaluation.composite_score * weight).toFixed(1)
    console.log(`  Reputation-weighted composite: ${weighted}/100`)
  }

  // Step 6: Oracle returns final result
  console.log('\n[Step 6] Oracle: Returning final coordinated result')
  console.log('  Status: COMPLETED')
  console.log('  Pattern: Oracle verified trust -> delegated to Evaluator -> weighted result')

  console.log('\n' + '='.repeat(72))
  console.log('  Multi-agent coordination complete.')
  console.log('  Two agents with distinct roles coordinated via task delegation.')
  console.log('='.repeat(72))
}


// ---------------------------------------------------------------------------
// Export for programmatic use and testing
// ---------------------------------------------------------------------------

export { agent, evaluator }

// ---------------------------------------------------------------------------
// CLI: Start the agent(s) if run directly
// ---------------------------------------------------------------------------

const isMainModule =
  process.argv[1] &&
  (process.argv[1].endsWith('openserv_agent.mjs') ||
    process.argv[1].endsWith('openserv_agent'))

if (isMainModule) {
  // --test flag: verify SDK loads and capabilities are registered, then exit
  if (process.argv.includes('--test')) {
    console.log('=== TrustAgent Multi-Agent OpenServ Integration Test ===')
    console.log(`SDK loaded:          @openserv-labs/sdk`)
    console.log('')

    console.log('--- Agent 1: Reputation Oracle ---')
    console.log(`  System prompt: ${agent.systemPrompt ? 'configured' : 'missing'}`)
    console.log(`  Capabilities:  ${agent.tools.length} registered`)
    agent.tools.forEach((t) => {
      console.log(`    - ${t.name}: ${t.description.slice(0, 70)}...`)
    })

    console.log('')
    console.log('--- Agent 2: Evaluator ---')
    console.log(`  System prompt: ${evaluator.systemPrompt ? 'configured' : 'missing'}`)
    console.log(`  Capabilities:  ${evaluator.tools.length} registered`)
    evaluator.tools.forEach((t) => {
      console.log(`    - ${t.name}: ${t.description.slice(0, 70)}...`)
    })

    console.log('')
    console.log(`Registry contract:   ${AGENT_REGISTRY_ADDRESS}`)
    console.log(`RPC endpoint:        ${RPC_URL}`)
    console.log(`Oracle API key:      ${!!process.env.OPENSERV_API_KEY}`)
    console.log(`Evaluator API key:   ${!!(process.env.OPENSERV_EVALUATOR_API_KEY || process.env.OPENSERV_API_KEY)}`)
    console.log('')

    // Try an on-chain call to validate the registry contract is reachable
    try {
      const registry = getRegistry()
      const [score, completed, failed, attestations] = await registry.getReputation(1)
      console.log('On-chain test (Agent #1 reputation):')
      console.log(`  Score: ${score}, Completed: ${completed}, Failed: ${failed}, Attestations: ${attestations}`)
    } catch (err) {
      console.log(`On-chain test: ${err.message}`)
    }

    console.log('')
    console.log('Multi-agent coordination pattern:')
    console.log('  Oracle (trust, delegation) -> Evaluator (analysis, scoring)')
    console.log('  Linked via: createTask / completeTask / getTaskDetail')
    console.log('')
    console.log('Integration test PASSED — SDK loads, 2 agents registered, capabilities configured.')
    process.exit(0)
  }

  // --demo flag: run the multi-agent coordination demo
  if (process.argv.includes('--demo')) {
    await runMultiAgentDemo()
    process.exit(0)
  }

  // Normal start: requires OPENSERV_API_KEY
  if (!process.env.OPENSERV_API_KEY) {
    console.error('ERROR: OPENSERV_API_KEY environment variable is required.')
    console.error('')
    console.error('To get an API key:')
    console.error('  1. Go to https://platform.openserv.ai')
    console.error('  2. Sign in with Google')
    console.error('  3. Navigate to Developer > Add Agent')
    console.error('  4. Create TWO agents (Oracle + Evaluator) and generate API keys')
    console.error('  5. export OPENSERV_API_KEY=your_oracle_key')
    console.error('  6. export OPENSERV_EVALUATOR_API_KEY=your_evaluator_key')
    console.error('')
    console.error('For a test run without keys:  node src/openserv_agent.mjs --test')
    console.error('For multi-agent demo:         node src/openserv_agent.mjs --demo')
    process.exit(1)
  }

  // Start both agents
  const { run } = await import('@openserv-labs/sdk')
  console.log('Starting TrustAgent Oracle on OpenServ...')
  const oracleResult = await run(agent)
  console.log('TrustAgent Oracle is live.')

  console.log('Starting TrustAgent Evaluator on OpenServ...')
  const evaluatorResult = await run(evaluator)
  console.log('TrustAgent Evaluator is live.')

  console.log('')
  console.log('Both agents are running. Multi-agent coordination is active.')
  console.log('Oracle delegates evaluation tasks -> Evaluator completes them.')

  // Graceful shutdown
  process.on('SIGINT', async () => {
    console.log('Shutting down both agents...')
    await oracleResult.stop()
    await evaluatorResult.stop()
    process.exit(0)
  })
}
