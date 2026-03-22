"""
public_goods_evaluator.py — TrustAgent Public Goods Evaluation Module

Evaluates public goods projects using reputation-weighted scoring across
three dimensions aligned with Octant's tracks:

  1. Mechanism Design  — Legitimacy scoring (is the project real and well-structured?)
  2. Data Analysis     — Impact scoring (what measurable impact does the project have?)
  3. Data Collection   — Sustainability scoring (can the project sustain itself?)

Evaluator credibility is weighted by their on-chain TrustAgent reputation score,
so higher-reputation agents have more influence on the final allocation ranking.

Usage:
    evaluator = PublicGoodsEvaluator(registry_address, rpc_url)
    projects  = [
        {"name": "OpenLib",   "category": "education",      "funding_requested": 10000, ...},
        {"name": "CleanDAO",  "category": "climate",         "funding_requested": 25000, ...},
    ]
    evaluations = [
        {"evaluator_agent_id": 2, "project": "OpenLib",  "legitimacy": 8, "impact": 7, "sustainability": 6},
        {"evaluator_agent_id": 3, "project": "OpenLib",  "legitimacy": 9, "impact": 8, "sustainability": 7},
        ...
    ]
    ranking = evaluator.rank_projects(projects, evaluations, total_budget=50000)
"""

from __future__ import annotations

import json
import math
import ssl
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# ABI fragment for the AgentRegistry functions we need
# ---------------------------------------------------------------------------
REGISTRY_ABI = json.loads("""[
  {
    "inputs": [{"internalType":"uint256","name":"agentId","type":"uint256"}],
    "name": "getReputation",
    "outputs": [
      {"internalType":"uint256","name":"score","type":"uint256"},
      {"internalType":"uint256","name":"completed","type":"uint256"},
      {"internalType":"uint256","name":"failed","type":"uint256"},
      {"internalType":"uint256","name":"totalAttestations","type":"uint256"}
    ],
    "stateMutability": "view",
    "type": "function"
  },
  {
    "inputs": [{"internalType":"uint256","name":"","type":"uint256"}],
    "name": "agents",
    "outputs": [
      {"internalType":"uint256","name":"id","type":"uint256"},
      {"internalType":"address","name":"wallet","type":"address"},
      {"internalType":"string","name":"name","type":"string"},
      {"internalType":"string","name":"ensName","type":"string"},
      {"internalType":"uint256","name":"registeredAt","type":"uint256"},
      {"internalType":"uint256","name":"reputationScore","type":"uint256"},
      {"internalType":"uint256","name":"tasksCompleted","type":"uint256"},
      {"internalType":"uint256","name":"tasksFailed","type":"uint256"},
      {"internalType":"bool","name":"active","type":"bool"}
    ],
    "stateMutability": "view",
    "type": "function"
  },
  {
    "inputs": [{"internalType":"string","name":"capability","type":"string"}],
    "name": "discoverByCapability",
    "outputs": [{"internalType":"uint256[]","name":"","type":"uint256[]"}],
    "stateMutability": "view",
    "type": "function"
  }
]""")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Project:
    """A public goods project to be evaluated."""
    name: str
    category: str
    funding_requested: float
    description: str = ""
    url: str = ""
    team_size: int = 1
    months_active: int = 0
    github_stars: int = 0
    users_served: int = 0


@dataclass
class Evaluation:
    """A single evaluator's assessment of a project."""
    evaluator_agent_id: int
    project_name: str
    legitimacy: int        # 1-10: team verification, track record, transparency
    impact: int            # 1-10: measurable outcomes, user reach, ecosystem value
    sustainability: int    # 1-10: revenue model, community, long-term viability


@dataclass
class ScoredProject:
    """Final scored result for a project."""
    name: str
    category: str
    funding_requested: float
    weighted_legitimacy: float = 0.0
    weighted_impact: float = 0.0
    weighted_sustainability: float = 0.0
    composite_score: float = 0.0
    evaluator_count: int = 0
    recommended_allocation: float = 0.0
    rank: int = 0


# ---------------------------------------------------------------------------
# Reputation weight helpers
# ---------------------------------------------------------------------------
def reputation_to_weight(score: int, completed: int, attestation_count: int) -> float:
    """
    Convert an on-chain reputation into a credibility weight for evaluation.

    - score: 0-10000 basis points (5000 = 50%)
    - completed: total tasks completed successfully
    - attestation_count: how many attestations the evaluator has received

    The weight is a product of:
      * normalized reputation (0.0 - 1.0)
      * experience multiplier based on completed tasks (log scale)
      * social proof factor from attestation count
    """
    rep_factor = score / 10_000  # 0.0 - 1.0

    # Experience: log2(completed + 1) capped at 4x multiplier
    exp_factor = min(math.log2(completed + 1) + 1, 4.0)

    # Social proof: sqrt(attestations + 1), capped at 3x
    social_factor = min(math.sqrt(attestation_count + 1), 3.0)

    return rep_factor * exp_factor * social_factor


# ---------------------------------------------------------------------------
# Main evaluator class
# ---------------------------------------------------------------------------
class PublicGoodsEvaluator:
    """
    Reputation-weighted public goods project evaluator.

    Connects to TrustAgent's AgentRegistry on-chain to fetch evaluator
    reputation, then uses that to weight project scores across three
    dimensions: legitimacy, impact, and sustainability.
    """

    # Weight each dimension in the composite score
    DIMENSION_WEIGHTS = {
        "legitimacy": 0.30,       # Mechanism design track
        "impact": 0.40,           # Data analysis track
        "sustainability": 0.30,   # Data collection track
    }

    def __init__(
        self,
        registry_address: str = "0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98",
        rpc_url: str = "https://sepolia.base.org",
        web3_provider=None,
    ):
        self.registry_address = registry_address
        self.rpc_url = rpc_url
        self._web3 = web3_provider
        self._contract = None
        self._reputation_cache: dict[int, tuple[int, int, int, int]] = {}

    # ── Web3 connection (lazy) ────────────────────────────────────
    def _get_contract(self):
        """Lazily initialize Web3 connection and contract instance."""
        if self._contract is not None:
            return self._contract

        try:
            from web3 import Web3
        except ImportError:
            raise ImportError(
                "web3 package is required: pip install web3"
            )

        if self._web3 is None:
            self._web3 = Web3(Web3.HTTPProvider(self.rpc_url))

        self._contract = self._web3.eth.contract(
            address=Web3.to_checksum_address(self.registry_address),
            abi=REGISTRY_ABI,
        )
        return self._contract

    def get_evaluator_reputation(self, agent_id: int) -> tuple[int, int, int, int]:
        """
        Fetch reputation data from the on-chain AgentRegistry.
        Returns (score, completed, failed, totalAttestations).
        """
        if agent_id in self._reputation_cache:
            return self._reputation_cache[agent_id]

        contract = self._get_contract()
        result = contract.functions.getReputation(agent_id).call()
        self._reputation_cache[agent_id] = tuple(result)
        return tuple(result)

    def get_evaluator_weight(self, agent_id: int) -> float:
        """Get the credibility weight for an evaluator agent."""
        score, completed, _failed, attestations = self.get_evaluator_reputation(agent_id)
        return reputation_to_weight(score, completed, attestations)

    # ── Offline mode (no Web3 required) ───────────────────────────
    def get_evaluator_weight_offline(
        self, score: int = 5000, completed: int = 0, attestations: int = 0
    ) -> float:
        """Compute weight without on-chain lookup (for testing / offline use)."""
        return reputation_to_weight(score, completed, attestations)

    # ── Core ranking logic ────────────────────────────────────────
    def rank_projects(
        self,
        projects: list[dict],
        evaluations: list[dict],
        total_budget: float = 100_000,
        online: bool = False,
        evaluator_reputations: Optional[dict[int, tuple[int, int, int]]] = None,
    ) -> list[ScoredProject]:
        """
        Rank projects by reputation-weighted evaluation scores.

        Parameters
        ----------
        projects : list of dicts with at least 'name', 'category', 'funding_requested'
        evaluations : list of dicts with 'evaluator_agent_id', 'project_name',
                      'legitimacy', 'impact', 'sustainability' (each 1-10)
        total_budget : total funding pool to allocate
        online : if True, fetch reputation from on-chain; otherwise use
                 evaluator_reputations dict or default weights
        evaluator_reputations : optional dict mapping agent_id -> (score, completed, attestations)
                                used when online=False

        Returns
        -------
        List of ScoredProject sorted by composite_score descending, with
        recommended_allocation values that sum to total_budget.
        """
        if evaluator_reputations is None:
            evaluator_reputations = {}

        # Parse projects
        project_map: dict[str, Project] = {}
        for p in projects:
            project_map[p["name"]] = Project(
                name=p["name"],
                category=p.get("category", "general"),
                funding_requested=p.get("funding_requested", 0),
                description=p.get("description", ""),
                url=p.get("url", ""),
                team_size=p.get("team_size", 1),
                months_active=p.get("months_active", 0),
                github_stars=p.get("github_stars", 0),
                users_served=p.get("users_served", 0),
            )

        # Parse evaluations and compute weighted scores
        # Accumulators: project_name -> (weighted_sum_leg, weighted_sum_imp, weighted_sum_sus, total_weight)
        accum: dict[str, list[float]] = {
            name: [0.0, 0.0, 0.0, 0.0] for name in project_map
        }

        for ev in evaluations:
            agent_id = ev["evaluator_agent_id"]
            proj_name = ev["project_name"]

            if proj_name not in accum:
                continue  # skip evaluations for unknown projects

            # Validate scores
            leg = max(1, min(10, ev.get("legitimacy", 5)))
            imp = max(1, min(10, ev.get("impact", 5)))
            sus = max(1, min(10, ev.get("sustainability", 5)))

            # Get evaluator weight
            if online:
                weight = self.get_evaluator_weight(agent_id)
            elif agent_id in evaluator_reputations:
                s, c, a = evaluator_reputations[agent_id]
                weight = reputation_to_weight(s, c, a)
            else:
                # Default: neutral reputation
                weight = reputation_to_weight(5000, 0, 0)

            accum[proj_name][0] += leg * weight
            accum[proj_name][1] += imp * weight
            accum[proj_name][2] += sus * weight
            accum[proj_name][3] += weight

        # Build scored results
        scored: list[ScoredProject] = []
        for name, proj in project_map.items():
            w_leg, w_imp, w_sus, total_w = accum[name]

            sp = ScoredProject(
                name=name,
                category=proj.category,
                funding_requested=proj.funding_requested,
            )

            if total_w > 0:
                sp.weighted_legitimacy = w_leg / total_w
                sp.weighted_impact = w_imp / total_w
                sp.weighted_sustainability = w_sus / total_w
            else:
                # No evaluations: use minimum scores
                sp.weighted_legitimacy = 1.0
                sp.weighted_impact = 1.0
                sp.weighted_sustainability = 1.0

            sp.composite_score = (
                self.DIMENSION_WEIGHTS["legitimacy"] * sp.weighted_legitimacy
                + self.DIMENSION_WEIGHTS["impact"] * sp.weighted_impact
                + self.DIMENSION_WEIGHTS["sustainability"] * sp.weighted_sustainability
            )

            # Count evaluators for this project
            sp.evaluator_count = sum(
                1 for ev in evaluations if ev["project_name"] == name
            )

            scored.append(sp)

        # Sort by composite score descending
        scored.sort(key=lambda s: s.composite_score, reverse=True)

        # Assign ranks
        for i, sp in enumerate(scored):
            sp.rank = i + 1

        # Allocate budget proportionally to composite score, capped at funding_requested
        self._allocate_budget(scored, total_budget)

        return scored

    def _allocate_budget(
        self, scored: list[ScoredProject], total_budget: float
    ) -> None:
        """
        Allocate budget proportionally to composite scores, respecting
        each project's funding_requested cap. Excess is redistributed.
        """
        total_score = sum(sp.composite_score for sp in scored)
        if total_score == 0:
            return

        remaining_budget = total_budget
        remaining_projects = list(scored)
        allocated = {sp.name: 0.0 for sp in scored}

        # Iterative allocation with cap redistribution
        for _ in range(5):  # max 5 redistribution rounds
            if not remaining_projects or remaining_budget <= 0:
                break

            round_total_score = sum(sp.composite_score for sp in remaining_projects)
            if round_total_score == 0:
                break

            next_remaining = []
            for sp in remaining_projects:
                share = (sp.composite_score / round_total_score) * remaining_budget
                capped = min(share, sp.funding_requested - allocated[sp.name])
                allocated[sp.name] += capped
                remaining_budget -= capped

                if allocated[sp.name] < sp.funding_requested:
                    next_remaining.append(sp)

            remaining_projects = next_remaining

        for sp in scored:
            sp.recommended_allocation = round(allocated[sp.name], 2)

    # ── HTTP helper ─────────────────────────────────────────────
    @staticmethod
    def _api_get(url: str, headers: dict | None = None, timeout: int = 15) -> dict | list | None:
        """
        Perform an HTTPS GET and return parsed JSON, or None on failure.
        Uses only stdlib (urllib) — no third-party HTTP library required.
        """
        hdrs = {"User-Agent": "TrustAgent/1.0", "Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, headers=hdrs)
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as exc:
            print(f"  [warn] API call failed for {url}: {exc}")
            return None

    # ── GitHub helpers ────────────────────────────────────────────
    @staticmethod
    def _parse_github_repo(raw: str) -> str:
        """
        Normalise various GitHub URL formats to 'owner/repo'.

        Accepts:
          - "owner/repo"
          - "https://github.com/owner/repo"
          - "https://github.com/owner/repo.git"
          - "github.com/owner/repo/anything"
        """
        raw = raw.strip().rstrip("/")
        if raw.endswith(".git"):
            raw = raw[:-4]
        # Strip protocol + domain
        for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        # Take only the first two path segments (owner/repo)
        parts = raw.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return raw  # best effort

    def _fetch_github_data(self, owner_repo: str) -> dict:
        """
        Call the GitHub REST API (no auth, 60 req/hr rate limit) and return
        a filled metrics dict plus collection status.
        """
        base = f"https://api.github.com/repos/{owner_repo}"
        metrics = {
            "total_commits": 0,
            "unique_contributors": 0,
            "open_issues": 0,
            "closed_issues": 0,
            "stars": 0,
            "forks": 0,
            "last_commit_date": "",
            "license": "",
            "readme_exists": False,
            "ci_configured": False,
        }
        status = "api_error"

        # 1. Main repo metadata
        repo_data = self._api_get(base)
        if repo_data is None or isinstance(repo_data, list):
            return {"metrics": metrics, "collection_status": status}

        metrics["stars"] = repo_data.get("stargazers_count", 0)
        metrics["forks"] = repo_data.get("forks_count", 0)
        metrics["open_issues"] = repo_data.get("open_issues_count", 0)
        lic = repo_data.get("license")
        if lic and isinstance(lic, dict):
            metrics["license"] = lic.get("spdx_id") or lic.get("name") or ""
        metrics["last_commit_date"] = (repo_data.get("pushed_at") or "")[:10]
        status = "live"

        # 2. Contributors count (paginated — just first page, per_page=1 trick with Link header)
        contribs = self._api_get(f"{base}/contributors?per_page=100&anon=true")
        if isinstance(contribs, list):
            metrics["unique_contributors"] = len(contribs)

        # 3. Commit count — use the /commits endpoint with per_page=1 and parse
        #    the Link header's "last" page number.
        try:
            req = urllib.request.Request(
                f"{base}/commits?per_page=1",
                headers={"User-Agent": "TrustAgent/1.0", "Accept": "application/json"},
            )
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                link_header = resp.getheader("Link") or ""
                # Parse "page=N" from the rel="last" link
                import re
                match = re.search(r'page=(\d+)>;\s*rel="last"', link_header)
                if match:
                    metrics["total_commits"] = int(match.group(1))
                else:
                    # Only one page — count items
                    items = json.loads(resp.read().decode())
                    metrics["total_commits"] = len(items) if isinstance(items, list) else 0
        except Exception:
            pass

        # 4. Closed issues count via search API
        search_url = (
            f"https://api.github.com/search/issues"
            f"?q=repo:{owner_repo}+type:issue+state:closed&per_page=1"
        )
        search_data = self._api_get(search_url)
        if isinstance(search_data, dict):
            metrics["closed_issues"] = search_data.get("total_count", 0)

        # 5. README existence check (HEAD-style via contents API)
        readme_data = self._api_get(f"{base}/readme")
        metrics["readme_exists"] = readme_data is not None and isinstance(readme_data, dict)

        # 6. CI configured — check for .github/workflows directory
        ci_data = self._api_get(f"{base}/contents/.github/workflows")
        metrics["ci_configured"] = isinstance(ci_data, list) and len(ci_data) > 0

        return {"metrics": metrics, "collection_status": status}

    # ── On-chain helpers ──────────────────────────────────────────
    def _fetch_onchain_data(self, address: str, network: str = "base-sepolia") -> dict:
        """
        Fetch transaction count for a contract address using the Base Sepolia
        RPC (eth_getTransactionCount) and, if available, the BaseScan API.

        Falls back gracefully when APIs are unreachable.
        """
        result = {
            "address": address,
            "deployed": False,
            "transaction_count": 0,
            "nonce": 0,
            "verified_source": False,
        }
        status = "api_error"

        # --- Strategy 1: JSON-RPC eth_getTransactionCount + eth_getCode ---
        rpc_url = self.rpc_url  # default: https://sepolia.base.org
        for method, key in [
            ("eth_getCode", "has_code"),
            ("eth_getTransactionCount", "nonce"),
        ]:
            payload = json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": method,
                "params": [address, "latest"],
            }).encode()
            try:
                req = urllib.request.Request(
                    rpc_url,
                    data=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "TrustAgent/1.0"},
                )
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                    body = json.loads(resp.read().decode())
                    hex_val = body.get("result", "0x0")
                    if method == "eth_getCode":
                        result["deployed"] = hex_val not in (None, "0x", "0x0")
                    else:
                        result["nonce"] = int(hex_val, 16)
                    status = "live"
            except Exception as exc:
                print(f"  [warn] RPC {method} failed for {address}: {exc}")

        # --- Strategy 2: BaseScan API (no key = 1 req/5s, limited) -------
        basescan_url = (
            f"https://api-sepolia.basescan.org/api"
            f"?module=account&action=txlist&address={address}"
            f"&startblock=0&endblock=99999999&page=1&offset=100&sort=asc"
        )
        txlist = self._api_get(basescan_url, timeout=20)
        if isinstance(txlist, dict) and txlist.get("status") == "1":
            txs = txlist.get("result", [])
            if isinstance(txs, list):
                result["transaction_count"] = len(txs)
                status = "live"
        elif isinstance(txlist, dict) and txlist.get("message") == "No transactions found":
            result["transaction_count"] = 0
            status = "live"

        # --- Strategy 3: try Etherscan mainnet if the address looks mainnet ---
        # (skipped for sepolia — we already tried BaseScan above)

        result["collection_status"] = status
        return result

    # ── Data Collection (Octant Track 1) ────────────────────────
    def collect_project_data(
        self,
        project_name: str,
        github_repo: str = "",
        contract_addresses: list[str] | None = None,
    ) -> dict:
        """
        Gather multi-source evidence for a public goods project via LIVE
        API calls to GitHub and on-chain RPCs / block explorers.

        Collects data from two categories:
          1. **Off-chain (GitHub):** commit count, unique contributors, open/closed
             issues, stars, forks, last commit date, license.
          2. **On-chain:** contract deployments, transaction count via RPC +
             BaseScan API.

        Parameters
        ----------
        project_name : str
            Human-readable project name.
        github_repo : str
            GitHub repo — accepts ``"owner/repo"``, a full GitHub URL, or a
            ``.git`` URL.  Parsed automatically.
        contract_addresses : list[str] | None
            Deployed contract addresses to query on-chain metrics for.

        Returns
        -------
        dict  — structured evidence packet ready for evaluation scoring.
        """
        if contract_addresses is None:
            contract_addresses = []

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # ----- Off-chain evidence (GitHub — LIVE) -----
        owner_repo = self._parse_github_repo(github_repo) if github_repo else ""
        if owner_repo and "/" in owner_repo:
            print(f"  Fetching GitHub data for {owner_repo} ...")
            gh = self._fetch_github_data(owner_repo)
        else:
            gh = {
                "metrics": {
                    "total_commits": 0, "unique_contributors": 0,
                    "open_issues": 0, "closed_issues": 0,
                    "stars": 0, "forks": 0,
                    "last_commit_date": "", "license": "",
                    "readme_exists": False, "ci_configured": False,
                },
                "collection_status": "no_repo_provided",
            }

        github_evidence = {
            "repo": owner_repo or f"{project_name.lower().replace(' ', '-')}/main",
            "metrics": gh["metrics"],
            "collection_method": "GitHub REST API v3 — LIVE (/repos, /contributors, /commits, /search/issues)",
            "collection_status": gh["collection_status"],
        }

        # ----- On-chain evidence (RPC + BaseScan — LIVE) -----
        onchain_evidence = {
            "network": "Base Sepolia (chainId 84532)",
            "contracts": [],
            "aggregate": {
                "total_transactions": 0,
                "total_nonce": 0,
            },
            "collection_method": "eth_getCode + eth_getTransactionCount (RPC) + BaseScan txlist API — LIVE",
            "collection_status": "no_contracts_provided" if not contract_addresses else "api_error",
        }

        for addr in contract_addresses:
            print(f"  Fetching on-chain data for {addr} ...")
            cdata = self._fetch_onchain_data(addr)
            onchain_evidence["contracts"].append(cdata)
            onchain_evidence["aggregate"]["total_transactions"] += cdata.get("transaction_count", 0)
            onchain_evidence["aggregate"]["total_nonce"] += cdata.get("nonce", 0)
            if cdata.get("collection_status") == "live":
                onchain_evidence["collection_status"] = "live"

        # ----- Compose full evidence packet -----
        evidence = {
            "project_name": project_name,
            "evaluation_timestamp": now_iso,
            "evaluator_registry": self.registry_address,
            "data_sources": {
                "github": github_evidence,
                "onchain": onchain_evidence,
            },
            "scoring_input": {
                "legitimacy_signals": [
                    "verified_source_code",
                    "license_present",
                    "contributor_count > 1",
                    "readme_exists",
                ],
                "impact_signals": [
                    "transaction_count",
                    "github_stars",
                    "issues_closed_ratio",
                    "forks",
                ],
                "sustainability_signals": [
                    "commit_frequency",
                    "contributor_growth",
                    "ci_configured",
                    "last_commit_recency",
                ],
            },
            "schema_version": "2.0.0",
        }

        return evidence

    # ── Reporting ─────────────────────────────────────────────────
    def format_report(self, results: list[ScoredProject]) -> str:
        """Format ranked results into a readable text report."""
        lines = [
            "=" * 72,
            "  TrustAgent Public Goods Evaluation Report",
            "  Reputation-Weighted Allocation Recommendation",
            "=" * 72,
            "",
        ]

        total_alloc = sum(r.recommended_allocation for r in results)

        for r in results:
            pct = (r.recommended_allocation / total_alloc * 100) if total_alloc > 0 else 0
            lines.append(f"  #{r.rank}  {r.name} ({r.category})")
            lines.append(f"      Composite Score:    {r.composite_score:.2f} / 10.00")
            lines.append(f"      Legitimacy:         {r.weighted_legitimacy:.2f} / 10")
            lines.append(f"      Impact:             {r.weighted_impact:.2f} / 10")
            lines.append(f"      Sustainability:     {r.weighted_sustainability:.2f} / 10")
            lines.append(f"      Evaluators:         {r.evaluator_count}")
            lines.append(f"      Requested:          ${r.funding_requested:,.0f}")
            lines.append(f"      Recommended:        ${r.recommended_allocation:,.0f} ({pct:.1f}%)")
            lines.append("")

        lines.append("-" * 72)
        lines.append(f"  Total Allocated: ${total_alloc:,.0f}")
        lines.append("")
        lines.append("  Methodology: Scores weighted by evaluator on-chain reputation")
        lines.append("  Dimensions:  Legitimacy (30%) + Impact (40%) + Sustainability (30%)")
        lines.append("  Registry:    0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98 (Base Sepolia)")
        lines.append("=" * 72)

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI demo (runs without Web3 using offline mode)
# ---------------------------------------------------------------------------
def demo():
    """Run a self-contained demo with sample data."""
    evaluator = PublicGoodsEvaluator()

    projects = [
        {
            "name": "OpenResearch DAO",
            "category": "science",
            "funding_requested": 25000,
            "description": "Decentralized open-access research publishing",
            "team_size": 5,
            "months_active": 18,
            "users_served": 12000,
        },
        {
            "name": "EthClimate",
            "category": "climate",
            "funding_requested": 30000,
            "description": "On-chain carbon credit verification for reforestation",
            "team_size": 3,
            "months_active": 8,
            "users_served": 500,
        },
        {
            "name": "LearnWeb3 Africa",
            "category": "education",
            "funding_requested": 15000,
            "description": "Free blockchain developer education in Sub-Saharan Africa",
            "team_size": 7,
            "months_active": 24,
            "users_served": 45000,
        },
        {
            "name": "PrivacyGuard SDK",
            "category": "privacy",
            "funding_requested": 20000,
            "description": "Open-source ZK-proof SDK for dApp developers",
            "team_size": 4,
            "months_active": 12,
            "users_served": 3000,
        },
        {
            "name": "GovBot",
            "category": "governance",
            "funding_requested": 10000,
            "description": "AI assistant for DAO governance participation",
            "team_size": 2,
            "months_active": 6,
            "users_served": 800,
        },
    ]

    # Simulated evaluations from agents with different reputations
    evaluations = [
        # Agent 2 (ResearchAgent): high reputation (10000, 1 completed, 1 attestation)
        {"evaluator_agent_id": 2, "project_name": "OpenResearch DAO",  "legitimacy": 9, "impact": 8, "sustainability": 7},
        {"evaluator_agent_id": 2, "project_name": "EthClimate",        "legitimacy": 6, "impact": 9, "sustainability": 5},
        {"evaluator_agent_id": 2, "project_name": "LearnWeb3 Africa",  "legitimacy": 9, "impact": 9, "sustainability": 8},
        {"evaluator_agent_id": 2, "project_name": "PrivacyGuard SDK",  "legitimacy": 8, "impact": 7, "sustainability": 6},
        {"evaluator_agent_id": 2, "project_name": "GovBot",            "legitimacy": 5, "impact": 6, "sustainability": 4},
        # Agent 3 (AuditorAgent): neutral reputation (5000, 0 completed, 0 attestations)
        {"evaluator_agent_id": 3, "project_name": "OpenResearch DAO",  "legitimacy": 8, "impact": 7, "sustainability": 8},
        {"evaluator_agent_id": 3, "project_name": "EthClimate",        "legitimacy": 7, "impact": 8, "sustainability": 4},
        {"evaluator_agent_id": 3, "project_name": "LearnWeb3 Africa",  "legitimacy": 8, "impact": 10, "sustainability": 9},
        {"evaluator_agent_id": 3, "project_name": "PrivacyGuard SDK",  "legitimacy": 7, "impact": 6, "sustainability": 7},
        {"evaluator_agent_id": 3, "project_name": "GovBot",            "legitimacy": 4, "impact": 5, "sustainability": 3},
        # Agent 1 (AnalystAgent): neutral reputation (5000, 0 completed, 0 attestations)
        {"evaluator_agent_id": 1, "project_name": "OpenResearch DAO",  "legitimacy": 7, "impact": 8, "sustainability": 6},
        {"evaluator_agent_id": 1, "project_name": "EthClimate",        "legitimacy": 5, "impact": 7, "sustainability": 6},
        {"evaluator_agent_id": 1, "project_name": "LearnWeb3 Africa",  "legitimacy": 9, "impact": 9, "sustainability": 7},
        {"evaluator_agent_id": 1, "project_name": "PrivacyGuard SDK",  "legitimacy": 8, "impact": 8, "sustainability": 5},
        {"evaluator_agent_id": 1, "project_name": "GovBot",            "legitimacy": 6, "impact": 4, "sustainability": 5},
    ]

    # Provide offline reputation data matching on-chain state
    evaluator_reps = {
        1: (5000, 0, 0),     # AnalystAgent: neutral, no completed tasks
        2: (10000, 1, 1),    # ResearchAgent: perfect score, 1 task, 1 attestation
        3: (5000, 0, 0),     # AuditorAgent: neutral, no completed tasks
    }

    results = evaluator.rank_projects(
        projects,
        evaluations,
        total_budget=100_000,
        online=False,
        evaluator_reputations=evaluator_reps,
    )

    print(evaluator.format_report(results))

    # ── Octant Data Collection demo — LIVE API calls ────────────
    print("\n\n" + "=" * 72)
    print("  Octant Data Collection — LIVE API Demo")
    print("  Gathering REAL project evidence (GitHub REST API + On-chain RPC)")
    print("=" * 72)

    demo_projects = [
        {
            "name": "TrustAgent",
            "github_repo": "devanshug2307/trustagent",
            "contract_addresses": ["0xcCEfce0Eb734Df5dFcBd68DB6Cf2bc80e8A87D98"],
        },
        {
            "name": "Uniswap V3 Core",
            "github_repo": "https://github.com/Uniswap/v3-core",
            "contract_addresses": [],
        },
        {
            "name": "OpenZeppelin Contracts",
            "github_repo": "OpenZeppelin/openzeppelin-contracts",
            "contract_addresses": [],
        },
    ]

    import os
    all_evidence = []

    for proj in demo_projects:
        print(f"\n{'─' * 60}")
        print(f"  Project: {proj['name']}")
        print(f"{'─' * 60}")

        evidence = evaluator.collect_project_data(
            project_name=proj["name"],
            github_repo=proj["github_repo"],
            contract_addresses=proj.get("contract_addresses", []),
        )
        all_evidence.append(evidence)

        gh = evidence["data_sources"]["github"]
        m = gh["metrics"]
        print(f"\n  GitHub ({gh['collection_status']}):")
        print(f"    Stars: {m['stars']}  |  Forks: {m['forks']}  |  Contributors: {m['unique_contributors']}")
        print(f"    Commits: {m['total_commits']}  |  Open issues: {m['open_issues']}  |  Closed issues: {m['closed_issues']}")
        print(f"    License: {m['license']}  |  README: {m['readme_exists']}  |  CI: {m['ci_configured']}")
        print(f"    Last push: {m['last_commit_date']}")

        oc = evidence["data_sources"]["onchain"]
        if oc["contracts"]:
            print(f"\n  On-chain ({oc['collection_status']}):")
            for c in oc["contracts"]:
                print(f"    {c['address'][:20]}... deployed={c['deployed']}  tx_count={c.get('transaction_count', 0)}  nonce={c.get('nonce', 0)}")
        else:
            print(f"\n  On-chain: no contracts provided")

    output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "octant_demo_output.json")
    with open(output_path, "w") as f:
        json.dump(all_evidence, f, indent=2)

    print(f"\n{'=' * 72}")
    print(f"  All {len(all_evidence)} evidence packets saved to {output_path}")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    demo()
