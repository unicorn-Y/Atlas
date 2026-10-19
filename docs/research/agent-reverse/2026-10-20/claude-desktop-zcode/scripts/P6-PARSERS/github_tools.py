#!/usr/bin/env python3
"""Verify GitHub MCP tool-name literals inside github-mcp-server.exe (read-only)."""
import re, sys, json

EXE = r"D:/Atlas/_research/claude-desktop/2026-10-20/extract/app/resources/app.asar.unpacked/resources/github-mcp/github-mcp-server.exe"

CANDIDATES = """
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
add_issue_assignees update_issue_assignees update_issue_milestone update_issue_labels update_issue_title
update_issue_state update_issue_suggestions create_issue_field delete_issue_field
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

def main():
    data = open(EXE, 'rb').read()
    found = {}
    for name in dict.fromkeys(CANDIDATES):
        i = data.find(name.encode())
        if i >= 0:
            found[name] = i
    # print as TSV-ish lines sorted by offset
    for name, off in sorted(found.items(), key=lambda kv: kv[1]):
        print(f"{off}\t{name}")
    print(f"# confirmed={len(found)} candidates={len(set(CANDIDATES))}")

if __name__ == '__main__':
    main()
