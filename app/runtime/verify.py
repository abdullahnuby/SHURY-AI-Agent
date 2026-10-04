"""Postcondition verification for tool results."""
def verify_step(tool, args, result) -> tuple[bool, str]:
    if not result.ok:
        return False, result.error or "tool failed"
    if tool.name in {"calculator", "calculate"}:
        if result.data is None:
            return False, "calculator returned no result"
        expr = str(args.get("expression") or "").strip()
        if expr:
            try:
                # Safe evaluation of basic math expressions to verify result
                import re
                clean_expr = expr.replace("×", "*").replace("÷", "/").replace(" ", "")
                if re.match(r"^[\d\.\+\-\*\/\(\)]+$", clean_expr):
                    expected = eval(clean_expr, {"__builtins__": None}, {})
                    actual = float(result.data)
                    if abs(actual - float(expected)) > 1e-5:
                        return False, f"calculator result verification failed: expected {expected}, got {result.data}"
            except Exception:
                pass
    if tool.name in {"remember_fact", "remember_result"}:
        if result.data is None:
            return False, f"{tool.name} returned no state confirmation"
    if tool.name == "save_note" and not str(result.data).startswith("تم الحفظ"):
        return False, "note tool returned an unexpected acknowledgement"
    if tool.name in {"read_file", "read_file_part"}:
        if result.data is None:
            return False, "file read tool returned no content"
    if tool.name in {"profile_dataset", "analyze_dataset"}:
        if not isinstance(result.data, dict) or ("rows" not in result.data and "summary" not in result.data and "path" not in result.data):
            return False, "dataset analysis tool returned invalid profile data"
    if tool.name in {"arxiv_research", "github_search", "internet_research"}:
        if not isinstance(result.data, dict) or "policy" not in result.data:
            return False, f"{tool.name} missing discovery provenance"
    if tool.name in {"web_research", "github_research"}:
        if not isinstance(result.data, dict) or "policy" not in result.data:
            return False, f"{tool.name} missing research provenance"
    if tool.name == "http_get":
        if not isinstance(result.data, dict) or not result.data.get("sha256") or not result.data.get("url"):
            return False, "http_get missing URL/hash provenance"
    if tool.name == "download_dataset":
        if not isinstance(result.data, dict) or not result.data.get("verified"):
            return False, "download_dataset failed local size verification"
    if tool.name == "check_project":
        if not isinstance(result.data, dict) or "all_passed" not in result.data or "total" not in result.data:
            return False, "check_project missing validation result"
        if int(result.data.get("total", 0)) <= 0:
            return False, "check_project ran no checks"
        if not bool(result.data.get("all_passed")):
            return False, "project validation check failed"
    return True, "ok"
