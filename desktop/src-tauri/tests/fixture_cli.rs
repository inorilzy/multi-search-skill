use std::{
    env,
    process::{Command, Stdio},
    thread,
    time::Duration,
};

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    if let Ok(path) = env::var("FIXTURE_LAUNCH_PATH") {
        std::fs::write(path, "started").unwrap();
    }
    // Test boundary: print the child's environment as JSON (names and values),
    // so tests can prove provider credentials never cross the process boundary.
    if args.first().map(String::as_str) == Some("env-dump") {
        let mut rows: Vec<String> = env::vars()
            .map(|(name, value)| {
                format!(
                    "\"{}\":\"{}\"",
                    name.replace('\\', "\\\\").replace('"', "\\\""),
                    value.replace('\\', "\\\\").replace('"', "\\\"").replace('\n', "\\n")
                )
            })
            .collect();
        rows.sort();
        println!("{{{}}}", rows.join(","));
        return;
    }
    if args.first().map(String::as_str) == Some("--version") {
        if let Ok(root) = env::var("FIXTURE_FAIL_ACTIVE_ROOT") {
            if env::current_exe().unwrap().starts_with(std::path::Path::new(&root).join("bin")) {
                if env::var("FIXTURE_BLOCK_RESTORE").as_deref() == Ok("1") {
                    let active = std::path::Path::new(&root).join("active.json");
                    std::fs::remove_file(&active).unwrap();
                    std::fs::create_dir(&active).unwrap();
                    std::fs::write(active.join("concurrent-user-file"), "preserve").unwrap();
                }
                std::process::exit(7);
            }
        }
        match env::var("FIXTURE_VERSION").as_deref() {
            Ok("fail") => {
                eprintln!("fixture version failure");
                std::process::exit(7);
            }
            Ok("legacy") => {
                eprintln!("usage error: the following arguments are required: command");
                std::process::exit(2);
            }
            Ok("secret") => {
                // The version probe runs with the minimal environment, so provider keys never reach
                // it. Report whether one leaked, then echo the debug-only seam value so the parent's
                // redaction of child output is still exercised.
                let leaked = env::var("EXA_API_KEY").is_ok();
                eprintln!("exa_key_present={leaked}");
                eprintln!("{}", env::var("FIXTURE_SECRET").unwrap_or_default());
                std::process::exit(2);
            }
            Ok("hang") => thread::sleep(Duration::from_secs(30)),
            Ok(version) => println!("multi-search {version}"),
            Err(_) => println!("multi-search 0.4.0"),
        }
        return;
    }
    if args.get(1).map(String::as_str) == Some("--help") {
        // Real help text lists each flag; FIXTURE_HELP=stale omits --expand to simulate an
        // incompatible CLI, and FIXTURE_HELP=no-routes rejects the routes subcommand.
        let help_mode = env::var("FIXTURE_HELP");
        let stale = help_mode.as_deref() == Ok("stale");
        if help_mode.as_deref() == Ok("no-routes") && args.first().map(String::as_str) == Some("routes") {
            eprintln!("usage error: argument command: invalid choice: 'routes'");
            std::process::exit(2);
        }
        match args.first().map(String::as_str) {
            Some("search") if stale => println!("usage: multi-search search [--route ROUTE] [--format FORMAT] query"),
            Some("search") => println!("usage: multi-search search [--route ROUTE] [--expand EXPAND] [--format FORMAT] [--source NAME] [--count N] [--timeout S] query"),
            Some("fetch") => println!("usage: multi-search fetch [--full-content] [--format FORMAT] [--url URL] [--url-file PATH] [source_id]"),
            Some("read") => println!("usage: multi-search read [--keyword KEYWORD] [--offset OFFSET] [--limit N] [--format FORMAT] source_id"),
            Some("doctor") => println!("usage: multi-search doctor [--no-keys] [--format FORMAT]"),
            Some("routes") => println!("usage: multi-search routes [--format FORMAT]"),
            Some("balance") => println!("usage: multi-search balance [--provider PROVIDER] [--format FORMAT] [--refresh]"),
            _ => {}
        }
        return;
    }
    if args.first().map(String::as_str) == Some("doctor") {
        if env::var("FIXTURE_STORAGE").as_deref() == Ok("legacy") { println!("{{\"outcome\":\"success\"}}"); }
        else if env::var("FIXTURE_STORAGE").as_deref() == Ok("corrupt") { println!("{{\"config_storage\":{{\"backend\":\"keys-file\",\"schema_version\":1}},\"config_error\":\"unreadable\"}}"); std::process::exit(1); }
        else if env::var("FIXTURE_PROGRESS").as_deref() == Ok("1") { println!("{{\"config_storage\":{{\"backend\":\"keys-file\",\"schema_version\":1}},\"search_progress\":{{\"prefix\":\"@@progress \",\"schema_version\":1}}}}"); }
        else { println!("{{\"config_storage\":{{\"backend\":\"keys-file\",\"schema_version\":1}}}}"); }
        return;
    }
    if args.first().map(String::as_str) == Some("descendant") {
        if let Ok(path) = env::var("FIXTURE_CHILD_PID") {
            std::fs::write(path, std::process::id().to_string()).unwrap();
        }
        thread::sleep(Duration::from_secs(60));
        return;
    }
    if let Ok(path) = env::var("FIXTURE_ARGS_PATH") {
        let body = format!(
            "[{}]",
            args.iter()
                .map(|arg| format!("\"{}\"", arg.replace('\\', "\\\\").replace('\"', "\\\"")))
                .collect::<Vec<_>>()
                .join(",")
        );
        std::fs::write(path, body).unwrap();
    }
    if args.first().map(String::as_str) == Some("login") {
        if let Ok(path) = env::var("FIXTURE_OAUTH_PID") {
            std::fs::write(path, std::process::id().to_string()).unwrap();
        }
        let mode = env::var("FIXTURE_OAUTH").unwrap_or_else(|_| "firecrawl".into());
        let open = |url: &str, user_code: Option<&str>| match user_code {
            Some(code) => println!(
                "{{\"event\":\"open_url\",\"url\":\"{}\",\"user_code\":\"{}\"}}",
                url, code
            ),
            None => println!("{{\"event\":\"open_url\",\"url\":\"{}\"}}", url),
        };
        match mode.as_str() {
            "non-https" => {
                open("http://www.firecrawl.dev/cli-auth", None);
                thread::sleep(Duration::from_secs(60));
            }
            "non-whitelisted" => {
                open("https://evil.example/cli-auth", None);
                thread::sleep(Duration::from_secs(60));
            }
            "invalid-json" => {
                println!("not-json");
                thread::sleep(Duration::from_secs(60));
            }
            "error" => {
                open("https://www.firecrawl.dev/cli-auth?code_challenge=synthetic", None);
                println!("{{\"event\":\"waiting\"}}");
                println!("{{\"event\":\"error\",\"error_kind\":\"provider\",\"message\":\"授权被拒绝。\"}}");
                std::process::exit(1);
            }
            "hang" => {
                open("https://www.firecrawl.dev/cli-auth?code_challenge=synthetic", None);
                println!("{{\"event\":\"waiting\"}}");
                thread::sleep(Duration::from_secs(60));
            }
            "parallel" => {
                open(
                    "https://platform.parallel.ai/device?user_code=ABCD-EFGH",
                    Some("ABCD-EFGH"),
                );
                thread::sleep(Duration::from_millis(150));
                println!("{{\"event\":\"waiting\"}}");
                thread::sleep(Duration::from_millis(150));
                println!("{{\"event\":\"complete\",\"credential\":\"parallel_account\"}}");
            }
            _ => {
                open("https://www.firecrawl.dev/cli-auth?code_challenge=synthetic", None);
                println!("{{\"event\":\"waiting\"}}");
                println!("{{\"event\":\"complete\",\"credential\":\"firecrawl\"}}");
            }
        }
        return;
    }
    if args.first().map(String::as_str) == Some("accounts") {
        match env::var("FIXTURE_ACCOUNTS").as_deref() {
            Ok("hang") => thread::sleep(Duration::from_secs(60)),
            Ok("legacy") => {
                eprintln!("usage error: argument command: invalid choice: 'accounts'");
                std::process::exit(2);
            }
            Ok("failure") => {
                eprintln!("usage error: cannot read configuration");
                std::process::exit(1);
            }
            Ok("invalid-option") => {
                eprintln!("usage error: unrecognized arguments: --format");
                std::process::exit(2);
            }
            Ok("truncated") => println!("{}", "x".repeat(5 * 1024 * 1024)),
            _ => println!("{}", env::var("FIXTURE_ACCOUNTS_JSON").unwrap_or_else(|_| r#"{"accounts":{}}"#.into())),
        }
        return;
    }
    if args.first().map(String::as_str) == Some("usage") {
        match env::var("FIXTURE_USAGE").as_deref() {
            Ok("hang") => thread::sleep(Duration::from_secs(60)),
            Ok("invalid") => println!("not-json"),
            Ok("legacy") => {
                eprintln!("usage error: argument command: invalid choice: 'usage' (choose from 'search', 'balance')");
                std::process::exit(2);
            }
            Ok("failure") => {
                eprintln!("usage error: cannot read configuration");
                std::process::exit(1);
            }
            Ok("invalid-option") => {
                eprintln!("usage error: unrecognized arguments: --refresh");
                std::process::exit(2);
            }
            Ok("truncated") => println!("{}", "x".repeat(5 * 1024 * 1024)),
            _ => println!("{}", env::var("FIXTURE_USAGE_JSON").unwrap_or_else(|_|
                r#"{"schema_version":1,"retention_days":30,"providers":[]}"#.into())),
        }
        return;
    }
    if args.first().map(String::as_str) == Some("balance") {
        match env::var("FIXTURE_BALANCE").as_deref() {
            Ok("hang") => thread::sleep(Duration::from_secs(60)),
            Ok("invalid") => println!("not-json"),
            _ => println!(
                "{}",
                env::var("FIXTURE_BALANCE_JSON").unwrap_or_else(|_| r#"{"schema_version":1,"providers":[{"id":"tavily","label":"Tavily","auth_methods":[],"balance_supported":true,"balance_note":"","reports":[{"provider":"tavily","status":"ok","scope":"key","unit":"credits","remaining":123,"limit":500,"used":377,"resets_at":null,"period":null,"key_fingerprint":null,"error_kind":null,"message":"","fetched_at":"2026-11-01T00:00:00+00:00"}]}]}"#.into())
            ),
        }
        return;
    }
    let query = args.iter().position(|arg| arg == "--").and_then(|i| args.get(i+1)).or_else(|| args.get(1)).map(String::as_str).unwrap_or("");
    if query == "hang" {
        let _child = Command::new(env::current_exe().unwrap())
            .arg("descendant")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        thread::sleep(Duration::from_secs(60));
    }
    if query == "env" {
        // Report which variable names reached the child, so tests can assert the minimal environment.
        let mut names: Vec<String> = env::vars().map(|(name, _)| name).collect();
        names.sort();
        println!("{{\"outcome\":\"success\",\"results\":[],\"errors\":[],\"env\":{:?}}}", names);
        return;
    }
    if query == "progress" {
        // Two stage events, a pause the poll loop can observe, then an ordinary stderr line.
        eprintln!("@@progress {{\"event\":\"route\",\"t_ms\":1,\"active_sources\":[\"brave\"]}}");
        eprintln!("@@progress {{\"event\":\"provider_start\",\"t_ms\":2,\"source\":\"brave\",\"error\":\"{}\"}}", env::var("FIXTURE_SECRET").unwrap_or_default());
        eprintln!("@@progress not-json");
        thread::sleep(Duration::from_millis(400));
        eprintln!("@@progress {{\"event\":\"provider_done\",\"t_ms\":300,\"source\":\"brave\",\"status\":\"ok\",\"hit_count\":3}}");
        eprintln!("plain warning");
        println!("{{\"outcome\":\"success\",\"results\":[],\"errors\":[]}}");
        return;
    }
    if query == "empty" { println!("{{\"outcome\":\"empty\",\"results\":[],\"errors\":[]}}"); return; }
    if query == "failure" { eprintln!("provider unavailable"); println!("{{\"outcome\":\"failed\",\"results\":[],\"errors\":[{{\"source\":\"brave\",\"error\":\"provider unavailable\"}}]}}"); std::process::exit(1); }
    if query == "partial" {
        println!("{{\"outcome\":\"partial\",\"results\":[{{\"title\":\"Fixture article\"}}],\"errors\":[{{\"source\":\"brave\",\"error\":\"unavailable {}\"}}]}}", env::var("FIXTURE_SECRET").unwrap_or_default());
    } else {
        println!(
            "{{\"outcome\":\"success\",\"results\":[{{\"title\":\"{}\"}}],\"errors\":[]}}",
            query.replace('"', "\\\"")
        );
    }
}
