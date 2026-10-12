use std::{
    env,
    process::{Command, Stdio},
    thread,
    time::Duration,
};

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("--version") {
        match env::var("FIXTURE_VERSION").as_deref() {
            Ok("fail") => {
                eprintln!("fixture version failure");
                std::process::exit(7);
            }
            Ok("hang") => thread::sleep(Duration::from_secs(30)),
            _ => println!("multi-search 0.4.0"),
        }
        return;
    }
    if args.get(1).map(String::as_str) == Some("--help") {
        // Real help text lists each flag; FIXTURE_HELP=stale omits --expand to simulate an incompatible CLI.
        let stale = env::var("FIXTURE_HELP").as_deref() == Ok("stale");
        match args.first().map(String::as_str) {
            Some("search") if stale => println!("usage: multi-search search [--route ROUTE] [--format FORMAT] query"),
            Some("search") => println!("usage: multi-search search [--route ROUTE] [--expand EXPAND] [--format FORMAT] query"),
            Some("fetch") => println!("usage: multi-search fetch [--full-content] [--format FORMAT] [source_id]"),
            Some("read") => println!("usage: multi-search read [--keyword KEYWORD] [--offset OFFSET] [--format FORMAT] source_id"),
            _ => {}
        }
        return;
    }
    if args.first().map(String::as_str) == Some("descendant") {
        if let Ok(path) = env::var("FIXTURE_CHILD_PID") {
            std::fs::write(path, std::process::id().to_string()).unwrap();
        }
        thread::sleep(Duration::from_secs(60));
        return;
    }
    let query = args.get(1).map(String::as_str).unwrap_or("");
    if query == "hang" {
        let _child = Command::new(env::current_exe().unwrap())
            .arg("descendant")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        thread::sleep(Duration::from_secs(60));
    }
    if query == "empty" { println!("{{\"outcome\":\"empty\",\"results\":[],\"errors\":[]}}"); return; }
    if query == "failure" { eprintln!("provider unavailable"); println!("{{\"outcome\":\"failed\",\"results\":[],\"errors\":[{{\"source\":\"brave\",\"error\":\"provider unavailable\"}}]}}"); std::process::exit(1); }
    if query == "partial" {
        println!("{{\"outcome\":\"partial\",\"results\":[{{\"title\":\"Fixture article\"}}],\"errors\":[{{\"source\":\"brave\",\"error\":\"unavailable {}\"}}]}}", env::var("EXA_API_KEY").unwrap_or_default());
    } else {
        println!(
            "{{\"outcome\":\"success\",\"results\":[{{\"title\":\"{}\"}}],\"errors\":[]}}",
            query.replace('"', "\\\"")
        );
    }
}
