use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::thread;
use std::time::Duration;

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

fn handle(stream: TcpStream) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let mut reader = BufReader::new(&stream);

    let mut request_line = String::new();
    if reader.read_line(&mut request_line).unwrap_or(0) == 0 {
        return;
    }

    let mut user_agent = String::new();
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line).unwrap_or(0) == 0 {
            break;
        }
        let line = line.trim_end();
        if line.is_empty() {
            break;
        }
        if let Some((k, v)) = line.split_once(':') {
            if k.eq_ignore_ascii_case("user-agent") {
                user_agent = v.trim().to_string();
            }
        }
    }

    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or("");
    let target = parts.next().unwrap_or("/");
    let (path, query) = target.split_once('?').unwrap_or((target, ""));

    let (status, body) = match (method, path) {
        ("GET", "/healthz") => ("200 OK", r#"{"status":"ok"}"#.to_string()),
        ("GET", "/") => ("200 OK", r#"{"service":"echo","runtime":"container"}"#.to_string()),
        (_, "/echo") => (
            "200 OK",
            format!(
                r#"{{"runtime":"container","method":"{}","path":"{}","query":"{}","user_agent":"{}"}}"#,
                json_escape(method),
                json_escape(path),
                json_escape(query),
                json_escape(&user_agent)
            ),
        ),
        _ => ("404 Not Found", r#"{"error":"not found"}"#.to_string()),
    };

    let response = format!(
        "HTTP/1.1 {status}\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
        body.len()
    );
    let mut out = &stream;
    let _ = out.write_all(response.as_bytes());
    let _ = out.flush();
}

fn main() {
    let addr = std::env::var("LISTEN_ADDR").unwrap_or_else(|_| "0.0.0.0:8080".to_string());
    let listener = TcpListener::bind(&addr).expect("bind failed");
    eprintln!("container-echo listening on {addr}");
    for stream in listener.incoming() {
        if let Ok(stream) = stream {
            thread::spawn(move || handle(stream));
        }
    }
}
