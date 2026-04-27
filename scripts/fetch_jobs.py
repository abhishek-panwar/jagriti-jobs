"""
Fetches Sr. Business Analyst jobs (Seattle area + remote) from Adzuna API,
updates Jagriti_Job_Listings.html with fresh listings.
"""
import os, re, json, requests, datetime, html as html_lib

APP_ID  = os.environ.get("ADZUNA_APP_ID",  "5975f043")
APP_KEY = os.environ.get("ADZUNA_APP_KEY", "8f81b1c0abed562e98c9a0d5a1890d93")
TODAY   = datetime.date.today().strftime("%B %Y")

SKILLS_KEYWORDS = [
    "Snowflake","AWS","API","SQL","Power BI","Agile","Scrum",
    "data governance","RESTful","business analyst","Tableau","stakeholder",
    "BRD","FRD","ETL","data platform","analytics"
]

def fetch_adzuna(query, location, results=15):
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
    if score >= 6: return "1"
    if score >= 3: return "2"
    return "3"

def tier_label(t):
    return {"1":"Best Match","2":"Good Match","3":"Partial Match"}[t]

def tier_badge_class(t):
    return {"1":"badge-tier1","2":"badge-tier2","3":"badge-tier3"}[t]

def location_type(job):
    text = (job.get("title","") + " " + job.get("description","")).lower()
    if "remote" in text: return "remote"
    if "hybrid" in text: return "hybrid"
    return "onsite"

def location_badge(lt):
    return {"remote":"badge-remote","hybrid":"badge-hybrid","onsite":"badge-onsite"}[lt]

def salary_str(job):
    mn, mx = job.get("salary_min"), job.get("salary_max")
    if mn and mx: return f"${int(mn):,} – ${int(mx):,} / year"
    if mn: return f"From ${int(mn):,} / year"
    return "Salary not listed"

def excerpt(text, n=200):
    text = text.replace("\n"," ").strip()
    return (text[:n] + "…") if len(text) > n else text

def slugify(s):
    s = re.sub(r'[^a-z0-9]+', '_', s.lower().strip())
    return re.sub(r'_+', '_', s).strip('_')[:40]

def job_id(job):
    title   = job.get("title","role")
    company = job.get("company",{}).get("display_name","co")
    return "job_" + slugify(title + "_" + company)

def resume_stem(i):
    return f"resume_job_{i+1:02d}"

def fit_note(job, t):
    score = score_job(job)
    matched = [kw for kw in SKILLS_KEYWORDS if kw.lower() in
               (job.get("title","") + " " + job.get("description","")).lower()]
    top = ", ".join(matched[:5]) if matched else "general BA skills"
    label = tier_label(t)
    return f"<strong>{label}:</strong> {score}/{len(SKILLS_KEYWORDS)} keywords matched — {top}."

def card_html(i, job):
    t       = tier(score_job(job))
    lt      = location_type(job)
    jid     = job_id(job)
    rstem   = resume_stem(i)
    title   = html_lib.escape(job.get("title","Role"))
    company = html_lib.escape(job.get("company",{}).get("display_name","Company"))
    loc     = html_lib.escape(job.get("location",{}).get("display_name","Seattle, WA"))
    url     = job.get("redirect_url","#")
    desc    = html_lib.escape(excerpt(job.get("description","")))
    sal     = salary_str(job)
    data_text = f"{title} {company} {loc}".lower()

    return f"""
  <!-- Job {i+1} -->
  <div class="card" data-tier="{t}" data-location="{lt}" data-id="{jid}" data-resume="{rstem}" data-text="{data_text}">
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
    <div class="fit-note">{fit_note(job, t)}</div>
    <div class="resume-section">
      <div class="resume-section-title">📄 Tailored Resume for this Role</div>
      <div class="resume-note">Resume summary tailored to match keywords and requirements of this specific posting.</div>
      <a class="download-btn" href="resumes/{rstem}.pdf" download="Jagriti_Mahajan_Resume_{i+1}.pdf">⬇ Download Resume PDF</a>
      <div class="change-note" id="change-{rstem}"></div>
    </div>
    <div class="card-actions">
      <a class="apply-btn" href="{url}" target="_blank">Apply →</a>
      <button class="applied-btn" onclick="markApplied('{jid}', this)">✓ Mark Applied</button>
    </div>
  </div>"""

def build_html(jobs):
    n = len(jobs)
    cards = "\n".join(card_html(i, j) for i, j in enumerate(jobs))

    table_rows = ""
    for i, job in enumerate(jobs):
        t       = tier(score_job(job))
        title   = html_lib.escape(job.get("title","Role")[:55])
        company = html_lib.escape(job.get("company",{}).get("display_name",""))
        loc     = html_lib.escape(job.get("location",{}).get("display_name",""))
        url     = job.get("redirect_url","#")
        sal     = salary_str(job)
        table_rows += f"""      <tr>
        <td>{i+1}</td><td>{title}</td><td>{company}</td><td>{loc}</td>
        <td>{sal}</td>
        <td><span class="badge {tier_badge_class(t)}">{tier_label(t)}</span></td>
        <td><a href="{url}" target="_blank">Apply →</a></td>
      </tr>\n"""

    with open("Jagriti_Job_Listings.html", "r") as f:
        page = f.read()

    # Replace cards grid
    new_grid = f'<div class="grid" id="grid">\n{cards}\n</div>'
    page = re.sub(
        r'<div class="grid" id="grid">.*?</div>\s*\n\s*<!-- (Summary|Bottom)',
        new_grid + '\n\n<!-- \\1',
        page, flags=re.DOTALL
    )

    # Update counts
    page = re.sub(r'\d+ active listings', f'{n} active listings', page)
    page = re.sub(r'All \(\d+\)', f'All ({n})', page)
    page = re.sub(r'Showing \d+ of \d+', f'Showing {n} of {n}', page)

    # Update date in header
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
    seattle_jobs = fetch_adzuna("senior business analyst", "Seattle WA", 12)
    remote_jobs  = fetch_adzuna("senior business analyst remote", "Seattle WA", 8)

    all_jobs = seattle_jobs + remote_jobs

    # Deduplicate by title+company
    seen, unique = set(), []
    for j in all_jobs:
        key = (j.get("title",""), j.get("company",{}).get("display_name",""))
        if key not in seen:
            seen.add(key)
            unique.append(j)

    # Sort by score descending
    unique.sort(key=score_job, reverse=True)
    jobs = unique[:15]  # keep up to 15 so there's always fresh ones after applied ones are hidden

    if jobs:
        print(f"Found {len(jobs)} jobs. Updating HTML...")
        build_html(jobs)
    else:
        print("No jobs fetched. HTML unchanged.")
