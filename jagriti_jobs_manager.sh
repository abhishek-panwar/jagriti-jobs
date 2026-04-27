#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Jagriti Jobs Manager
# Usage: ./jagriti_jobs_manager.sh [command]
#   status    — show repo info + last workflow run
#   push      — push all local changes to GitHub
#   refresh   — trigger the job search workflow on GitHub
#   open      — open the live GitHub Pages site
#   help      — show this message
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/.jagriti_config"

if [ ! -f "$CONFIG" ]; then
  echo "❌  Config not found at $CONFIG"
  exit 1
fi

source "$CONFIG"

API="https://api.github.com"
AUTH="Authorization: Bearer $GITHUB_TOKEN"
REPO_API="$API/repos/$GITHUB_USER/$GITHUB_REPO"

case "${1:-help}" in

  # ── STATUS ──────────────────────────────────────────────────
  status)
    echo "📦  Repo: https://github.com/$GITHUB_USER/$GITHUB_REPO"
    echo "🌐  Live: $GITHUB_PAGES_URL"
    echo ""

    # Last workflow run
    RUN=$(curl -s -H "$AUTH" "$REPO_API/actions/runs?per_page=1" \
          | python3 -c "
import sys,json
d=json.load(sys.stdin)
runs=d.get('workflow_runs',[])
if runs:
    r=runs[0]
    print(f\"Last run: {r['name']} | Status: {r['status']} | Conclusion: {r.get('conclusion','—')} | {r['created_at']}\")
else:
    print('No workflow runs yet.')
")
    echo "⚙️   $RUN"

    # Pages status
    PAGES=$(curl -s -H "$AUTH" "$REPO_API/pages" \
            | python3 -c "
import sys,json
d=json.load(sys.stdin)
if 'html_url' in d:
    print(f\"Pages: {d['status']} | URL: {d['html_url']}\")
else:
    print('Pages not yet enabled.')
")
    echo "📄  $PAGES"
    ;;

  # ── PUSH ────────────────────────────────────────────────────
  push)
    echo "🚀  Pushing files to GitHub..."
    cd "$LOCAL_DIR" || exit 1

    # Init git if needed (isolated, won't affect system git config)
    if [ ! -d ".git" ]; then
      git init
      git remote add origin "https://$GITHUB_TOKEN@github.com/$GITHUB_USER/$GITHUB_REPO.git"
    fi

    # Make sure remote is set with token
    git remote set-url origin "https://$GITHUB_TOKEN@github.com/$GITHUB_USER/$GITHUB_REPO.git"

    # Stage all relevant files
    git add Jagriti_Job_Listings.html resumes/ .github/ 2>/dev/null
    git add Jagriti_Mahajan_Resume.html 2>/dev/null

    git -c user.email="abhishek-panwar@users.noreply.github.com" \
        -c user.name="Abhishek Panwar" \
        commit -m "Update job listings and resumes $(date '+%Y-%m-%d %H:%M')" 2>/dev/null || echo "Nothing new to commit."

    git push origin main --force-with-lease 2>/dev/null || git push origin main --force
    echo "✅  Pushed to https://github.com/$GITHUB_USER/$GITHUB_REPO"
    echo "🌐  Live at: $GITHUB_PAGES_URL"
    ;;

  # ── REFRESH ─────────────────────────────────────────────────
  refresh)
    echo "🔄  Triggering job search refresh on GitHub Actions..."
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST \
      -H "$AUTH" \
      -H "Content-Type: application/json" \
      "$REPO_API/dispatches" \
      -d '{"event_type":"refresh-jobs"}')

    if [ "$RESPONSE" = "204" ]; then
      echo "✅  Workflow triggered! Check progress at:"
      echo "    https://github.com/$GITHUB_USER/$GITHUB_REPO/actions"
      echo "    Page will update in ~2-3 minutes."
    else
      echo "❌  Failed to trigger workflow (HTTP $RESPONSE)"
      echo "    Make sure the Actions workflow is set up in the repo."
    fi
    ;;

  # ── OPEN ────────────────────────────────────────────────────
  open)
    echo "🌐  Opening $GITHUB_PAGES_URL ..."
    open "$GITHUB_PAGES_URL"
    ;;

  # ── HELP ────────────────────────────────────────────────────
  *)
    echo ""
    echo "Jagriti Jobs Manager"
    echo "────────────────────"
    echo "  ./jagriti_jobs_manager.sh status    Check repo + last workflow run"
    echo "  ./jagriti_jobs_manager.sh push       Push local changes to GitHub"
    echo "  ./jagriti_jobs_manager.sh refresh    Trigger job search refresh"
    echo "  ./jagriti_jobs_manager.sh open       Open the live page in browser"
    echo ""
    ;;
esac
