from flask import Flask, request, jsonify
from flask_cors import CORS
from components.hostfileservice import block, unblock

app = Flask(__name__)
CORS(app)
blocked_sites = []
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


@app.route("/api/blocking", methods=["GET"])
def getblockedsites():
    return jsonify({"blocked_sites": blocked_sites})

# unblock the site
@app.route("/api/unblock", methods=["POST"])
def apiunblock():
    data = request.get_json()
    sites = data.get("sites", [])
    unblock(sites)
    
    for site in sites:
        if site in blocked_sites:
            blocked_sites.remove(site)
    
    return jsonify({"status": "success", "unblocked": sites})


if __name__ == "__main__":
    app.run(debug=True)