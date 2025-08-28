from flask import Flask, render_template, request, jsonify
from openai import AzureOpenAI
import os

app = Flask(__name__)

# Load config from environment variables (set these in Azure App Service → Configuration)
ENDPOINT   = os.environ["AZURE_OPENAI_ENDPOINT"]
API_KEY    = os.environ["AZURE_OPENAI_API_KEY"]
API_VER    = os.environ["AZURE_OPENAI_API_VERSION"]
DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]

# Create Azure OpenAI client
client = AzureOpenAI(
    api_key=API_KEY,
    api_version=API_VER,
    azure_endpoint=ENDPOINT
)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask():
    try:
        resp = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[{"role": "user", "content": "Tell me who you are"}],
            max_completion_tokens=200
        )
        answer = resp.choices[0].message.content
        return jsonify({"ok": True, "answer": answer})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
