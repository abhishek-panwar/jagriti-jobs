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
import os, re, json, requests, datetime, html as html_lib

# ── API keys (env vars take precedence if set and non-empty) ──
ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID")  or "5975f043"
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY") or "8f81b1c0abed562e98c9a0d5a1890d93"
JSEARCH_KEY    = os.environ.get("JSEARCH_KEY")    or "58cd19e2f7msh91cf447019c17c1p1c8ca5jsnc4d911a8d7c9"
JSEARCH_HOST   = "jsearch.p.rapidapi.com"

TODAY = datetime.date.today().strftime("%B %Y")

SKILLS_KEYWORDS = [
    "Snowflake","AWS","API","SQL","Power BI","Agile","Scrum",
    "data governance","RESTful","business analyst","Tableau","stakeholder",
    "BRD","FRD","ETL","data platform","analytics","requirements",
    "process improvement","user stories","UAT"
]

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
def normalise(title, company, location, url, description, salary_min=None, salary_max=None, source=""):
    return {
        "title":       (title or "").strip(),
        "company":     (company or "").strip(),
        "location":    (location or "").strip(),
        "url":         url or "#",
        "description": (description or "").strip(),
        "salary_min":  salary_min,
        "salary_max":  salary_max,
        "source":      source,
    }

# ── Source 1: JSearch ──
def fetch_jsearch(query, num_results=15):
    jobs = []
    try:
        r = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers={"X-RapidAPI-Key": JSEARCH_KEY, "X-RapidAPI-Host": JSEARCH_HOST},
            params={"query": query, "page": "1", "num_pages": "2", "date_posted": "month"},
            timeout=15
        )
        r.raise_for_status()
        for j in r.json().get("data", [])[:num_results]:
            city  = j.get("job_city")  or ""
            state = j.get("job_state") or ""
            loc   = (city + (", " + state if state else "")).strip(", ") or "Seattle, WA"
            jobs.append(normalise(
                title       = j.get("job_title") or "",
                company     = j.get("employer_name") or "",
                location    = loc,
                url         = j.get("job_apply_link") or j.get("job_google_link") or "#",
                description = (j.get("job_description") or "")[:600],
                salary_min  = j.get("job_min_salary"),
                salary_max  = j.get("job_max_salary"),
                source      = j.get("job_publisher") or "JSearch"
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
        for j in r.json().get("results", []):
            mn, mx = j.get("salary_min"), j.get("salary_max")
            jobs.append(normalise(
                title       = j.get("title") or "",
                company     = j.get("company", {}).get("display_name") or "",
                location    = j.get("location", {}).get("display_name") or location,
                url         = j.get("redirect_url") or "#",
                description = (j.get("description") or "")[:600],
                salary_min  = int(mn) if mn else None,
                salary_max  = int(mx) if mx else None,
                source      = "Adzuna"
            ))
        print(f"  Adzuna ({location}): {len(jobs)} jobs fetched")
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
        for j in r.json().get("jobs", [])[:results]:
            desc = re.sub(r'<[^>]+>', '', j.get("description",""))[:600]
            jobs.append(normalise(
                title       = j.get("title") or "",
                company     = j.get("company_name") or "",
                location    = "Remote",
                url         = j.get("url") or "#",
                description = desc,
                source      = "Remotive"
            ))
        print(f"  Remotive: {len(jobs)} jobs fetched")
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

def tier_label(t):   return {"1":"Best Match","2":"Good Match","3":"Partial Match"}[t]
def tier_badge(t):   return {"1":"badge-tier1","2":"badge-tier2","3":"badge-tier3"}[t]

def location_type(job):
    text = (job["title"] + " " + job["description"] + " " + job["location"]).lower()
    if "remote" in text: return "remote"
    if "hybrid" in text: return "hybrid"
    return "onsite"

def loc_badge(lt):   return {"remote":"badge-remote","hybrid":"badge-hybrid","onsite":"badge-onsite"}[lt]

def salary_str(job):
    mn, mx = job.get("salary_min"), job.get("salary_max")
    if mn and mx: return f"${int(mn):,} – ${int(mx):,} / year"
    if mn: return f"From ${int(mn):,} / year"
    return "Salary not listed"

def excerpt(text, n=220):
    text = text.replace("\n"," ").strip()
    return (text[:n] + "…") if len(text) > n else text

def slugify(s):
    s = re.sub(r'[^a-z0-9]+', '_', s.lower().strip())
    return re.sub(r'_+', '_', s).strip('_')[:40]

def job_id(job):
    return "job_" + slugify((job["title"] or "") + "_" + (job["company"] or ""))

def resume_stem(i):
    return f"resume_job_{i+1:02d}"

def source_badge_html(job):
    src = job.get("source", "")
    colors = {
        "LinkedIn":     ("#0a66c2","#e8f0fb"),
        "Indeed":       ("#2d2d2d","#f3f4f6"),
        "Glassdoor":    ("#0caa41","#d1fae5"),
        "ZipRecruiter": ("#4b0082","#f3e8ff"),
        "Remotive":     ("#7c3aed","#f5f3ff"),
        "Adzuna":       ("#1a56a4","#e8f0fb"),
    }
    for name, (fg, bg) in colors.items():
        if name.lower() in src.lower():
            return (f'<span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:999px;'
                    f'background:{bg};color:{fg};margin-left:4px">{name}</span>')
    return (f'<span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:999px;'
            f'background:#f3f4f6;color:#374151;margin-left:4px">{html_lib.escape(src)}</span>')

def fit_note_html(job, t):
    score   = score_job(job)
    matched = [kw for kw in SKILLS_KEYWORDS
               if kw.lower() in (job["title"] + " " + job["description"]).lower()]
    top = html_lib.escape(", ".join(matched[:5])) if matched else "general BA skills"
    src = html_lib.escape(job.get("source",""))
    src_note = f" &nbsp;·&nbsp; via <em>{src}</em>" if src else ""
    return (f'<strong>{tier_label(t)}:</strong> {score}/{len(SKILLS_KEYWORDS)} keywords matched '
            f'— {top}.{src_note}')

def card_html(i, job):
    t     = tier(score_job(job))
    lt    = location_type(job)
    jid   = job_id(job)
    rstem = resume_stem(i)
    title   = html_lib.escape(job["title"])
    company = html_lib.escape(job["company"])
    loc     = html_lib.escape(job["location"])
    url     = job["url"]
    desc    = html_lib.escape(excerpt(job["description"]))
    sal     = salary_str(job)
    data_text = f"{title} {company} {loc}".lower()
    return f"""
  <!-- Job {i+1} -->
  <div class="card" data-tier="{t}" data-location="{lt}" data-id="{jid}" data-resume="{rstem}" data-text="{data_text}">
    <div class="card-top">
      <div>
        <div class="job-title">{title} {source_badge_html(job)}</div>
        <div class="company">{company}</div>
      </div>
      <div class="badges">
        <span class="badge {loc_badge(lt)}">{lt.capitalize()}</span>
        <span class="badge {tier_badge(t)}">{tier_label(t)}</span>
      </div>
    </div>
    <div class="location">📍 {loc}</div>
    <div class="salary">{sal}</div>
    <ul class="requirements"><li>{desc}</li></ul>
    <div class="fit-note">{fit_note_html(job, t)}</div>
    <div class="resume-section">
      <div class="resume-section-title">📄 Tailored Resume for this Role</div>
      <div class="resume-note">Resume summary tailored to match keywords and requirements of this posting.</div>
      <a class="download-btn" href="resumes/{rstem}.pdf" download="Jagriti_Mahajan_Resume_{i+1}.pdf">⬇ Download Resume PDF</a>
      <div class="change-note" id="change-{rstem}"></div>
    </div>
    <div class="card-actions">
      <a class="apply-btn" href="{url}" target="_blank">Apply →</a>
      <button class="applied-btn" onclick="markApplied('{jid}', this)">✓ Mark Applied</button>
    </div>
  </div>"""

def build_html(jobs):
    n     = len(jobs)
    cards = "\n".join(card_html(i, j) for i, j in enumerate(jobs))
    table_rows = ""
    for i, job in enumerate(jobs):
        t       = tier(score_job(job))
        title   = html_lib.escape(job["title"][:55])
        company = html_lib.escape(job["company"])
        loc     = html_lib.escape(job["location"])
        sal     = salary_str(job)
        table_rows += (
            f"      <tr><td>{i+1}</td><td>{title}</td><td>{company}</td>"
            f"<td>{loc}</td><td>{sal}</td>"
            f"<td><span class='badge {tier_badge(tier(score_job(job)))}'>{tier_label(tier(score_job(job)))}</span></td>"
            f"<td><a href='{job['url']}' target='_blank'>Apply →</a></td></tr>\n"
        )
    with open("Jagriti_Job_Listings.html", "r") as f:
        page = f.read()
    new_grid = f'<div class="grid" id="grid">\n{cards}\n</div>'
    page = re.sub(
        r'<div class="grid" id="grid">.*?</div>\s*\n\s*<!-- (Summary|Bottom)',
        new_grid + '\n\n<!-- \\1',
        page, flags=re.DOTALL
    )
    page = re.sub(r'\d+ active listings', f'{n} active listings', page)
    page = re.sub(r'All \(\d+\)',          f'All ({n})',           page)
    page = re.sub(r'Showing \d+ of \d+',  f'Showing {n} of {n}',  page)
    page = re.sub(r'[A-Z][a-z]+ \d{4}', TODAY, page, count=1)
    page = re.sub(
        r'(<tbody>).*?(</tbody>)',
        r'\1\n' + table_rows + r'    \2',
        page, flags=re.DOTALL
    )
    with open("Jagriti_Job_Listings.html", "w") as f:
        f.write(page)
    print(f"Updated HTML with {n} jobs.")

# ── Main ──
if __name__ == "__main__":
    now = datetime.datetime.utcnow()

    # Load state files
    meta    = load_json("resumes/fetch_meta.json", {
        "jsearch_last_called": "2000-01-01T00:00:00",
        "jsearch_calls_this_month": 0,
        "jsearch_month": "2000-01"
    })
    applied_data = load_json("resumes/applied_jobs.json", {"applied": []})
    cache_data   = load_json("resumes/jobs_cache.json",   {"jobs": [], "totalCount": 0})

    # ── Check 70% threshold ──
    cached_jobs  = cache_data.get("jobs", [])
    total_cached = len(cached_jobs)
    applied_ids  = {j["id"] for j in applied_data.get("applied", [])}
    applied_count = sum(1 for j in cached_jobs if j.get("id") in applied_ids)
    pct = (applied_count / total_cached * 100) if total_cached > 0 else 100
    threshold_met = total_cached == 0 or pct >= 70

    print(f"Applied: {applied_count}/{total_cached} ({pct:.0f}%) — threshold {'MET ✓' if threshold_met else f'not met (need 70%)'}")

    if not threshold_met:
        print(f"Skipping fetch — only {pct:.0f}% of jobs applied. Refresh will fetch new jobs once ≥70% are applied.")
        meta["threshold_status"] = {"applied": applied_count, "total": total_cached, "pct": round(pct), "met": False}
        save_json("resumes/fetch_meta.json", meta)
        exit(0)

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
        # Single combined call instead of two — saves quota
        all_jobs += fetch_jsearch("senior business analyst Seattle WA OR remote", num_results=18)
        meta["jsearch_last_called"]        = now.isoformat()
        meta["jsearch_calls_this_month"]   = monthly_calls + 1

    print("Fetching from Adzuna...")
    all_jobs += fetch_adzuna("senior business analyst", "Seattle WA", 12)
    all_jobs += fetch_adzuna("senior business analyst", "remote",     8)

    print("Fetching from Remotive...")
    all_jobs += fetch_remotive(8)

    # Deduplicate
    seen, unique = set(), []
    for j in all_jobs:
        key = (j["title"].lower().strip(), j["company"].lower().strip())
        if key not in seen and j["title"] and j["company"]:
            seen.add(key)
            j["id"] = job_id(j)     # bake in stable ID
            unique.append(j)

    unique.sort(key=score_job, reverse=True)
    jobs = unique[:20]

    if not jobs:
        print("No jobs fetched from any source. HTML unchanged.")
        save_json("resumes/fetch_meta.json", meta)
        exit(0)

    print(f"\nTotal unique: {len(unique)} → keeping top {len(jobs)}")

    # ── Update HTML ──
    build_html(jobs)

    # ── Save cache (workflow reads this next run for threshold check) ──
    save_json("resumes/jobs_cache.json", {
        "jobs":       jobs,
        "totalCount": len(jobs),
        "fetchedAt":  now.isoformat()
    })

    # ── Save meta ──
    meta["threshold_status"] = {
        "applied": applied_count, "total": len(jobs),
        "pct": 0,   # freshly fetched, 0% applied
        "met": True,
        "lastFetch": now.isoformat()
    }
    meta["jsearch_next_available"] = (
        (jsearch_last + datetime.timedelta(hours=24)).isoformat()
        if can_use_jsearch
        else (now + datetime.timedelta(hours=24)).isoformat()
    )
    save_json("resumes/fetch_meta.json", meta)
    print("Done. Cache and meta saved.")
