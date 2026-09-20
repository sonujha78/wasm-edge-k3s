use std::io::{BufRead, BufReader, Read, Write};
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
    let _ = stream.set_nodelay(true);
    let mut reader = BufReader::new(&stream);
    let mut out = &stream;

    loop {
        let mut request_line = String::new();
        if reader.read_line(&mut request_line).unwrap_or(0) == 0 {
            return;
        }

        let mut user_agent = String::new();
        let mut content_length: usize = 0;
        let mut close = false;
        loop {
            let mut line = String::new();
            if reader.read_line(&mut line).unwrap_or(0) == 0 {
                return;
            }
            let line = line.trim_end();
            if line.is_empty() {
                break;
            }
            if let Some((k, v)) = line.split_once(':') {
                let v = v.trim();
                if k.eq_ignore_ascii_case("user-agent") {
                    user_agent = v.to_string();
                } else if k.eq_ignore_ascii_case("content-length") {
                    content_length = v.parse().unwrap_or(0);
                } else if k.eq_ignore_ascii_case("connection") && v.eq_ignore_ascii_case("close") {
                    close = true;
                }
            }
        }

        // Drain (ignore) any request body so keep-alive framing stays intact.
        if content_length > 1 << 20 {
            return;
        }
        if content_length > 0 {
            let mut sink = vec![0u8; content_length];
            if reader.read_exact(&mut sink).is_err() {
                return;
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

        let conn = if close { "connection: close\r\n" } else { "" };
        let response = format!(
            "HTTP/1.1 {status}\r\ncontent-type: application/json\r\ncontent-length: {}\r\n{conn}\r\n{body}",
            body.len()
        );
        if out.write_all(response.as_bytes()).is_err() {
            return;
        }
        if close {
            return;
        }
    }
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
