from flask import Flask, render_template, request, send_file, jsonify, abort
from openai import AzureOpenAI
import os, io, re, traceback
from markdown import markdown
from xhtml2pdf import pisa

app = Flask(__name__)

# ---- Azure OpenAI config from environment (.env / App Settings) ----
ENDPOINT    = os.environ["AZURE_OPENAI_ENDPOINT"]
API_KEY     = os.environ["AZURE_OPENAI_API_KEY"]
API_VER     = os.environ["AZURE_OPENAI_API_VERSION"]      # e.g., 2024-08-01-preview
DEPLOYMENT  = os.environ["AZURE_OPENAI_DEPLOYMENT"]       # e.g., gpt5-mini-deploy

client = AzureOpenAI(api_key=API_KEY, azure_endpoint=ENDPOINT, api_version=API_VER)

# ---------- Helpers ----------
def slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", (s or "project")).strip("_").lower()

def wrap_html(body_html: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: DejaVu Sans, Arial, Helvetica, sans-serif; font-size: 12pt; }}
  h1,h2,h3 {{ color:#111; margin: 0.6em 0 0.2em; }}
  table {{ width:100%; border-collapse: collapse; margin: 0.6em 0; }}
  th, td {{ border: 1px solid #888; padding: 6px; vertical-align: top; }}
  .muted {{ color:#555; font-size: 10pt; }}
  code, pre {{ font-family: monospace; font-size: 10pt; }}
  ul, ol {{ margin: 0.3em 0 0.6em 1.2em; }}
  hr {{ border: none; border-top: 1px solid #aaa; margin: 1em 0; }}
</style></head><body>{body_html}</body></html>"""

def html_to_pdf_bytes(html: str) -> bytes:
    buf = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=buf)  # xhtml2pdf
    return buf.getvalue()

def build_prompt(form: dict) -> str:
    """
    Generic PBL project generator prompt that mirrors the professional structure
    of an engineering design assignment (objective/description/deliverables/
    requirements/benchmarking/milestones) but works for ANY subject.
    """
    title        = form.get("title", "")
    subject      = form.get("subject", "")
    grade        = form.get("grade", "")
    duration     = form.get("duration", "")
    group_size   = form.get("group_size", "")
    driving_q    = form.get("driving_q", "")
    standards    = form.get("standards", "")
    constraints  = form.get("constraints", "")
    public_prod  = form.get("public_product", "")
    assessment   = form.get("assessment", "")
    resources    = form.get("resources", "")

    return f"""
You are an instructional design assistant.

Write a professional, publication-quality **project-based learning (PBL) project brief**
that follows the tone and rigor of a formal university project handout:
clear Objective; precise Project Description; explicit Deliverables; formal Requirements
(what to analyze/build/evaluate, what assumptions to state); a Milestones/Timeline table;
Collaboration roles; Inquiry/Research plan; Scaffolding/UDL supports; Assessment/Rubrics;
Integrity/Safety constraints; Public Product instructions; and References.
Output **Markdown** only.

### Inputs (teacher)
- Title: {title}
- Subject / Grade: {subject} / {grade}
- Duration: {duration} weeks
- Typical Group Size: {group_size}
- Driving Question: {driving_q}
- Target Standards: {standards}
- Constraints (safety/ethics/resources/scope): {constraints}
- Public Product / Showcase: {public_prod}
- Assessment Focus (rubrics): {assessment}
- Seed Resources (optional): {resources}

### Output format (use these exact sections; keep them concise but specific)
# {title}
**Subject/Grade:** {subject} / {grade} · **Duration:** {duration} weeks · **Group size:** {group_size}

## Objective
A measurable goal tied to the driving question and standards.

## Project Description
Authentic context; what students will create, investigate, or prototype for **{subject}**.

## Driving Question
State and frame inquiry for students.

## Standards Alignment
A small table mapping outcomes → standards codes.

## Milestones & Timeline
A week-by-week table (Week, Focus, Key Tasks, Interim Deliverables).

## Collaboration & Roles
Recommended roles (e.g., Research Lead, Designer/Builder, Analyst, Communicator) and team norms.

## Inquiry & Research Plan
Guiding questions; suggested trustworthy sources; data collection or experimental design (adapt to {subject}).

## Requirements & Assumptions
Bullet list of must-haves, constraints, required methods/equations/criteria; explicit assumptions students must state.

## Scaffolding & UDL Supports
Differentiation, accessibility, language supports, checklists, exemplars.

## Assessment & Rubrics
Criteria for content mastery + 21st-century skills (creativity, collaboration, communication, critical thinking).
Provide a compact rubric table (Levels × Criteria).

## Academic Integrity, Safety, and Ethics
Clear rules tailored to {subject}; safety notes if labs/experiments are used.

## Public Product & Submission
How to package results (report/slides/prototype/demo), file naming, and showcase details: {public_prod}

## References
Short, credible references or suggested starting points (adapt to {subject}).
"""

# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/generate", methods=["POST"])
def generate():
    data = request.form.to_dict() or {}
    if not data.get("title"):
        abort(400, "Title is required")

    prompt = build_prompt(data)

    try:
        resp = client.chat.completions.create(
            model=DEPLOYMENT,                    # GPT-5 mini deployment name
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=1400           # GPT-5 family param
            # (do not pass temperature/top_p—unsupported by GPT-5 mini on Azure)
        )
        md_text = resp.choices[0].message.content or "# (no content)"
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

    # Markdown -> HTML -> PDF
    html_body = markdown(md_text, extensions=["tables"])
    html_full = wrap_html(html_body)
    pdf_bytes = html_to_pdf_bytes(html_full)

    filename = f"{slug(data.get('title'))}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )

if __name__ == "__main__":
    app.run(debug=True)



