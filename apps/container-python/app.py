from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.get("/")
def index():
    return jsonify(service="echo", runtime="container-python")


@app.route("/echo", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def echo():
    return jsonify(
        runtime="container-python",
        method=request.method,
        path=request.path,
        query=request.query_string.decode(),
        user_agent=request.headers.get("User-Agent", ""),
    )
