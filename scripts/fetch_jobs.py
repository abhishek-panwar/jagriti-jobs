"""
Fetches Sr. Business Analyst jobs from multiple sources:
  1. JSearch (RapidAPI) — LinkedIn, Indeed, Glassdoor, ZipRecruiter
     - 24h cooldown between calls (don't waste quota on rapid refresh clicks)
     - Monthly cap at 180 calls (leaves 20-call buffer on free plan)
     - Single combined query instead of 2 separate calls
  2. Adzuna — unlimited, runs on every refresh
  3. Remotive — unlimited, remote jobs

Threshold logic:
  - Reads resumes/applied_jobs.json to count applied jobs
  - Only fetches new jobs if >= 70% of current listings are applied (or cache is empty)
  - This prevents burning API quota on refreshes when most jobs are still unread

Saves:
  - resumes/jobs_cache.json  — full job list (used for threshold check next run)
  - resumes/fetch_meta.json  — JSearch usage tracking
"""
import os, re, json, requests, datetime

# ── API keys (env vars take precedence if set and non-empty) ──
ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID")  or "5975f043"
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY") or "8f81b1c0abed562e98c9a0d5a1890d93"
JSEARCH_KEY    = os.environ.get("JSEARCH_KEY")    or "58cd19e2f7msh91cf447019c17c1p1c8ca5jsnc4d911a8d7c9"
JSEARCH_HOST   = "jsearch.p.rapidapi.com"

TODAY = datetime.date.today().strftime("%B %Y")

# ── Resume-based profile (mirrors RESUME_PROFILE in the HTML) ──
SKILLS_KEYWORDS = [
    "Snowflake","AWS","SQL","Power BI","Tableau","Agile","Scrum","SAFe",
    "data governance","RESTful","RESTful API","API","JSON","Swagger","ReadyAPI",
    "BRD","FRD","UAT","ETL","data platform","analytics","requirements",
    "process improvement","user stories","stakeholder","metadata","Informatica",
    "Confluence","JIRA","data quality","data mapping","Visio","LucidChart",
    "DynamoDB","SQL Server","IBM DB2","Mainframe","Snowflake"
]

# ── Search query — mirrors RESUME_PROFILE.search_query in the HTML ──
# Add/remove terms here to change what all API sources fetch.
SEARCH_TERMS = [
    "business analyst",
    "product owner",
    "solutions architect",
    "systems analyst",
    "technical program manager",
    "data governance",
]
SEARCH_QUERY = " OR ".join(SEARCH_TERMS)

# Title regex — broad match against SEARCH_TERMS, excludes junior/associate/unrelated roles
TITLE_RE = re.compile(
    r'\b(?:sr\.?|senior|lead|principal|staff|enterprise|technical|it|data|systems?|product|solutions?|process|requirements)\s+'
    r'(?:(?:technical|it|data|systems?|product|solutions?|process|requirements)\s+)?'
    r'(?:business\s+analyst|ba)\b'
    r'|\bbusiness\s+(?:analyst|systems?\s+analyst|it\s+analyst|data\s+analyst|technical\s+analyst|solutions?\s+analyst|process\s+analyst|requirements\s+analyst)\b'
    r'|\bbusiness\s+analyst\s*(?:i{1,3}|iv|v|[1-5])?\b'
    r'|\bba[-\s]?(?:iii|3|iv|4)\b'
    r'|\b(?:sr\.?|senior|lead|principal|staff|technical|business)?\s*product\s+owner\b'
    r'|\bbusiness\s+systems?\s+\w+\b'
    r'|\bsolutions?\s+architect\b|\b(?:sr\.?|senior|lead|principal|staff|enterprise|technical)\s+(?:solutions?\s+)?architect\b'
    r'|\b(?:sr\.?|senior|lead|principal|staff|it|technical|enterprise)\s+systems?\s+analyst\b'
    r'|\b(?:sr\.?|senior|lead|principal|staff)?\s*technical\s+program\s+manager\b'
    r'|\bdata\s+governance\s+(?:analyst|specialist|manager|lead|director|engineer)\b',
    re.IGNORECASE
)
TITLE_EXCLUDE_RE = re.compile(r'\b(junior|jr\.?|associate|entry.level|marketing analyst|financial analyst)\b', re.IGNORECASE)

# ── Helpers ──
def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# ── Normalise raw job into common schema ──
def normalise(title, company, location, url, description, salary_min=None, salary_max=None, source="", listed=""):
    return {
        "title":       (title or "").strip(),
        "company":     (company or "").strip(),
        "location":    (location or "").strip(),
        "url":         url or "#",
        "description": (description or "").strip(),
        "salary_min":  salary_min,
        "salary_max":  salary_max,
        "source":      source,
        "listed":      listed or "",
    }

# ── Source 1: JSearch ──
def fetch_jsearch(query, num_results=15):
    jobs = []
    try:
        r = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers={"X-RapidAPI-Key": JSEARCH_KEY, "X-RapidAPI-Host": JSEARCH_HOST},
            params={"query": query, "page": "1", "num_pages": "2", "date_posted": "week"},
            timeout=15
        )
        r.raise_for_status()
        for j in r.json().get("data", [])[:num_results]:
            city  = j.get("job_city")  or ""
            state = j.get("job_state") or ""
            loc   = (city + (", " + state if state else "")).strip(", ") or "Seattle, WA"
            raw_date = j.get("job_posted_at_datetime_utc") or j.get("job_posted_at") or ""
            listed_date = raw_date[:10] if raw_date else ""
            jobs.append(normalise(
                title       = j.get("job_title") or "",
                company     = j.get("employer_name") or "",
                location    = loc,
                url         = j.get("job_apply_link") or j.get("job_google_link") or "#",
                description = (j.get("job_description") or "")[:600],
                salary_min  = j.get("job_min_salary"),
                salary_max  = j.get("job_max_salary"),
                source      = j.get("job_publisher") or "JSearch",
                listed      = listed_date
            ))
        print(f"  JSearch: {len(jobs)} jobs fetched")
    except Exception as e:
        print(f"  JSearch error: {e}")
    return jobs

# ── Source 2: Adzuna ──
def fetch_adzuna(query, location, results=10):
    jobs = []
    try:
        r = requests.get(
            "https://api.adzuna.com/v1/api/jobs/us/search/1",
            params={"app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
                    "results_per_page": results, "what": query,
                    "where": location, "distance": 25, "sort_by": "relevance"},
            timeout=15
        )
        r.raise_for_status()
        cutoff = datetime.date.today() - datetime.timedelta(days=7)
        for j in r.json().get("results", []):
            raw_date = j.get("created") or ""
            listed_date = raw_date[:10] if raw_date else ""
            if listed_date and datetime.date.fromisoformat(listed_date) < cutoff:
                continue
            mn, mx = j.get("salary_min"), j.get("salary_max")
            jobs.append(normalise(
                title       = j.get("title") or "",
                company     = j.get("company", {}).get("display_name") or "",
                location    = j.get("location", {}).get("display_name") or location,
                url         = j.get("redirect_url") or "#",
                description = (j.get("description") or "")[:600],
                salary_min  = int(mn) if mn else None,
                salary_max  = int(mx) if mx else None,
                source      = "Adzuna",
                listed      = listed_date
            ))
        print(f"  Adzuna ({location}): {len(jobs)} jobs fetched (last 7 days)")
    except Exception as e:
        print(f"  Adzuna error: {e}")
    return jobs

# ── Source 3: Remotive ──
def fetch_remotive(results=8):
    jobs = []
    try:
        r = requests.get(
            "https://remotive.com/api/remote-jobs",
            params={"category": "business", "search": "business analyst", "limit": results},
            timeout=15
        )
        r.raise_for_status()
        cutoff = datetime.date.today() - datetime.timedelta(days=7)
        for j in r.json().get("jobs", [])[:results]:
            raw_date = j.get("publication_date") or ""
            listed_date = raw_date[:10] if raw_date else ""
            if listed_date and datetime.date.fromisoformat(listed_date) < cutoff:
                continue
            desc = re.sub(r'<[^>]+>', '', j.get("description",""))[:600]
            jobs.append(normalise(
                title       = j.get("title") or "",
                company     = j.get("company_name") or "",
                location    = "Remote",
                url         = j.get("url") or "#",
                description = desc,
                source      = "Remotive",
                listed      = listed_date
            ))
        print(f"  Remotive: {len(jobs)} jobs fetched (last 7 days)")
    except Exception as e:
        print(f"  Remotive error: {e}")
    return jobs

# ── Scoring ──
def score_job(job):
    text = (job["title"] + " " + job["description"]).lower()
    return sum(1 for kw in SKILLS_KEYWORDS if kw.lower() in text)

def tier(score):
    if score >= 6: return "1"
    if score >= 3: return "2"
    return "3"

def slugify(s):
    s = re.sub(r'[^a-z0-9]+', '_', s.lower().strip())
    return re.sub(r'_+', '_', s).strip('_')[:60]

def job_id(job):
    return "job_" + slugify((job["title"] or "") + "_" + (job["company"] or ""))

# ── Main ──
if __name__ == "__main__":
    now = datetime.datetime.utcnow()

    # Load state files
    meta    = load_json("resumes/fetch_meta.json", {
        "jsearch_last_called": "2000-01-01T00:00:00",
        "jsearch_calls_this_month": 0,
        "jsearch_month": "2000-01"
    })
    # ── JSearch cooldown check ──
    try:
        jsearch_last = datetime.datetime.fromisoformat(meta.get("jsearch_last_called", "2000-01-01T00:00:00"))
    except Exception:
        jsearch_last = datetime.datetime(2000, 1, 1)

    hours_since = (now - jsearch_last).total_seconds() / 3600

    current_month = now.strftime("%Y-%m")
    if meta.get("jsearch_month") != current_month:
        meta["jsearch_month"]              = current_month
        meta["jsearch_calls_this_month"]   = 0

    monthly_calls   = meta.get("jsearch_calls_this_month", 0)
    can_use_jsearch = hours_since >= 24 and monthly_calls < 180

    if can_use_jsearch:
        print(f"JSearch: available (last used {hours_since:.1f}h ago, {monthly_calls}/180 calls this month)")
    elif hours_since < 24:
        print(f"JSearch: on 24h cooldown ({hours_since:.1f}h since last call) — using Adzuna + Remotive only")
    else:
        print(f"JSearch: monthly cap reached ({monthly_calls}/180) — using Adzuna + Remotive only")

    # ── Fetch ──
    all_jobs = []

    if can_use_jsearch:
        print("Fetching from JSearch (LinkedIn/Indeed/Glassdoor/ZipRecruiter)...")
        all_jobs += fetch_jsearch(f"({SEARCH_QUERY}) Seattle WA OR remote", num_results=18)
        meta["jsearch_last_called"]        = now.isoformat()
        meta["jsearch_calls_this_month"]   = monthly_calls + 1

    print("Fetching from Adzuna...")
    all_jobs += fetch_adzuna(SEARCH_QUERY, "Seattle WA", 12)
    all_jobs += fetch_adzuna(SEARCH_QUERY, "remote",     8)

    print("Fetching from Remotive...")
    all_jobs += fetch_remotive(8)

    # Deduplicate + title filter (resume-based regex, not hardcoded "Sr BA" only)
    seen, unique = set(), []
    for j in all_jobs:
        key = (j["title"].lower().strip(), j["company"].lower().strip())
        if key not in seen and j["title"] and j["company"]:
            if TITLE_RE.search(j["title"]) and not TITLE_EXCLUDE_RE.search(j["title"]):
                seen.add(key)
                j["id"] = job_id(j)
                unique.append(j)

    unique.sort(key=score_job, reverse=True)
    jobs = unique[:20]

    if not jobs:
        print("No jobs fetched from any source.")
        # Still write fetchedAt so the page poller knows the workflow ran
        save_json("resumes/new_jobs.json", {
            "jobs":       [],
            "totalCount": 0,
            "fetchedAt":  now.isoformat()
        })
        save_json("resumes/fetch_meta.json", meta)
        exit(0)

    print(f"\nTotal unique: {len(unique)} → keeping top {len(jobs)}")

    # ── Save new_jobs.json (read by the page) ──
    save_json("resumes/new_jobs.json", {
        "jobs":       jobs,
        "totalCount": len(jobs),
        "fetchedAt":  now.isoformat()
    })
    print(f"Saved {len(jobs)} jobs to resumes/new_jobs.json")

    # ── Save cache ──
    save_json("resumes/jobs_cache.json", {
        "jobs":       jobs,
        "totalCount": len(jobs),
        "fetchedAt":  now.isoformat()
    })

    # ── Save meta ──
    meta["lastFetch"] = now.isoformat()
    meta["jsearch_next_available"] = (
        (jsearch_last + datetime.timedelta(hours=24)).isoformat()
        if can_use_jsearch
        else (now + datetime.timedelta(hours=24)).isoformat()
    )
    save_json("resumes/fetch_meta.json", meta)
    print("Done. Cache and meta saved.")
