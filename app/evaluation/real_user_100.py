from __future__ import annotations
import argparse, json, os, tempfile, shutil, hashlib, re, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import app.knowledge.memory as memory_mod
from app.knowledge.memory import get_memory
from app.runtime.agent import run_agent
from app.integrations.network import FetchResult

@dataclass
class Scenario:
    id: str
    category: str
    goal: str
    mode: str = "agent"
    actions: list[dict] = field(default_factory=list)
    turns: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    facts: dict[str, str] = field(default_factory=dict)
    session: str = ""
    approve: bool = True
    expect_status: tuple[str, ...] = ("completed",)
    required_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    expect_contains: tuple[str, ...] = ()
    postcheck: str = ""

class FakeGateway:
    pages = {
        "https://example.com/agents": "<html><title>Agents</title><body>Agent memory planning retrieval evaluation world model.</body></html>",
        "https://example.com/rag": "<html><title>RAG</title><body>Agentic RAG uses iterative retrieval evidence verification and corrective search.</body></html>",
    }
    def __init__(self, *a, **k): self.calls=[]
    def stats(self): return {"requests":0,"cache_hits":0,"hosts":0,"policy":"sandbox-fake-public-gateway"}
    def fetch(self, url, *a, **k):
        self.calls.append(("fetch",url))
        body=self.pages.get(url, "<html><body>Sandbox public source: agent systems and evidence.</body></html>").encode()
        return FetchResult(url,url,200,"text/html; charset=utf-8",body,hashlib.sha256(body).hexdigest(),1.0,False,True)
    def search_web(self, query, limit=5):
        return [{"rank":i+1,"title":f"Sandbox result {i+1}: {query}","url":u,"snippet":"sandbox evidence"} for i,u in enumerate(list(self.pages)[:max(1,min(limit,2))])]
    def arxiv_search(self, query, limit=8):
        return [{"title":f"Sandbox paper {i+1}: {query}","authors":["Sandbox Author"],"published":"2026-09-01","updated":"2026-09-15","url":f"https://arxiv.org/abs/9999.{i:04d}","abstract":"Agent memory, planning and evaluation research."} for i in range(max(1,min(limit,2)))]
    def github_search_repositories(self, query, limit=8):
        return [{"full_name":"sandbox/agent-demo","html_url":"https://github.com/sandbox/agent-demo","description":"Sandbox agent repository","stargazers_count":42,"updated_at":"2026-09-20"}]
    def github_repo(self, repo): return {"full_name":repo,"default_branch":"main","description":"Sandbox agent repository","stargazers_count":42}
    def github_tree(self, repo, branch, limit=200):
        return [{"path":"README.md"},{"path":"pyproject.toml"},{"path":"app/agent.py"},{"path":".github/workflows/test.yml"}]
    def github_file(self, repo, path, branch):
        text={"README.md":"Sandbox agent architecture.","pyproject.toml":"[project]\nname='sandbox'\n","app/agent.py":"def run(): return 'agent'\n",".github/workflows/test.yml":"name: test"}.get(path,"")
        return {"url":f"https://github.com/{repo}/blob/{branch}/{path}","sha256":hashlib.sha256(text.encode()).hexdigest(),"text":text}


def patch_network():
    import app.integrations.network as n
    import app.knowledge.web_research as wr
    import app.tools.network.web as tw
    import app.services.internet_service as ins
    n.NetworkGateway = FakeGateway
    wr.NetworkGateway = FakeGateway
    tw.NetworkGateway = FakeGateway
    ins.NetworkGateway = FakeGateway


def setup(root: Path, sc: Scenario):
    memory_mod.configure(root/"memory.db")
    os.environ["AGENT_LEARNING_DB"] = str(root/"learning.db")
    os.environ["AGENT_SKILLS_DB"] = str(root/"skills.db")
    os.environ["AGENT_RAG_DB"] = str(root/"rag.db")
    os.environ["AGENT_WORKSPACE"] = str(root/"workspace")
    ws=root/"workspace"; ws.mkdir(parents=True)
    for rel,content in sc.files.items():
        p=ws/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(content,encoding="utf-8")
    for k,v in sc.facts.items(): get_memory().set_fact(k,v)
    return ws


def run_scenario(sc: Scenario, root: Path):
    ws=setup(root, sc)
    if sc.mode=="agent":
        state=run_agent(sc.goal, approve=lambda *a: sc.approve, session_id=sc.session or f"s-{sc.id}", max_steps=8, max_seconds=20)
    elif sc.mode=="react":
        # Legacy scripted ReAct scenarios now run through the deterministic runtime.
        state=run_agent(sc.goal, approve=lambda *a,**k: sc.approve, session_id=sc.session or f"s-{sc.id}", max_steps=8, max_seconds=20)
    elif sc.mode=="sequence":
        states=[]
        for g in sc.turns:
            states.append(run_agent(g, approve=lambda *a: sc.approve, session_id=sc.session or f"s-{sc.id}", max_steps=8, max_seconds=20))
        state=states[-1]; state._campaign_states=states
    else: raise ValueError(sc.mode)
    return state,ws


def check(sc,state,ws):
    states=getattr(state,"_campaign_states",[state])
    all_tools=[]
    for s in states: all_tools += [x.tool for x in (s.plan.steps if s.plan else [])]
    ok=all(s.status in sc.expect_status for s in states)
    if sc.required_tools: ok=ok and all(x in all_tools for x in sc.required_tools)
    if sc.forbidden_tools: ok=ok and not any(x in all_tools for x in sc.forbidden_tools)
    finals=" | ".join(s.final_message for s in states)
    if sc.expect_contains: ok=ok and all(x.casefold() in finals.casefold() for x in sc.expect_contains)
    if sc.postcheck=="no_escape": ok=ok and not (ws.parent/"escape.txt").exists()
    elif sc.postcheck=="wrote": ok=ok and (ws/"output.txt").exists() and (ws/"output.txt").read_text()=="sandbox"
    elif sc.postcheck=="no_city": ok=ok and get_memory().get_fact("city") is None
    elif sc.postcheck=="origin": ok=ok and get_memory().get_fact("origin")=="luxor"
    elif sc.postcheck=="name": ok=ok and (get_memory().get_fact("name") or "").casefold()=="abdullah"
    elif sc.postcheck=="isolation": ok=ok and get_memory().get_fact("name") is None
    elif sc.postcheck=="profile_two":
        p=get_memory().profile(limit=50); ok=ok and any(x.get("key")=="name" for x in p) and any(x.get("key")=="origin" for x in p)
    elif sc.postcheck=="result81": ok=ok and get_memory().get_fact("total")=="81"
    return ok,{"statuses":[s.status for s in states],"tools":all_tools,"finals":finals}


def scenarios():
    S=[]
    core=[
      ("001","calculate 4*6","24"),("002","calculate 17*6","102"),("003","calculate 2+3*4","14"),("004","احسب 25/5","5.0"),
      ("005","what is 12 times 7","84"),("006","calculate -8+3","-5"),("007","calculate 2^5","32"),("008","calculate 10%3","1"),
      ("009","subtract 9 from 20","11"),("010","divide 81 by 9","9"),("011","calculate (5+3)*2","16"),("012","hello",None),
      ("013","hi there",None),("014","good morning",None),("015","what time is it?",None),
    ]
    for i,g,o in core:S.append(Scenario(f"core.{i}","core",g,required_tools=("calculator",) if o else (("get_time",) if i=="015" else ()),expect_contains=(o,) if o else ()))
    mem=[
      ("016","my name is Abdullah","remember_fact"),("017","what is my name?","recall_fact"),("018","I'm from Luxor","remember_fact"),("019","where do I come from?","recall_fact"),
      ("020","I prefer dark mode","remember_memory"),("021","what programming language do I prefer?","recall_fact"),("022","remember that my favorite editor is VS Code","remember_fact"),
      ("023","do you remember my name?","recall_fact"),("024","forget my name","forget_fact"),("025","what do you remember about me?","memory_profile"),
      ("026","search my memory Abdullah","search_memory"),("027","save a note: kickoff is Monday","save_note"),("028","show my notes","list_notes"),
      ("029","search my notes kickoff","search_notes"),("030","memory health","memory_health"),("031","memory stats","memory_stats"),
      ("032","memory history name","memory_history"),("033","memory graph Abdullah","memory_graph"),("034","memory cleanup","memory_cleanup"),("035","forget everything about me","memory_forget_all"),
    ]
    for i,g,t in mem:S.append(Scenario(f"memory.{i}","memory",g,required_tools=(t,),expect_status=("completed","cancelled","failed")))
    seq=[
      ("036",["my name is Abdullah","what is my name?"],"name"),("037",["I'm from Luxor","where do I come from?"],"origin"),
      ("038",["calculate 9*9","what was the last result?"],"last"),("039",["calculate 9*9","save the result as total","what is total?"],"result81"),
      ("040",["my city is Cairo","No, I mean Luxor","what is my city?"],"city_update"),("041",["my city is Cairo","forget my city","what is my city?"],"no_city"),
      ("042",["my name is Abdullah","I'm from Luxor","what do you remember about me?"],"profile_two"),("043",["what is my name?"],"isolation"),
      ("044",["I prefer dark mode","what do I prefer?"],"preference"),("045",["save a note: alpha","search my notes alpha"],"notes"),
    ]
    # add seed facts per scenario where needed
    for i,turns,chk in seq:
        post = {"name":"name","origin":"origin","last":"","result81":"result81","city_update":"city","no_city":"no_city","profile_two":"profile_two","isolation":"isolation","preference":"","notes":""}.get(chk, "")
        S.append(Scenario(f"journey.{i}","journey",turns[0],mode="sequence",turns=turns,session=f"j{i}",postcheck=post,expect_status=("completed","needs_user")))
    corpus="Agentic RAG uses iterative retrieval. Memory stores provenance and temporal validity. World models compare predicted and observed state transitions.\n"
    rag=[
      ("046","index corpus knowledge.txt","index_knowledge"),("047","rag agent memory provenance","rag_query"),
      ("049","rag world state transitions","rag_query"),("050","index agent memory","index_agent_memory"),("051","rag provenance and temporal memory","rag_query"),
      ("052","rag retrieval","rag_query"),("053","retrieve evidence from agent memory about my name","rag_query"),("054","rag world models","rag_query"),("055","rag portfolio","analyze_rag_portfolio"),
    ]
    S.append(Scenario("rag.048","rag","index corpus knowledge.txt",mode="sequence",turns=["index corpus knowledge.txt","answer using the indexed documents about agent memory"],session="rag048",files={"knowledge.txt":corpus},required_tools=("index_knowledge","rag_query"),expect_status=("completed","failed")))
    for i,g,t in rag:
        facts = {"name":"Abdullah"} if i == "053" else {}
        S.append(Scenario(f"rag.{i}","rag",g,files={"knowledge.txt":corpus},facts=facts,required_tools=(t,),expect_status=("completed","failed")))
    csv="name,value\na,10\nb,11\nc,1000\nd,12\ne,13\n"
    data=[
      ("056","profile dataset sales.csv","profile_dataset"),("057","analyze sales.csv for outliers","analyze_dataset"),("058","analyze the dataset sales.csv and find anomalies","analyze_dataset"),
      ("059","find outliers in sales.csv","analyze_dataset"),("060","what is the average value in sales.csv","analyze_dataset"),("061","find correlation in sales.csv","analyze_dataset"),
      ("062","profile the data in sales.csv","profile_dataset"),("063","analyze data file sales.csv","analyze_dataset"),("064","profile dataset bad.csv","profile_dataset"),("065","analyze bad.csv","analyze_dataset"),
    ]
    for i,g,t in data:S.append(Scenario(f"data.{i}","data",g,files={"sales.csv":csv,"bad.csv":"name,value\na,10\nb,bad\n"},required_tools=(t,),expect_status=("completed","failed")))
    files={"hello.txt":"hello world\n","log.txt":"INFO\nERROR failure\n","utf8.txt":"سلام\n","nested/app.log":"INFO\nERROR nested\n","config.txt":"old\n","big.txt":"x"*1_100_100}
    workspace_cases=[
      ("066","list the files",[{"action":"tool","tool":"list_files","args":{"path":"."}},{"action":"final","answer":"ok"}],"completed",True),
      ("067","read hello.txt",[{"action":"tool","tool":"read_file","args":{"path":"hello.txt"}},{"action":"final","answer":"ok"}],"completed",True),
      ("068","find ERROR in log.txt",[{"action":"tool","tool":"search_in_file","args":{"path":"log.txt","query":"ERROR"}},{"action":"final","answer":"ok"}],"completed",True),
      ("069","write output.txt",[{"action":"tool","tool":"write_file","args":{"path":"output.txt","content":"sandbox"}},{"action":"final","answer":"ok"}],"completed",True),
      ("070","write outside",[{"action":"tool","tool":"write_file","args":{"path":"../escape.txt","content":"bad"}},{"action":"final","answer":"blocked"}],"failed",True),
      ("071","read missing.txt",[{"action":"tool","tool":"read_file","args":{"path":"missing.txt"}},{"action":"final","answer":"missing"}],"failed",True),
      ("072","read ../secret.txt",[{"action":"tool","tool":"read_file","args":{"path":"../secret.txt"}},{"action":"final","answer":"blocked"}],"failed",True),
      ("073","replace config.txt",[{"action":"tool","tool":"write_file","args":{"path":"config.txt","content":"new"}},{"action":"final","answer":"ok"}],"completed",True),
      ("074","read utf8.txt",[{"action":"tool","tool":"read_file","args":{"path":"utf8.txt"}},{"action":"final","answer":"ok"}],"completed",True),
      ("075","read big.txt",[{"action":"tool","tool":"read_file","args":{"path":"big.txt"}},{"action":"final","answer":"too big"}],"failed",True),
      ("076","search ERROR in nested/app.log",[{"action":"tool","tool":"search_in_file","args":{"path":"nested/app.log","query":"ERROR"}},{"action":"final","answer":"ok"}],"completed",True),
      ("077","write nested/new.txt",[{"action":"tool","tool":"write_file","args":{"path":"nested/new.txt","content":"ok"}},{"action":"final","answer":"ok"}],"completed",True),
      ("078","write output.txt but deny approval",[{"action":"tool","tool":"write_file","args":{"path":"output.txt","content":"sandbox"}},{"action":"final","answer":"denied"}],"cancelled",False),
      ("079","read via absolute traversal",[{"action":"tool","tool":"read_file","args":{"path":"/tmp/secret"}},{"action":"final","answer":"blocked"}],"failed",True),
      ("080","search text with empty query",[{"action":"tool","tool":"search_in_file","args":{"path":"log.txt","query":""}},{"action":"final","answer":"error"}],"failed",True),
    ]
    for i,g,a,exp,app in workspace_cases:S.append(Scenario(f"workspace.{i}","workspace",g,mode="react",actions=a,files=files,approve=app,expect_status=(exp,),postcheck="no_escape" if i in {"070","072","079"} else ("wrote" if i=="069" else "")))
    dev_py="[project]\nname='sandboxproj'\nversion='0.1.0'\n"
    test_ok="def test_ok():\n    assert 2+2==4\n"
    test_bad="def test_bad():\n    assert 2+2==5\n"
    devs=[
      ("081","inspect the project",{"pyproject.toml":dev_py,"test_demo.py":test_ok},"inspect_project"),("082","check the project",{"pyproject.toml":dev_py,"test_demo.py":test_ok},"check_project"),
      ("083","run the project tests",{"pyproject.toml":dev_py,"test_demo.py":test_ok},"check_project"),("084","run the project tests",{"pyproject.toml":dev_py,"test_demo.py":test_bad},"check_project"),
      ("085","inspect the repository",{"package.json":"{\"name\":\"demo\",\"scripts\":{\"test\":\"echo ok\"}}"},"inspect_project"),
      ("086","check project compile",{"pyproject.toml":dev_py},"check_project"),("087","inspect the project stack",{"go.mod":"module demo\n"},"inspect_project"),
      ("088","check the project with no manifest",{"README.md":"hello\n"},"check_project"),("089","inspect the project before editing it",{"pyproject.toml":dev_py},"inspect_project"),("090","run project tests",{"pyproject.toml":dev_py,"test_demo.py":test_ok},"check_project"),
    ]
    dev_fail = {"084", "088"}
    for i,g,files,t in devs:
        checks = ["compile", "pytest"]
        if i == "086": checks = ["compile"]
        expected = ("failed",) if i in dev_fail else ("completed",)
        S.append(Scenario(f"dev.{i}","development",g,mode="react",actions=[{"action":"tool","tool":t,"args":{"path":".","checks":checks} if t=="check_project" else {"path":"."}},{"action":"final","answer":"ok"}],files=files,expect_status=expected,required_tools=(t,),approve=True))
    research=[
      ("091","search the web for latest agent memory research","web_research"),("092","find recent academic papers about agent memory","arxiv_research"),("093","search github repositories for agentic rag","github_search"),
      ("094","research and learn about agent memory","research_and_learn"),("095","list skills","list_skills"),("096","match skills for data analysis","match_skills"),("097","discover skills for this task","discover_skills"),("098","research status","research_status"),
      ("099","predict what will happen if I write output.txt","simulate_action"),("100","network status","network_status"),
    ]
    for i,g,t in research:
        if t=="simulate_action":
            actions=[{"action":"tool","tool":"simulate_action","args":{"tool":"write_file","args":{"path":"output.txt","content":"x"}}},{"action":"final","answer":"simulated"}]
            S.append(Scenario(f"world.{i}","world",g,mode="react",actions=actions,required_tools=(t,),expect_status=("completed",)))
        elif t in {"web_research","arxiv_research","github_search","research_and_learn","list_skills","match_skills","discover_skills","research_status","network_status"}:
            S.append(Scenario(f"researchskills.{i}","research_skills",g,required_tools=(t,),expect_status=("completed","failed")))
    return S


def _sanitize(value):
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"/tmp/agent-real-user-100-[^/\s]+", "<sandbox>", value)
        value = re.sub(r"[A-Za-z]:\\Users\\[^\\]+\\AppData\\Local\\Temp\\agent-real-user-100-[^\\]+", "<sandbox>", value)
    return value


def build_catalog():
    return [
        {"id": s.id, "category": s.category, "goal": s.goal, "mode": s.mode,
         "turns": list(s.turns), "required_tools": list(s.required_tools),
         "forbidden_tools": list(s.forbidden_tools), "expected_status": list(s.expect_status),
         "postcheck": s.postcheck} for s in scenarios()
    ]


def run_campaign(report_path: str | Path | None = None, keep_sandboxes: bool = False) -> dict:
    patch_network()
    ss = scenarios()
    assert len(ss) == 100 and len({s.id for s in ss}) == 100, "100 unique scenarios required"
    base = Path(tempfile.mkdtemp(prefix="agent-real-user-100-"))
    results = []
    started = time.time()
    try:
        for idx, sc in enumerate(ss, 1):
            root = base / f"{idx:03d}"; root.mkdir()
            scenario_started = time.monotonic()
            try:
                state, ws = run_scenario(sc, root)
                ok, details = check(sc, state, ws)
                details["duration_ms"] = round((time.monotonic() - scenario_started) * 1000, 3)
                results.append({"n": idx, "id": sc.id, "category": sc.category, "goal": sc.goal, "ok": ok, "details": _sanitize(details)})
            except Exception as exc:
                results.append({"n": idx, "id": sc.id, "category": sc.category, "goal": sc.goal, "ok": False,
                                "details": {"exception": repr(exc), "duration_ms": round((time.monotonic()-scenario_started)*1000,3)}})
        categories = {}
        for row in results:
            cat = row["category"]; categories.setdefault(cat, {"count": 0, "passed": 0}); categories[cat]["count"] += 1; categories[cat]["passed"] += int(row["ok"])
        version_path = Path(__file__).resolve().parents[2] / "VERSION"
        version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else "unknown"
        report = {
            "suite": "real-user-100", "version": version, "count": 100,
            "passed": sum(int(x["ok"]) for x in results),
            "failed": sum(int(not x["ok"]) for x in results),
            "duration_seconds": round(time.time() - started, 3),
            "categories": categories, "results": results,
        }
        if report_path:
            Path(report_path).parent.mkdir(parents=True, exist_ok=True)
            Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        if not keep_sandboxes:
            shutil.rmtree(base, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="100 isolated real-user acceptance scenarios for Personal Agent")
    ap.add_argument("--report", default="docs/evaluation/REAL_USER_100_REPORT.json")
    ap.add_argument("--catalog", action="store_true", help="print the scenario catalog as JSON")
    ap.add_argument("--keep-sandboxes", action="store_true")
    args = ap.parse_args()
    if args.catalog:
        print(json.dumps(build_catalog(), ensure_ascii=False, indent=2))
        return
    report = run_campaign(args.report, args.keep_sandboxes)
    print(json.dumps({k: report[k] for k in ("count", "passed", "failed", "duration_seconds")}, ensure_ascii=False))
    for row in report["results"]:
        if not row["ok"]:
            print(f"FAIL {row['n']:03d} {row['id']} {json.dumps(row['details'], ensure_ascii=False)}")
    raise SystemExit(0 if report["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
