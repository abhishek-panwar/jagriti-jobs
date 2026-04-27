"""
Fetches Sr. Business Analyst jobs from multiple sources:
  1. JSearch (RapidAPI) — aggregates LinkedIn, Indeed, Glassdoor, ZipRecruiter
  2. Adzuna — general job board aggregator
  3. The Muse — curated professional roles (no key needed)
  4. Remotive — remote jobs (no key needed)
Deduplicates, scores by Jagriti's skill keywords, and updates the HTML.
"""
import os, re, json, requests, datetime, html as html_lib

# ── API keys ──
ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID",  "5975f043")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "8f81b1c0abed562e98c9a0d5a1890d93")
JSEARCH_KEY    = os.environ.get("JSEARCH_KEY",    "58cd19e2f7msh91cf447019c17c1p1c8ca5jsnc4d911a8d7c9")
JSEARCH_HOST   = "jsearch.p.rapidapi.com"

TODAY = datetime.date.today().strftime("%B %Y")

SKILLS_KEYWORDS = [
    "Snowflake", "AWS", "API", "SQL", "Power BI", "Agile", "Scrum",
    "data governance", "RESTful", "business analyst", "Tableau", "stakeholder",
    "BRD", "FRD", "ETL", "data platform", "analytics", "requirements",
    "process improvement", "user stories", "UAT"
]

# ── Normalise a raw job dict into a common schema ──
def normalise(title, company, location, url, description, salary_min=None, salary_max=None, source=""):
    return {
        "title":       title.strip(),
        "company":     company.strip(),
        "location":    location.strip(),
        "url":         url,
        "description": description.strip(),
        "salary_min":  salary_min,
        "salary_max":  salary_max,
        "source":      source,
    }

# ── Source 1: JSearch (LinkedIn / Indeed / Glassdoor / ZipRecruiter) ──
def fetch_jsearch(query, location, num_results=10):
    jobs = []
    try:
        r = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers={"X-RapidAPI-Key": JSEARCH_KEY, "X-RapidAPI-Host": JSEARCH_HOST},
            params={"query": f"{query} in {location}", "page": "1", "num_pages": "2",
                    "date_posted": "month"},
            timeout=15
        )
        r.raise_for_status()
        for j in r.json().get("data", [])[:num_results]:
            jobs.append(normalise(
                title       = j.get("job_title", ""),
                company     = j.get("employer_name", ""),
                location    = j.get("job_city", "") + (", " + j.get("job_state", "") if j.get("job_state") else ""),
                url         = j.get("job_apply_link") or j.get("job_google_link", "#"),
                description = j.get("job_description", "")[:600],
                salary_min  = j.get("job_min_salary"),
                salary_max  = j.get("job_max_salary"),
                source      = j.get("job_publisher", "JSearch")
            ))
        print(f"  JSearch: {len(jobs)} jobs")
    except Exception as e:
        print(f"  JSearch error: {e}")
    return jobs

# ── Source 2: Adzuna ──
def fetch_adzuna(query, location, results=10):
    jobs = []
    try:
        r = requests.get(
            f"https://api.adzuna.com/v1/api/jobs/us/search/1",
            params={"app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
                    "results_per_page": results, "what": query,
                    "where": location, "distance": 25, "sort_by": "relevance"},
            timeout=15
        )
        r.raise_for_status()
        for j in r.json().get("results", []):
            mn = j.get("salary_min")
            mx = j.get("salary_max")
            jobs.append(normalise(
                title       = j.get("title", ""),
                company     = j.get("company", {}).get("display_name", ""),
                location    = j.get("location", {}).get("display_name", location),
                url         = j.get("redirect_url", "#"),
                description = j.get("description", "")[:600],
                salary_min  = int(mn) if mn else None,
                salary_max  = int(mx) if mx else None,
                source      = "Adzuna"
            ))
        print(f"  Adzuna: {len(jobs)} jobs")
    except Exception as e:
        print(f"  Adzuna error: {e}")
    return jobs

# ── Source 3: The Muse (no key needed) ──
def fetch_the_muse(results=10):
    jobs = []
    try:
        r = requests.get(
            "https://www.themuse.com/api/public/jobs",
            params={"category": "Business & Strategy", "level": "Senior Level",
                    "location": "Seattle, WA", "page": 0, "descending": "true"},
            timeout=15
        )
        r.raise_for_status()
        for j in r.json().get("results", [])[:results]:
            loc_list = [loc.get("name","") for loc in j.get("locations", [])]
            loc = ", ".join(loc_list) if loc_list else "Seattle, WA"
            contents = j.get("contents","").replace("<br/>","\n")
            contents = re.sub(r'<[^>]+>', '', contents)[:600]
            jobs.append(normalise(
                title       = j.get("name",""),
                company     = j.get("company",{}).get("name",""),
                location    = loc,
                url         = j.get("refs",{}).get("landing_page","#"),
                description = contents,
                source      = "The Muse"
            ))
        print(f"  The Muse: {len(jobs)} jobs")
    except Exception as e:
        print(f"  The Muse error: {e}")
    return jobs

# ── Source 4: Remotive (remote only, no key needed) ──
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
                title       = j.get("title",""),
                company     = j.get("company_name",""),
                location    = "Remote",
                url         = j.get("url","#"),
                description = desc,
                source      = "Remotive"
            ))
        print(f"  Remotive: {len(jobs)} jobs")
    except Exception as e:
        print(f"  Remotive error: {e}")
    return jobs

# ── Scoring & helpers ──
def score_job(job):
    text = (job["title"] + " " + job["description"]).lower()
    return sum(1 for kw in SKILLS_KEYWORDS if kw.lower() in text)

def tier(score):
    if score >= 6: return "1"
    if score >= 3: return "2"
    return "3"

def tier_label(t):
    return {"1": "Best Match", "2": "Good Match", "3": "Partial Match"}[t]

def tier_badge_class(t):
    return {"1": "badge-tier1", "2": "badge-tier2", "3": "badge-tier3"}[t]

def location_type(job):
    text = (job["title"] + " " + job["description"] + " " + job["location"]).lower()
    if "remote" in text: return "remote"
    if "hybrid" in text: return "hybrid"
    return "onsite"

def location_badge(lt):
    return {"remote": "badge-remote", "hybrid": "badge-hybrid", "onsite": "badge-onsite"}[lt]

def salary_str(job):
    mn, mx = job.get("salary_min"), job.get("salary_max")
    if mn and mx: return f"${int(mn):,} – ${int(mx):,} / year"
    if mn: return f"From ${int(mn):,} / year"
    return "Salary not listed"

def excerpted(text, n=220):
    text = text.replace("\n", " ").strip()
    return (text[:n] + "…") if len(text) > n else text

def slugify(s):
    s = re.sub(r'[^a-z0-9]+', '_', s.lower().strip())
    return re.sub(r'_+', '_', s).strip('_')[:40]

def job_id(job):
    return "job_" + slugify(job["title"] + "_" + job["company"])

def resume_stem(i):
    return f"resume_job_{i+1:02d}"

def fit_note(job, t):
    score = score_job(job)
    matched = [kw for kw in SKILLS_KEYWORDS
               if kw.lower() in (job["title"] + " " + job["description"]).lower()]
    top = ", ".join(matched[:5]) if matched else "general BA skills"
    src = job.get("source", "")
    src_note = f" &nbsp;·&nbsp; via <em>{html_lib.escape(src)}</em>" if src else ""
    return (f"<strong>{tier_label(t)}:</strong> {score}/{len(SKILLS_KEYWORDS)} keywords matched "
            f"— {html_lib.escape(top)}.{src_note}")

def source_badge(job):
    src = job.get("source", "")
    colors = {
        "LinkedIn":  ("#0a66c2", "#e8f0fb"),
        "Indeed":    ("#2d2d2d", "#f3f4f6"),
        "Glassdoor": ("#0caa41", "#d1fae5"),
        "ZipRecruiter": ("#4b0082", "#f3e8ff"),
        "The Muse":  ("#ff6b35", "#fff3ed"),
        "Remotive":  ("#7c3aed", "#f5f3ff"),
        "Adzuna":    ("#1a56a4", "#e8f0fb"),
    }
    for name, (fg, bg) in colors.items():
        if name.lower() in src.lower():
            return f'<span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:999px;background:{bg};color:{fg};margin-left:4px">{name}</span>'
    return f'<span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:999px;background:#f3f4f6;color:#374151;margin-left:4px">{html_lib.escape(src)}</span>'

# ── Card HTML ──
def card_html(i, job):
    t     = tier(score_job(job))
    lt    = location_type(job)
    jid   = job_id(job)
    rstem = resume_stem(i)
    title   = html_lib.escape(job["title"])
    company = html_lib.escape(job["company"])
    loc     = html_lib.escape(job["location"])
    url     = job["url"]
    desc    = html_lib.escape(excerpted(job["description"]))
    sal     = salary_str(job)
    data_text = f"{title} {company} {loc}".lower()

    return f"""
  <!-- Job {i+1} -->
  <div class="card" data-tier="{t}" data-location="{lt}" data-id="{jid}" data-resume="{rstem}" data-text="{data_text}">
    <div class="card-top">
      <div>
        <div class="job-title">{title} {source_badge(job)}</div>
        <div class="company">{company}</div>
      </div>
      <div class="badges">
        <span class="badge {location_badge(lt)}">{lt.capitalize()}</span>
        <span class="badge {tier_badge_class(t)}">{tier_label(t)}</span>
      </div>
    </div>
    <div class="location">📍 {loc}</div>
    <div class="salary">{sal}</div>
    <ul class="requirements">
      <li>{desc}</li>
    </ul>
    <div class="fit-note">{fit_note(job, t)}</div>
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

# ── Rebuild HTML ──
def build_html(jobs):
    n = len(jobs)
    cards = "\n".join(card_html(i, j) for i, j in enumerate(jobs))

    table_rows = ""
    for i, job in enumerate(jobs):
        t       = tier(score_job(job))
        title   = html_lib.escape(job["title"][:55])
        company = html_lib.escape(job["company"])
        loc     = html_lib.escape(job["location"])
        url     = job["url"]
        sal     = salary_str(job)
        src     = html_lib.escape(job.get("source",""))
        table_rows += (
            f"      <tr><td>{i+1}</td><td>{title}</td><td>{company}</td>"
            f"<td>{loc}</td><td>{sal}</td>"
            f"<td><span class='badge {tier_badge_class(t)}'>{tier_label(t)}</span></td>"
            f"<td><a href='{url}' target='_blank'>Apply →</a></td></tr>\n"
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
    page = re.sub(r'All \(\d+\)', f'All ({n})', page)
    page = re.sub(r'Showing \d+ of \d+', f'Showing {n} of {n}', page)
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
    all_jobs = []

    print("Fetching from JSearch (LinkedIn/Indeed/Glassdoor/ZipRecruiter)...")
    all_jobs += fetch_jsearch("senior business analyst", "Seattle WA", 12)
    all_jobs += fetch_jsearch("senior business analyst remote", "USA", 8)

    print("Fetching from Adzuna...")
    all_jobs += fetch_adzuna("senior business analyst", "Seattle WA", 10)
    all_jobs += fetch_adzuna("senior business analyst remote", "Seattle WA", 8)

    print("Fetching from The Muse...")
    all_jobs += fetch_the_muse(8)

    print("Fetching from Remotive...")
    all_jobs += fetch_remotive(6)

    # Deduplicate by normalised title+company
    seen, unique = set(), []
    for j in all_jobs:
        key = (j["title"].lower().strip(), j["company"].lower().strip())
        if key not in seen and j["title"] and j["company"]:
            seen.add(key)
            unique.append(j)

    # Sort by score descending, keep top 20
    unique.sort(key=score_job, reverse=True)
    jobs = unique[:20]

    if jobs:
        print(f"\nTotal unique jobs after dedup: {len(unique)} → keeping top {len(jobs)}")
        build_html(jobs)
    else:
        print("No jobs fetched from any source. HTML unchanged.")
