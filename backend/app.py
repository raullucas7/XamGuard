from flask import Flask, request, jsonify
from components.hostfileservice import block, unblock

app = Flask(__name__)

@app.route("/")

def home():
    return "Hello Xamguard"

# GET : getting/sending info to a website/client
#   - use if you dont care about sensitivity of info
# POST : more secure GET 
#   - use if info is sensitive (form data)

@app.route("/api/block", methods=["POST"])
def apiblock():
    data = request.get_json()
    sites = data.get("sites", [])
    block(sites)
    return jsonify({"status": "success", "blocked": sites})

if __name__ == "__main__":
    app.run(debug=True)