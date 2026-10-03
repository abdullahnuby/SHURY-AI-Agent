import json
from app.intelligence.semantic import semantic_understand
from app.evaluation.semantic_benchmark import run_semantic_benchmark
from app.api import run_brain
from app.runtime.agent import resume_agent, replay_run, plan_only, reliability_report, plan_cache
run_agent = run_brain
from app.knowledge.memory import get_memory
from app.knowledge.learning import discover_routines
from app.evaluation.versions.v9 import run_v9_benchmark
from app.evaluation.versions.v10 import run_v10_benchmark
from app.evaluation.versions.v11 import run_v11_benchmark
from app.evaluation.versions.v12 import run_v12_benchmark
from app.evaluation.versions.v13 import run_v13_benchmark
from app.evaluation.versions.v14 import run_v14_benchmark
from app.evaluation.versions.v15 import run_v15_benchmark
from app.evaluation.versions.v16 import run_v16_benchmark
from app.evaluation.versions.v17 import run_v17_benchmark
from app.evaluation.versions.v18 import run_v18_benchmark
from app.evaluation.versions.v19 import run_v19_benchmark
from app.evaluation.versions.v20 import run_v20_benchmark
from app.evaluation.versions.v21 import run_v21_benchmark
from app.services.skill_supply_service import discover_skills, skill_routes, install_skill, refresh_skill, installed_skills, skill_supply_status, approve_remote_skill, learn_skills
from app.services.project_skill_service import skill_snapshot, matching_skills, set_skill_status, learn_project
from app.services.skill_evaluation_service import inspect_skill, skill_metadata, activate_skill_view, skill_evidence
from app.services.internet_service import network_status, fetch_web, research_web, internet_research, research_github, inspect_repo, git_repo_status, validate_project
from app.services.knowledge_service import ask_knowledge, index_knowledge, index_agent_memory, rag_runtime_stats
from app.services.agentic_rag_service import agentic_rag
from app.identity import get_identity
from app.evaluation.agentic_rag_benchmark import run_agentic_rag_benchmark
from app.services.workspace_service import workspace_analyze
from app.observability.agent_analytics import analyze_runtime
from app.knowledge.data_analysis import DeterministicDataAgent
from app.evaluation.memory_benchmark import run_memory_benchmark
from app.learning.manager import SelfImprovementManager
from app.evaluation.self_improvement_benchmark import run_self_improvement_benchmark
from app.evaluation import EvaluationLab, load_scenarios, default_scenarios, release_gate
from app.evaluation.scenarios import write_scenarios
from app.evaluation.simulations import run_real_user_simulation
from app.evaluation.world_model_benchmark import run_world_model_benchmark
from app.world.model import WorldModel
from app.runtime.registry import load_tools
from app.tools.system.files import safe_path, workspace_root
from pathlib import Path
import json
import uuid

ICON = {"done": "✓", "failed": "✗", "skipped": "⏭", "pending": "…"}


def ask_approval(tool: str, args: dict, notes=None) -> bool:
    for n in notes or []:
        print(f"  ⚠ {n}")
    return input(f"  ⚠ الـAgent عايز ينفذ {tool} {args} — موافق؟ (y/n): ").strip().lower() in ("y", "yes", "ايوه", "أيوه", "ا")


def show_plan(plan):
    for s in plan.steps:
        deps = f" deps={s.depends_on}" if s.depends_on else ""
        print(f"  {s.id}: {s.tool}({s.args}){deps}")
    print(f"  planner={plan.planner} estimated_cost={plan.estimated_cost:.3f} estimated_duration={plan.estimated_duration:.3f}")


def show_state(state):
    if hasattr(state, "state") and hasattr(state, "response"):
        cognitive = state.state
        run_id = getattr(state, "run_id", "")
        status = getattr(state, "status", "")
        decision = getattr(getattr(cognitive, "decision", None), "kind", "")
        goal = getattr(getattr(cognitive, "goal", None), "objective", "")
        print(f"run_id: {run_id}")
        print(f"status: {status}")
        print(f"goal: {goal}")
        print(f"decision: {decision}")
        print(f"[{status}] {state.response}")
        return
    print(f"run_id: {state.run_id}")
    print("الخطة:")
    show_plan(state.plan)
    for s in state.plan.steps:
        print(f"  {ICON.get(s.status, '?')} {s.id} {s.tool} -> {s.output if s.status == 'done' else (s.error or s.status)}")
    print(f"[{state.status}] replans={state.replans} | {state.final_message}")


def show_result(state, debug=False):
    if debug:
        show_state(state)
    elif hasattr(state, "response"):
        print(state.response)
    else:
        print(state.final_message)

def main():
    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "unknown"
    identity = get_identity()
    print(f"{identity.name} V{version} — {identity.role} | /debug /tools /semantic <نص> /semantic-benchmark /agent <هدف> /brain /plan <هدف> /resume <run_id> /replay <run_id> /reliability /experience /memory <query> /memory-profile /memory-stats /memory-health /memory-consolidate /memory-cleanup /memory-benchmark /memory-export <path> /memory-import <path> /routines /world /world-benchmark /benchmark /v12-benchmark /v13-benchmark /v14-benchmark /v15-benchmark /v16-benchmark /v17-benchmark /v18-benchmark /v19-benchmark /v20-benchmark /v21-benchmark /discover-skills <query> /route-skills <query> /learn-skills <query> /install-skill <owner/repo> <path> /refresh-skill <key> /installed-skills /approve-skill <key> /skill-supply-status /learn <query> /learn-development <path> /research-status /research-memory <query> /research-source-learning <query> /skills /skill-match <goal> /skill-status <key> <status> /learn-project <path> /inspect-skill <path> /skill-meta <path> /skill-view <path> /skill-evidence <key> /analytics /algorithm-portfolio /workspace <path> /rag-index <path> /rag-memory-index /rag <query> /rag-stats /agentic-rag <query> /agentic-rag-benchmark /learning-status /brain-bootstrap /brain-ingest <path> /brain-stats /brain-match <text> /brain-procedures <text> /learning <goal> /evolve <skill-key> /rollback <skill-key> /self-improvement-benchmark /eval-suite [scenario.json] /eval-sim /eval-gate <baseline.json> <candidate.json> /seed <query> /seed-stats /deep-research <query> /web <query> /arxiv <query> /github-search <query> /fetch <url> /github <owner/repo> /network-status /project <path> /git-status <path> /check <path> exit")
    session_id = uuid.uuid4().hex
    pending_cognitive_goal: str | None = None
    debug_mode = False
    while True:
        goal = input("\n> ").strip()
        if goal.lower() in ("exit", "quit", "خروج"):
            break
        if not goal:
            continue
        if goal == "/debug":
            debug_mode = not debug_mode
            print(f"Debug mode: {'on' if debug_mode else 'off'}")
            continue
        if goal == "/seed-stats":
            try:
                from app.knowledge.seed_scenarios import SeedScenarioStore
                print(json.dumps(SeedScenarioStore().stats(), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[seed stats failed] {e}")
            continue
        if goal.startswith("/seed "):
            try:
                from app.knowledge.seed_scenarios import SeedScenarioStore
                items = SeedScenarioStore().context(goal[len("/seed "):].strip(), limit=8)
                print(json.dumps(items, ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[seed search failed] {e}")
            continue
        if goal == "/tools":
            for t in load_tools().values():
                print(f"  - {t.name}: {t.description} | cap={t.capability or t.name} | cost={t.cost} | duration={t.duration} | risk={t.risk}{' [موافقة]' if t.requires_approval else ''}")
            continue
        if goal == "/brain":
            from app.intelligence.semantic.retrieval import model_status
            print(json.dumps({
                "brain": "canonical-state-brain",
                "semantic_nlp": model_status(),
            }, ensure_ascii=False, indent=2))
            continue

        if goal == "/nlp-status":
            from app.intelligence.semantic.retrieval import model_status
            print(json.dumps(model_status(), ensure_ascii=False, indent=2))
            continue
        if goal.startswith("/semantic "):
            parsed = semantic_understand(goal[len("/semantic "):].strip(), session_id=session_id)
            print(json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2))
            continue
        if goal == "/semantic-benchmark":
            print(json.dumps(run_semantic_benchmark(), ensure_ascii=False, indent=2))
            continue

        if goal.startswith("/agent "):
            requested_goal = goal[7:].strip()
            state = run_agent(requested_goal, approve=ask_approval, session_id=session_id)
            show_result(state, debug_mode)
            pending_cognitive_goal = requested_goal if state.status == "needs_user" else None
            continue
        if goal.startswith("/plan "):
            plan, errors = plan_only(goal[6:])
            show_plan(plan)
            print("  أخطاء:", errors or "لا يوجد")
            continue
        if goal.startswith("/resume "):
            try:
                show_result(resume_agent(goal[8:].strip(), approve=ask_approval), debug_mode)
            except (KeyError, ValueError) as e:
                print(f"[resume failed] {e}")
            continue
        if goal.startswith("/replay "):
            try:
                for row in replay_run(goal[8:].strip()):
                    print(row)
            except Exception as e:
                print(f"[replay failed] {e}")
            continue
        if goal == "/reliability":
            print(reliability_report())
            continue
        if goal == "/experience":
            print(plan_cache())
            continue
        if goal.startswith("/memory "):
            print(get_memory().recall_context(goal[8:].strip()))
            continue
        if goal == "/memory-profile":
            print(get_memory().profile(limit=50))
            continue
        if goal == "/memory-stats":
            print(get_memory().memory_stats())
            continue
        if goal == "/memory-consolidate":
            print(get_memory().consolidate())
            continue
        if goal == "/memory-cleanup":
            print(get_memory().cleanup())
            continue
        if goal == "/memory-health":
            print(get_memory().memory_health())
            continue
        if goal == "/memory-benchmark":
            print(run_memory_benchmark())
            continue
        if goal.startswith("/memory-export "):
            target = goal[len("/memory-export "):].strip()
            if not target:
                print("استخدم: /memory-export <path>")
                continue
            try:
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(get_memory().export_memory(), f, ensure_ascii=False, indent=2, default=str)
                print({"exported_to": target})
            except Exception as e:
                print(f"[memory export failed] {e}")
            continue
        if goal.startswith("/memory-import "):
            target = goal[len("/memory-import "):].strip()
            if not target:
                print("استخدم: /memory-import <path>")
                continue
            try:
                with open(target, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if ask_approval("memory_import", {"path": target}):
                    print(get_memory().restore_memory(payload, include_episodes=True))
                else:
                    print("[memory import cancelled]")
            except Exception as e:
                print(f"[memory import failed] {e}")
            continue
        if goal == "/routines":
            print(discover_routines(get_memory()))
            continue
        if goal == "/world":
            from app.world.store import load_session_world
            print(WorldModel().context(load_session_world(get_memory(), session_id), limit=20))
            continue
        if goal == "/world-benchmark":
            print(json.dumps(run_world_model_benchmark(), ensure_ascii=False, indent=2))
            continue
        if goal.startswith("/stateful-benchmark"):
            from app.evaluation.stateful_conversation_benchmark import run_stateful_benchmark
            tail = goal[len("/stateful-benchmark"):].strip()
            try:
                count = int(tail) if tail else 20
            except ValueError:
                count = 20
            print(json.dumps(run_stateful_benchmark(count=count, seed=1, rounds=1, live=False), ensure_ascii=False, indent=2))
            continue
        if goal == "/benchmark":
            print({"v10": run_v10_benchmark(), "v11": run_v11_benchmark(), "v12": run_v12_benchmark(), "v13": run_v13_benchmark(), "v14": run_v14_benchmark(), "v15": run_v15_benchmark(), "v16": run_v16_benchmark(), "v17": run_v17_benchmark(), "v18": run_v18_benchmark(), "v19": run_v19_benchmark(), "v20": run_v20_benchmark(), "v21": run_v21_benchmark()})
            continue
        if goal == "/v13-benchmark":
            print(run_v13_benchmark())
            continue
        if goal == "/v14-benchmark":
            print(run_v14_benchmark())
            continue
        if goal == "/v15-benchmark":
            print(run_v15_benchmark())
            continue
        if goal == "/v16-benchmark":
            print(run_v16_benchmark())
            continue
        if goal == "/v17-benchmark":
            print(run_v17_benchmark())
            continue
        if goal == "/v18-benchmark":
            print(run_v18_benchmark())
            continue
        if goal == "/v19-benchmark":
            print(run_v19_benchmark())
            continue
        if goal == "/v20-benchmark":
            print(run_v20_benchmark())
            continue
        if goal == "/v21-benchmark":
            print(run_v21_benchmark())
            continue
        if goal.startswith("/discover-skills "):
            try:
                print(discover_skills(goal[17:].strip()))
            except Exception as e:
                print(f"[discover skills failed] {e}")
            continue
        if goal.startswith("/route-skills "):
            try:
                print(skill_routes(goal[14:].strip()))
            except Exception as e:
                print(f"[route skills failed] {e}")
            continue
        if goal.startswith("/learn-skills "):
            try:
                print(learn_skills(goal[14:].strip()))
            except Exception as e:
                print(f"[learn skills failed] {e}")
            continue
        if goal.startswith("/install-skill "):
            raw = goal[15:].strip()
            parts = raw.split(None, 1)
            if len(parts) != 2:
                print("استخدم: /install-skill <owner/repo> <skill_path/SKILL.md>")
            else:
                try:
                    print(install_skill(parts[0], parts[1]))
                except Exception as e:
                    print(f"[install skill failed] {e}")
            continue
        if goal.startswith("/refresh-skill "):
            try:
                print(refresh_skill(goal[15:].strip()))
            except Exception as e:
                print(f"[refresh skill failed] {e}")
            continue
        if goal == "/installed-skills":
            print(installed_skills())
            continue
        if goal.startswith("/approve-skill "):
            try:
                print(approve_remote_skill(goal[15:].strip()))
            except Exception as e:
                print(f"[approve skill failed] {e}")
            continue
        if goal == "/skill-supply-status":
            print(skill_supply_status())
            continue
        if goal.startswith("/learn "):
            try:
                from app.services.research_service import learn
                print(learn(goal[7:].strip()))
            except Exception as e:
                print(f"[learn failed] {e}")
            continue
        if goal.startswith("/learn-development "):
            try:
                from app.services.research_service import learn_development
                print(learn_development(goal[19:].strip()))
            except Exception as e:
                print(f"[learn-development failed] {e}")
            continue
        if goal == "/research-status":
            from app.services.research_service import research_status
            print(research_status())
            continue
        if goal.startswith("/research-memory "):
            from app.services.research_service import research_sources
            print(research_sources(goal[17:].strip()))
            continue
        if goal.startswith("/research-source-learning "):
            from app.services.research_service import research_source_learning
            print(research_source_learning(goal[25:].strip()))
            continue
        if goal.startswith("/inspect-skill "):
            try: print(inspect_skill(goal[14:].strip()))
            except Exception as e: print(f"[inspect skill failed] {e}")
            continue
        if goal.startswith("/skill-meta "):
            try: print(skill_metadata(goal[12:].strip()))
            except Exception as e: print(f"[skill meta failed] {e}")
            continue
        if goal.startswith("/skill-view "):
            try: print(activate_skill_view(goal[12:].strip()))
            except Exception as e: print(f"[skill view failed] {e}")
            continue
        if goal.startswith("/skill-evidence "):
            try: print(skill_evidence(goal[16:].strip()))
            except Exception as e: print(f"[skill evidence failed] {e}")
            continue
        if goal == "/skills":
            print(skill_snapshot())
            continue
        if goal.startswith("/skill-match "):
            print(matching_skills(goal[12:].strip()))
            continue
        if goal.startswith("/skill-status "):
            parts = goal[13:].strip().split(" ", 1)
            if len(parts) == 2:
                try:
                    print(set_skill_status(parts[0], parts[1]))
                except Exception as e:
                    print(f"[skill status failed] {e}")
            continue
        if goal.startswith("/learn-project "):
            try:
                print(learn_project(goal[15:].strip()))
            except Exception as e:
                print(f"[learn project failed] {e}")
            continue
        if goal.startswith("/rag-index "):
            try:
                print(index_knowledge(goal[10:].strip()))
            except Exception as e:
                print(f"[rag index failed] {e}")
            continue
        if goal == "/rag-memory-index":
            try:
                print(index_agent_memory())
            except Exception as e:
                print(f"[rag memory index failed] {e}")
            continue
        if goal.startswith("/rag "):
            try:
                print(ask_knowledge(goal[5:].strip()))
            except Exception as e:
                print(f"[rag failed] {e}")
            continue
        if goal.startswith("/agentic-rag "):
            try:
                print(json.dumps(agentic_rag(goal[len("/agentic-rag "):].strip()), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[agentic rag failed] {e}")
            continue
        if goal == "/agentic-rag-benchmark":
            print(json.dumps(run_agentic_rag_benchmark(), ensure_ascii=False, indent=2))
            continue
        if goal == "/brain-stats":
            try:
                from app.learning.brain_store import BrainKnowledgeStore
                print(json.dumps(BrainKnowledgeStore().stats(), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[brain stats failed] {e}")
            continue
        if goal == "/brain-bootstrap":
            try:
                from app.learning.bootstrap import bootstrap_seed
                print(json.dumps(bootstrap_seed(), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[brain bootstrap failed] {e}")
            continue
        if goal.startswith("/brain-ingest "):
            try:
                from app.learning.bootstrap import ingest_file
                print(json.dumps(ingest_file(goal[len("/brain-ingest "):].strip()), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[brain ingest failed] {e}")
            continue
        if goal.startswith("/brain-match "):
            try:
                from app.learning.brain_store import BrainKnowledgeStore
                print(json.dumps(BrainKnowledgeStore().match_capabilities(goal[len("/brain-match "):].strip(), registry=load_tools(), limit=10), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[brain match failed] {e}")
            continue
        if goal.startswith("/brain-procedures "):
            try:
                from app.learning.brain_store import BrainKnowledgeStore
                print(json.dumps(BrainKnowledgeStore().match_procedures(goal[len("/brain-procedures "):].strip(), registry=load_tools(), limit=10), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[brain procedures failed] {e}")
            continue
        if goal == "/learning-status":
            print(json.dumps(SelfImprovementManager().status(), ensure_ascii=False, indent=2))
            continue
        if goal.startswith("/learning "):
            try:
                manager = SelfImprovementManager()
                print(json.dumps(manager.guidance(goal[len("/learning "):].strip(), limit=8), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[learning failed] {e}")
            continue
        if goal.startswith("/evolve "):
            key = goal[len("/evolve "):].strip()
            if not key:
                print("استخدم: /evolve <skill-key>")
                continue
            try:
                manager = SelfImprovementManager()
                decision = manager.evolve_candidate(key, memory=get_memory(), registry=load_tools())
                print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[evolve failed] {e}")
            continue
        if goal.startswith("/rollback "):
            key = goal[len("/rollback "):].strip()
            if not key:
                print("استخدم: /rollback <skill-key>")
                continue
            try:
                print(json.dumps(SelfImprovementManager().rollback(key), ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[rollback failed] {e}")
            continue
        if goal == "/self-improvement-benchmark":
            print(json.dumps(run_self_improvement_benchmark(), ensure_ascii=False, indent=2))
            continue
        if goal == "/eval-sim":
            try:
                result = run_real_user_simulation("data/evaluations-sim")
                print(json.dumps({"pass_rate": result.get("pass_rate"), "mean_score": result.get("mean_score"),
                                  "safety_violations": result.get("safety_violations"),
                                  "reproducible": result.get("reproducible"),
                                  "failure_patterns": result.get("failure_patterns")}, ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[eval simulation failed] {e}")
            continue
        if goal.startswith("/eval-suite"):
            raw = goal[len("/eval-suite"):].strip()
            try:
                scenarios = load_scenarios(raw) if raw else default_scenarios()
                report = EvaluationLab().run(scenarios)
                print(json.dumps({"run_id": report.run_id, "version": report.version, "pass_rate": report.pass_rate,
                                  "mean_score": report.mean_score, "safety_violations": report.safety_violations,
                                  "reproducible": report.reproducible}, ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[eval suite failed] {e}")
            continue
        if goal.startswith("/eval-gate "):
            raw=goal[len("/eval-gate "):].strip().split()
            if len(raw)!=2:
                print("استخدم: /eval-gate <baseline.json> <candidate.json>")
                continue
            try:
                import json as _json
                with open(raw[0], "r", encoding="utf-8") as f: baseline=_json.load(f)
                with open(raw[1], "r", encoding="utf-8") as f: candidate=_json.load(f)
                comparison=EvaluationLab().compare(baseline,candidate)
                gate=release_gate(candidate)
                print(json.dumps({"comparison": comparison, "candidate_gate": gate}, ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"[eval gate failed] {e}")
            continue
        if goal == "/rag-stats":
            print(rag_runtime_stats())
            continue
        if goal.startswith("/workspace "):
            try:
                print(workspace_analyze(goal[11:].strip()))
            except Exception as e:
                print(f"[workspace failed] {e}")
            continue
        if goal == "/algorithm-portfolio":
            print(get_memory().algorithm_portfolio_snapshot())
            continue
        if goal == "/network-status":
            print(network_status())
            continue
        if goal.startswith("/arxiv "):
            try:
                from app.services.internet_service import research_arxiv
                print(research_arxiv(goal[7:].strip()))
            except Exception as e:
                print(f"[arxiv failed] {e}")
            continue
        if goal.startswith("/github-search "):
            try:
                from app.services.internet_service import search_github
                print(search_github(goal[15:].strip()))
            except Exception as e:
                print(f"[github search failed] {e}")
            continue
        if goal.startswith("/deep-research "):
            try:
                print(internet_research(goal[15:].strip()))
            except Exception as e:
                print(f"[deep research failed] {e}")
            continue
        if goal.startswith("/web "):
            try:
                print(research_web(goal[5:].strip()))
            except Exception as e:
                print(f"[web research failed] {e}")
            continue
        if goal.startswith("/fetch "):
            try:
                print(fetch_web(goal[7:].strip()))
            except Exception as e:
                print(f"[fetch failed] {e}")
            continue
        if goal.startswith("/github "):
            try:
                print(research_github(goal[8:].strip()))
            except Exception as e:
                print(f"[github failed] {e}")
            continue
        if goal.startswith("/project "):
            try:
                print(inspect_repo(goal[9:].strip()))
            except Exception as e:
                print(f"[project failed] {e}")
            continue
        if goal.startswith("/git-status "):
            try:
                print(git_repo_status(goal[12:].strip()))
            except Exception as e:
                print(f"[git status failed] {e}")
            continue
        if goal.startswith("/check "):
            try:
                print(validate_project(goal[7:].strip()))
            except Exception as e:
                print(f"[check failed] {e}")
            continue
        if goal == "/analytics":
            print(analyze_runtime(get_memory()))
            continue
        if goal.startswith("/analyze "):
            raw = goal[9:].strip()
            parts = raw.split(" ", 1)
            if not parts:
                print("استخدم: /analyze <path> <question>")
                continue
            path = parts[0]
            question = parts[1] if len(parts) > 1 else "profile"
            try:
                candidate = Path(path).expanduser()
                if not candidate.is_absolute():
                    candidate = safe_path(path)
                print(DeterministicDataAgent().ask(str(candidate), question))
            except Exception as e:
                print(f"[analysis failed] {e}")
            continue
        if pending_cognitive_goal:
            continued_goal = pending_cognitive_goal + "\n\nUSER CLARIFICATION: " + goal
            state = run_agent(continued_goal, approve=ask_approval, session_id=session_id)
            show_result(state, debug_mode)
            pending_cognitive_goal = continued_goal if state.status == "needs_user" else None
        else:
            show_result(run_agent(goal, approve=ask_approval, session_id=session_id), debug_mode)


if __name__ == "__main__":
    main()
