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
        if not isinstance(result.data, dict):
            return False, "dataset analysis tool returned invalid profile data"
        profile_shape = any(key in result.data for key in ("rows", "summary", "path"))
        answer_shape = bool(result.data.get("answer")) and bool(result.data.get("fingerprint")) and bool(result.data.get("source"))
        if not profile_shape and not answer_shape:
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

    if tool.name == "analyze_csv_collection":
        data = result.data if isinstance(result.data, dict) else {}
        files = data.get("files") or []
        selected = data.get("selected") or {}
        if not data.get("verified") or not files or not data.get("selected_path"):
            return False, "CSV collection analysis missing verified selection"
        expected = max(files, key=lambda x: (float(x.get("numeric_total_sum") or 0.0), str(x.get("path") or "")))
        if expected.get("path") != data.get("selected_path"):
            return False, "CSV collection selection does not match recomputed maximum"
    if tool.name == "move_workspace_file":
        data = result.data if isinstance(result.data, dict) else {}
        if not data.get("verified") or not data.get("destination_exists") or not data.get("fingerprint_match"):
            return False, "workspace move was not integrity-verified"
        if not data.get("unchanged_files_verified"):
            return False, "workspace move did not prove that other source files remained unchanged"
    if tool.name == "create_company_data_report":
        data = result.data if isinstance(result.data, dict) else {}
        if not data.get("verified") or not data.get("report_reread_verified") or not data.get("path"):
            return False, "company data report was not verified on disk"
    if tool.name == "analyze_csv_by_average":
        data = result.data if isinstance(result.data, dict) else {}
        files = data.get("files") or []
        if not data.get("verified") or not files or not data.get("selected_path") or data.get("selection_metric") != "average":
            return False, "CSV average ranking missing verified selection"
        expected = max(files, key=lambda x: (float(x.get("average") or 0.0), str(x.get("path") or "")))
        if expected.get("path") != data.get("selected_path"):
            return False, "CSV average selection does not match recomputed maximum"
    if tool.name == "create_sales_analysis_report":
        data = result.data if isinstance(result.data, dict) else {}
        if not data.get("verified") or not data.get("report_reread_verified") or not data.get("path"):
            return False, "sales analysis report was not verified on disk"
    if tool.name == "move_workspace_report":
        data = result.data if isinstance(result.data, dict) else {}
        if not data.get("verified") or not data.get("destination_exists") or not data.get("fingerprint_match") or not data.get("source_removed"):
            return False, "workspace report move was not integrity-verified"
    if tool.name == "organize_workspace_files":
        data = result.data if isinstance(result.data, dict) else {}
        if not data.get("verified") or not data.get("report_reread_verified"):
            return False, "workspace organization was not verified on disk"
        if int(data.get("original_file_count", -1)) != int(data.get("moved_file_count", -2)):
            return False, "workspace organization lost or skipped files"
        if int(data.get("verified_destination_count", -1)) != int(data.get("moved_file_count", -2)):
            return False, "workspace organization has unverified destinations"
        if not data.get("all_fingerprints_match") or not data.get("sources_cleared"):
            return False, "workspace organization failed conservation/fingerprint verification"
    if tool.name == "create_workspace_tree_inventory":
        data = result.data if isinstance(result.data, dict) else {}
        required = ("verified", "report_reread_verified", "filesystem_match", "folder_stats_match", "largest_5_match", "report_excluded")
        if not all(bool(data.get(key)) for key in required):
            return False, "recursive workspace inventory was not fully verified against live filesystem"
        if int(data.get("file_count", -1)) < 0 or len(data.get("largest_5") or []) > 5:
            return False, "recursive workspace inventory returned invalid ranking"
    if tool.name == "create_file_inventory":
        data = result.data if isinstance(result.data, dict) else {}
        snapshot = data.get("snapshot", []) or []
        try:
            count = int(data.get("file_count", -1))
        except Exception:
            count = -1
        if not data.get("verified") or count != len(snapshot):
            return False, "workspace inventory report was not verified against its source snapshot"
    if tool.name == "audit_project_tests":
        if not isinstance(result.data, dict) or int(result.data.get("attempted", 0)) <= 0:
            return False, "project audit ran no validation commands"
    if tool.name == "create_project_audit_report":
        if not isinstance(result.data, dict) or not result.data.get("verified") or not result.data.get("path"):
            return False, "project audit report was not verified on disk"
    if tool.name == "check_project":
        if not isinstance(result.data, dict) or "all_passed" not in result.data or "total" not in result.data:
            return False, "check_project missing validation result"
        if int(result.data.get("total", 0)) <= 0:
            return False, "check_project ran no checks"
        if not bool(result.data.get("all_passed")):
            return False, "project validation check failed"
    return True, "ok"
