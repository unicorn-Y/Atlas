#!/usr/bin/env python3
"""Build MCP-TOOLS.tsv (office365 + github + runtime) with evidence offsets. Read-only input."""
import re, os

OUT = r"D:/Atlas/_research/claude-desktop/2026-10-20/index/work-P6/MCP-TOOLS.tsv"
O365 = r"D:/Atlas/_research/claude-desktop/2026-10-20/extract/_asar/resources/office365-mcp/office365-mcp-stdio.mjs"
EXE  = r"D:/Atlas/_research/claude-desktop/2026-10-20/extract/app/resources/app.asar.unpacked/resources/github-mcp/github-mcp-server.exe"
LZA  = r"D:/Atlas/_research/claude-desktop/2026-10-20/extract/_asar/.vite/build/index.chunk-lzaSYO3Q.js"
HEAVY= r"D:/Atlas/_research/claude-desktop/2026-10-20/extract/_asar/.vite/build/heavy-work-worker/heavyWorkWorker.js"

rows = []

# ---------- office365 ----------
s = open(O365, encoding='utf-8', errors='replace').read()

READ = ["sharepoint_search","sharepoint_folder_search","outlook_email_search","outlook_calendar_search",
        "find_meeting_availability","outlook_find_available_time","chat_message_search","teams_list_chats",
        "get_me","search_people","teams_list_teams","teams_list_channels","teams_list_channel_messages"]
RES  = ["onedrive_file","onedrive_drive","sharepoint_site","sharepoint_site_page","outlook_email_message",
        "outlook_folder","outlook_calendar_event","meeting_transcript","chat_message","channel_message"]
WRITE = ["outlook_send_mail","outlook_set_vacation","outlook_forward_mail","outlook_create_filter",
         "outlook_trash_thread","outlook_create_label","outlook_update_label","outlook_batch_delete_messages",
         "outlook_delete_label","outlook_untrash_thread","outlook_create_draft","outlook_create_reply_draft",
         "outlook_create_reply_all_draft","outlook_update_draft","outlook_send_draft","outlook_delete_draft",
         "outlook_create_event","outlook_update_event","outlook_delete_event","outlook_modify_labels",
         "outlook_delete_filter","outlook_modify_thread_labels","outlook_batch_modify_labels",
         "outlook_respond_to_event","sharepoint_upload_file","sharepoint_update_file","sharepoint_create_folder",
         "sharepoint_rename_item","sharepoint_move_item","sharepoint_copy_item","sharepoint_delete_item"]
TEAMS_W = ["teams_send_chat_message","teams_send_channel_message","teams_reply_channel_message","teams_create_chat"]
EXTRA = ["read_resource","get_granted_scopes"]

DESC_RE = re.compile(r"description=(?:\"((?:[^\"\\]|\\.){0,3000})\"|'((?:[^'\\]|\\.){0,3000})'|`((?:[^`\\]|\\.){0,3000})`)")


def desc_at(name):
    """Tool classes declare `name="x";description=...` (after) or `description=...;name="x"` (before).
    Prefer a literal that immediately follows the name; otherwise take the nearest one before it
    inside the same class body (no intervening name="")."""
    pos = s.find('name="%s"' % name)
    if pos < 0:
        return "", -1
    after = s[pos + len(name) + 8: pos + len(name) + 8 + 2500]
    # stop at the next name=" of a following class
    nxt = after.find('name="')
    if nxt != -1:
        after = after[:nxt]
    m = DESC_RE.search(after)
    if m:
        return (m.group(1) or m.group(2) or m.group(3) or "").strip().replace("\t", " ").replace("\n", " "), pos
    lo = max(0, pos - 2500)
    body = s[lo:pos]
    last_name = body.rfind('name="')
    best = ""
    for mm in DESC_RE.finditer(body):
        if last_name != -1 and mm.start() < last_name:
            continue
        cand = (mm.group(1) or mm.group(2) or mm.group(3) or "").strip()
        if len(cand) > len(best):
            best = cand
    return best.replace("\t", " ").replace("\n", " "), pos

for group, lst, ro in [("read", READ, True), ("write", WRITE, False), ("teams-write", TEAMS_W, False), ("extra", EXTRA, None)]:
    for n in lst:
        d, pos = desc_at(n)
        if pos < 0:
            rows.append(("office365", n, d or "(not found)", "missing", ""))
            continue
        rows.append(("office365", n, d, "declared",
                     f"office365-mcp-stdio.mjs@{pos} (name literal); registered via tool class .register() -> server.registerTool(this.name,...) @{s.find('async register(e){return e.registerTool(this.name')}"))

for n in RES:
    d, pos = desc_at(n)
    rows.append(("office365", f"resource:{n}", d or "(resource handler; no description)", "declared",
                 f"office365-mcp-stdio.mjs@{pos} (resource handler class); registry array @{s.find('read_resource_tool_registered')}"))

# ---------- github ----------
data = open(EXE, 'rb').read()
GH = """
get_me get_teams get_team_members
create_or_update_file search_repositories create_repository get_file_contents fork_repository
create_branch list_branches list_commits get_commit get_tag list_tags list_releases get_latest_release
get_release get_release_by_tag push_files delete_file get_repository_tree search_code get_repository
list_starred_repositories star_repository unstar_repository get_files get_file_blame list_repository_collaborators
create_issue list_issues get_issue update_issue add_issue_comment search_issues list_issue_types
issue_read issue_write sub_issue_write add_sub_issue remove_sub_issue reprioritize_sub_issue
assign_copilot_to_issue list_issue_fields get_issue_field create_issue_field update_issue_field
delete_issue_field set_issue_fields get_issue_field_values add_issue_field_values delete_issue_field_values
create_iteration_field add_issue_reaction add_issue_comment_reaction get_issue_comments update_issue_type
update_issue_assignees update_issue_milestone update_issue_labels update_issue_title update_issue_state
update_issue_suggestions add_issue_assignees
create_pull_request list_pull_requests merge_pull_request get_pull_request get_pull_request_files
get_pull_request_status update_pull_request_branch get_pull_request_comments get_pull_request_reviews
get_pull_request_diff create_pull_request_review create_pending_pull_request_review
add_comment_to_pending_review submit_pending_pull_request_review delete_pending_pull_request_review
add_reply_to_pull_request_comment request_copilot_review update_pull_request pull_request_read
pull_request_review_write update_pull_request_title update_pull_request_body update_pull_request_state
update_pull_request_draft_state request_pull_request_reviewers add_pull_request_review_comment
resolve_review_thread unresolve_review_thread pull_request_review_comment get_review_comments
list_workflow_runs list_workflow_jobs get_workflow_run get_workflow_job get_workflow_run_logs
get_workflow_run_usage get_workflow_job_logs get_workflow_run_logs_url download_workflow_run_artifact
list_workflow_run_artifacts run_workflow rerun_workflow_run rerun_failed_jobs cancel_workflow_run
delete_workflow_run_logs get_job_logs list_workflows
get_code_scanning_alert list_code_scanning_alerts get_secret_scanning_alert list_secret_scanning_alerts
get_dependabot_alert list_dependabot_alerts get_global_security_advisory list_global_security_advisories
list_repository_security_advisories get_repository_security_advisory get_code_quality_finding
list_notifications get_notification_details dismiss_notification mark_all_notifications_read
manage_notification_subscription manage_repository_notification_subscription
search_orgs list_org_repositories list_org_members search_users
get_discussion list_discussions get_discussion_comments list_discussion_categories discussion_comment_write
list_gists get_gist create_gist update_gist
get_label list_label create_label update_label delete_label label_write
get_project list_project_fields get_project_field list_project_items add_project_item
update_project_item delete_project_item get_project_status_update create_project_status_update
search_commits get_commits commit_comment get_comment
""".split()
seen = {}
for n in dict.fromkeys(GH):
    i = data.find(n.encode())
    if i >= 0 and n not in seen:
        seen[n] = i
# tool policy allow/ask map in main bundle gives an authoritative "these are real tool names" set
lza = open(LZA, encoding='utf-8', errors='replace').read()
policy = set(re.findall(r'([a-z0-9_]+):"ask"', lza[lza.find('var fOe={'):lza.find('var fOe={') + 6000]))
for n, off in sorted(seen.items(), key=lambda kv: kv[1]):
    ev = f"github-mcp-server.exe@{off} (name literal)"
    if n in policy:
        ev += f"; also in builtin tool-policy map lza@fOe (ask)"
    rows.append(("github", n, "(description not extracted: Go string table)", "declared", ev))

# ---------- runtime ----------
ws_off = lza.find('dKr="web_search"')
ws_conn = lza.find('connectWebSearchBuiltinMcp')
rows.append(("runtime", "web_search",
             "Search the public web (builtin websearch connector; provider brave/tavily/exa/custom)",
             "declared",
             "index.chunk-lzaSYO3Q.js@%d (WEB_SEARCH_TOOL_NAME); connectWebSearchBuiltinMcp @%d" % (ws_off, ws_conn)))
br_off = lza.find('/^mcp__(.+?)__(.+)$/')
rows.append(("runtime", "mcp__<server>__<tool>",
             "Bridge naming for every direct-MCP tool exposed to a remote/Cowork session",
             "declared",
             "index.chunk-lzaSYO3Q.js@%d (regex); bridge builder index.chunk-DlE0R5Pd.js@5135" % br_off))
dlq_data = open(r"D:/Atlas/_research/claude-desktop/2026-10-20/extract/_asar/.vite/build/index.chunk-DLqLwOmD.js", "rb").read()
sk_off = dlq_data.find(b"<invoke_with>")
rows.append(("runtime", "Skill",
             "Not an MCP tool: the Skill tool the CLI exposes for skills listed with <invoke_with>Skill tool</invoke_with>",
             "inferred",
             "index.chunk-DLqLwOmD.js@%d (<invoke_with> prompt clause)" % sk_off))

with open(OUT, "w", encoding="utf-8", newline="") as f:
    f.write("server\ttool_name\tdescription\tsource\tevidence\n")
    for r in rows:
        f.write("\t".join(r) + "\n")
print("wrote", OUT, "rows", len(rows))
print("office365:", sum(1 for r in rows if r[0]=='office365'), "github:", sum(1 for r in rows if r[0]=='github'), "runtime:", sum(1 for r in rows if r[0]=='runtime'))
