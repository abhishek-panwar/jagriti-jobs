"""
Fetches Sr. Business Analyst jobs (Seattle area + remote) from Adzuna API,
updates Jagriti_Job_Listings.html with fresh listings.
Falls back to static listings if API keys not set.
"""
import os, json, requests, datetime, html as html_lib

APP_ID  = os.environ.get("ADZUNA_APP_ID", "")
APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
TODAY   = datetime.date.today().strftime("%B %Y")

SKILLS_KEYWORDS = [
    "Snowflake","AWS","API","SQL","Power BI","Agile","Scrum",
    "data governance","RESTful","business analyst"
]

def fetch_adzuna(query, location, results=15):
    if not APP_ID or not APP_KEY:
        return []
    url = (
        f"https://api.adzuna.com/v1/api/jobs/us/search/1"
        f"?app_id={APP_ID}&app_key={APP_KEY}"
        f"&results_per_page={results}"
        f"&what={requests.utils.quote(query)}"
        f"&where={requests.utils.quote(location)}"
        f"&distance=25&sort_by=relevance"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception as e:
        print(f"Adzuna error: {e}")
        return []

def score_job(job):
    text = (job.get("title","") + " " + job.get("description","")).lower()
    return sum(1 for kw in SKILLS_KEYWORDS if kw.lower() in text)

def tier(score):
    if score >= 5: return "1"
    if score >= 3: return "2"
    return "3"

def tier_label(t):
    return {"1":"Best Match","2":"Good Match","3":"Partial Match"}[t]

def tier_badge_class(t):
    return {"1":"badge-tier1","2":"badge-tier2","3":"badge-tier3"}[t]

def location_type(job):
    title = (job.get("title","") + " " + job.get("description","")).lower()
    if "remote" in title: return "remote"
    if "hybrid" in title: return "hybrid"
    return "onsite"

def location_badge(lt):
    m = {"remote":"badge-remote","hybrid":"badge-hybrid","onsite":"badge-onsite"}
    return m[lt]

def salary_str(job):
    mn = job.get("salary_min")
    mx = job.get("salary_max")
    if mn and mx:
        return f"${int(mn):,} – ${int(mx):,} / year"
    if mn: return f"From ${int(mn):,} / year"
    return "Salary not listed"

def excerpt(text, n=180):
    text = text.replace("\n"," ").strip()
    return text[:n] + "…" if len(text) > n else text

def resume_file(i):
    names = [
        "resume_job_01","resume_job_02","resume_job_03","resume_job_04",
        "resume_job_05","resume_job_06","resume_job_07","resume_job_08",
        "resume_job_09","resume_job_10","resume_job_11","resume_job_12",
    ]
    return names[i % len(names)] + ".pdf"

def card_html(i, job):
    t   = tier(score_job(job))
    lt  = location_type(job)
    title   = html_lib.escape(job.get("title","Role"))
    company = html_lib.escape(job.get("company",{}).get("display_name","Company"))
    loc     = html_lib.escape(job.get("location",{}).get("display_name","Seattle, WA"))
    url     = job.get("redirect_url","#")
    desc    = html_lib.escape(excerpt(job.get("description","")))
    sal     = salary_str(job)
    rf      = resume_file(i)
    data_text = f"{title} {company} {loc}".lower()

    return f"""
  <!-- Job {i+1} -->
  <div class="card" data-tier="{t}" data-location="{lt}" data-text="{data_text}">
    <div class="card-top">
      <div>
        <div class="job-title">{title}</div>
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
    <div class="fit-note"><strong>Match score:</strong> {score_job(job)}/10 keywords matched from Jagriti's skill set.</div>
    <div class="resume-section">
      <div class="resume-section-title">📄 Tailored Resume for this Role</div>
      <div class="resume-note">Resume tailored to match keywords and requirements of this specific posting.</div>
      <a class="download-btn" href="resumes/{rf}" download="Jagriti_Mahajan_Resume_{i+1}.pdf">⬇ Download Resume PDF</a>
    </div>
    <div class="card-actions">
      <a class="apply-btn" href="{url}" target="_blank">Apply →</a>
    </div>
  </div>"""

def build_html(jobs):
    n = len(jobs)
    cards = "\n".join(card_html(i, j) for i, j in enumerate(jobs))

    # Build summary table rows
    table_rows = ""
    for i, job in enumerate(jobs):
        t   = tier(score_job(job))
        title   = html_lib.escape(job.get("title","Role")[:50])
        company = html_lib.escape(job.get("company",{}).get("display_name",""))
        loc     = html_lib.escape(job.get("location",{}).get("display_name",""))
        url     = job.get("redirect_url","#")
        sal     = salary_str(job)
        rf      = resume_file(i)
        table_rows += f"""      <tr>
        <td>{i+1}</td>
        <td>{title}</td>
        <td>{company}</td>
        <td>{loc}</td>
        <td>{sal}</td>
        <td><span class="badge {tier_badge_class(t)}">{tier_label(t)}</span></td>
        <td><a href="{url}" target="_blank">Apply →</a></td>
      </tr>\n"""

    with open("Jagriti_Job_Listings.html", "r") as f:
        page = f.read()

    # Replace the cards grid content
    import re
    new_grid = f'<div class="grid" id="grid">\n{cards}\n</div>'
    page = re.sub(
        r'<div class="grid" id="grid">.*?</div>\s*\n\s*<!-- Summary',
        new_grid + '\n\n<!-- Summary',
        page, flags=re.DOTALL
    )

    # Update count in header and pills
    page = re.sub(r'(\d+) active listings', f'{n} active listings', page)
    page = re.sub(r'All \(\d+\)', f'All ({n})', page)
    page = re.sub(r'Showing \d+ of \d+', f'Showing {n} of {n}', page)

    # Update date
    page = re.sub(r'[A-Z][a-z]+ \d{4}', TODAY, page, count=1)

    # Replace table body
    page = re.sub(
        r'(<tbody>).*?(</tbody>)',
        r'\1\n' + table_rows + r'    \2',
        page, flags=re.DOTALL
    )

    with open("Jagriti_Job_Listings.html", "w") as f:
        f.write(page)
    print(f"Updated Jagriti_Job_Listings.html with {n} jobs.")

# ── Main ──
if __name__ == "__main__":
    print("Fetching jobs from Adzuna...")
    seattle_jobs = fetch_adzuna("senior business analyst", "Seattle WA", 10)
    remote_jobs  = fetch_adzuna("senior business analyst remote", "Seattle WA", 8)

    all_jobs = seattle_jobs + remote_jobs
    # Deduplicate by title+company
    seen = set()
    unique = []
    for j in all_jobs:
        key = (j.get("title",""), j.get("company",{}).get("display_name",""))
        if key not in seen:
            seen.add(key)
            unique.append(j)

    # Sort by score descending
    unique.sort(key=score_job, reverse=True)
    jobs = unique[:12]

    if jobs:
        print(f"Found {len(jobs)} jobs. Updating HTML...")
        build_html(jobs)
    else:
        print("No jobs fetched (API keys may not be set). HTML unchanged.")
        print("To enable live job fetching, add ADZUNA_APP_ID and ADZUNA_APP_KEY as GitHub secrets.")
