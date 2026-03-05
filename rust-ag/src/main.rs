use std::env;
use std::process;

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();

    if args.is_empty() {
        eprintln!("Usage: rust-ag [OPTIONS] PATTERN [PATH]");
        process::exit(2);
    }

    for arg in &args {
        match arg.as_str() {
            "--version" => {
                println!("rust-ag {VERSION}");
                process::exit(0);
            }
            "--help" | "-h" => {
                print_help();
                process::exit(0);
            }
            _ => {}
        }
    }

    // Placeholder: parse flags but do not search yet.
    // Future milestones will implement actual search behavior.
    // Exit code 1 = no match (ag convention).
    process::exit(1);
}

fn print_help() {
    println!(
        "\
rust-ag {VERSION} — Rust rewrite of The Silver Searcher

Usage: rust-ag [OPTIONS] PATTERN [PATH]

This is a placeholder binary. Search functionality will be implemented
in subsequent milestones (rust-search-core, rust-cli-parity).

Options:
  --version          Show version information
  --help, -h         Show this help message
  --nocolor          Disable color output (accepted, not yet implemented)
  --workers=N        Number of worker threads (accepted, not yet implemented)
  --parallel         Parallel search (accepted, not yet implemented)
  --noaffinity       Disable CPU affinity (accepted, not yet implemented)

Exit codes:
  0  Matches found
  1  No matches found
  2  Error"
    );
}
