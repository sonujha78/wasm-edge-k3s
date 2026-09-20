use spin_sdk::http::{IntoResponse, Request, Response};
use spin_sdk::http_service;

// Same builder chain for every reply so all match arms have one type.
macro_rules! reply {
    ($status:literal, $body:expr) => {
        Response::builder()
            .status($status)
            .header("content-type", "application/json")
            .body($body)
    };
}

fn json_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

#[http_service]
async fn handle_wasm_echo(req: Request) -> anyhow::Result<impl IntoResponse> {
    let method = req.method().as_str().to_owned();
    let path = req.uri().path().to_owned();
    let query = req.uri().query().unwrap_or("").to_owned();
    let user_agent = req
        .headers()
        .get("user-agent")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_owned();

    let resp = match (method.as_str(), path.as_str()) {
        ("GET", "/healthz") => reply!(200, r#"{"status":"ok"}"#.to_string()),
        ("GET", "/") => reply!(200, r#"{"service":"echo","runtime":"wasm"}"#.to_string()),
        (_, "/echo") => reply!(
            200,
            format!(
                r#"{{"runtime":"wasm","method":"{}","path":"{}","query":"{}","user_agent":"{}"}}"#,
                json_escape(&method),
                json_escape(&path),
                json_escape(&query),
                json_escape(&user_agent)
            )
        ),
        _ => reply!(404, r#"{"error":"not found"}"#.to_string()),
    };
    Ok(resp)
}
