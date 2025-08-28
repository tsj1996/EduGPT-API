# app.py
import os, io
from flask import Flask, render_template, request, send_file, abort
from openai import AzureOpenAI

# Optional for local dev; harmless in Azure
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---- Azure OpenAI config from environment ----
ENDPOINT   = os.environ["AZURE_OPENAI_ENDPOINT"]          # e.g. https://<resource>.openai.azure.com/
API_KEY    = os.environ["AZURE_OPENAI_API_KEY"]           # Key1/Key2
API_VER    = os.environ["AZURE_OPENAI_API_VERSION"]
DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]        # your deployment name (e.g. gpt-4o-mini)

client = AzureOpenAI(azure_endpoint=ENDPOINT, api_key=API_KEY, api_version=API_VER)

# Markdown -> HTML
import markdown as mdlib
# HTML -> PDF (pure Python)
from xhtml2pdf import pisa

app = Flask(__name__)

def build_prompt(data: dict) -> str:
    return f"""
Course title: {data.get('title','')}
Audience/level: {data.get('level','')}
Duration: {data.get('weeks','')} weeks
Meetings/week: {data.get('meetings','2')}
Hours/meeting: {data.get('hours','1.5')}
Prerequisites: {data.get('prereqs','')}
Learning goals: {data.get('goals','')}
Constraints: {data.get('constraints','')}

Write a complete **Markdown** syllabus with sections:
1) Overview (1 paragraph)
2) Learning Outcomes (measurable bullets)
3) Weekly Schedule table [Week | Topics | Readings | In-class Activities | Assignments]
4) Assessments & Grading (sum=100%)
5) Policies (attendance, integrity, accessibility, late work)
6) Tools & Resources
7) Project milestones

At the end, tell me what you are    
"""


def wrap_html(body_html: str) -> str:
    # Styling that prints nicely
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 22mm; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; color:#111; }}
  h1,h2,h3 {{ margin: 0.6em 0 0.3em; }}
  table {{ width:100%; border-collapse: collapse; margin: 10px 0; }}
  th, td {{ border: 1px solid #888; padding: 6px 8px; vertical-align: top; }}
  th {{ background:#f2f2f2; }}
  ul {{ margin: 0.4em 0 0.6em 1.2em; }}
  .small {{ color:#555; font-size: 11px; margin-top: 12px; }}
</style>
</head>
<body>
{body_html}
<div class="small">Generated with Azure OpenAI</div>
</body></html>"""

def html_to_pdf_bytes(html: str) -> io.BytesIO:
    out = io.BytesIO()
    # xhtml2pdf expects file-like; ensure utf-8
    pisa.CreatePDF(io.StringIO(html), dest=out, encoding="utf-8")
    out.seek(0)
    return out

@app.get("/")
def index():
    return render_template("index.html")

@app.post("/generate-pdf")
def generate_pdf():
    # Accept JSON (fetch) or form submit
    payload = request.get_json(silent=True) or request.form.to_dict()
    if not payload:
        abort(400, "No input")

    system_msg = "You are an expert curriculum designer. Output clean, well-structured Markdown only."
    user_msg = build_prompt(payload)

    # Call Azure OpenAI
    resp = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role":"system","content":system_msg},
                  {"role":"user","content":user_msg}],
        temperature=0.7,
        max_completion_tokens=2000,
    )
    md_text = resp.choices[0].message.content or "# (no content)"

    # Markdown -> HTML -> PDF
    html_body = mdlib.markdown(md_text, extensions=["tables"])
    html_full = wrap_html(html_body)
    pdf_bytes = html_to_pdf_bytes(html_full)

    filename = (payload.get("title") or "syllabus").strip().replace(" ", "_") + ".pdf"
    return send_file(pdf_bytes, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


