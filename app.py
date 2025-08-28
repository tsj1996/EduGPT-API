from flask import Flask, render_template, jsonify
from openai import AzureOpenAI
import os

app = Flask(__name__)

# ---- Azure OpenAI config from environment ----
ENDPOINT    = os.environ["AZURE_OPENAI_ENDPOINT"]
API_KEY     = os.environ["AZURE_OPENAI_API_KEY"]
API_VER     = os.environ["AZURE_OPENAI_API_VERSION"]
DEPLOYMENT  = os.environ["AZURE_OPENAI_DEPLOYMENT"]

client = AzureOpenAI(
    api_key=API_KEY,
    azure_endpoint=ENDPOINT,
    api_version=API_VER
)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask():
    messages = [{"role": "user", "content": "Tell me who you are"}]

    resp = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=messages,
        max_completion_tokens=200
    )

    answer = resp.choices[0].message.content
    return jsonify({"answer": answer})   # ✅ Proper JSON response

if __name__ == "__main__":
    app.run(debug=True)




