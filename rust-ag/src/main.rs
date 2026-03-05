mod ignore;
mod opts;
mod search;
mod walk;

use std::env;
use std::process;

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();

    if args.is_empty() {
        eprintln!("Usage: rust-ag [OPTIONS] PATTERN [PATH]");
        process::exit(2);
    }

    let opts = match opts::Opts::parse(&args) {
        Ok(o) => o,
        Err(e) => {
            eprintln!("rust-ag: {e}");
            process::exit(2);
        }
    };

    if opts.version {
        println!("rust-ag {VERSION}");
        process::exit(0);
    }

    if opts.help {
        print_help();
        process::exit(0);
    }

    // Need a pattern to search.
    if opts.pattern.is_none() {
        eprintln!("Usage: rust-ag [OPTIONS] PATTERN [PATH]");
        process::exit(2);
    }

    // Build the regex.
    let re = match search::build_regex(&opts) {
        Ok(r) => r,
        Err(e) => {
            eprintln!("rust-ag: {e}");
            process::exit(2);
        }
    };

    // Walk to collect files.
    let files = walk::walk_paths(&opts);

    let multi_file = files.len() > 1 || opts.paths.iter().any(|p| std::path::Path::new(p).is_dir());

    // ag preserves the user-specified path prefix in output.
    // When the user passes "." it strips it; when they pass a specific
    // directory like "tests/foo", the output includes "tests/foo/...".
    // We only strip the prefix when the search path is exactly ".".
    let strip_dot_prefix = opts.paths.len() == 1 && opts.paths[0] == ".";

    let mut found_any = false;

    for file_path in &files {
        let result = search::search_file(file_path, &re, &opts);

        let display_path = display_path_for(file_path, strip_dot_prefix);

        // Handle binary files.
        // When -c or -l is set with --search-binary/-u, search_file returns
        // real matches for binary files (no binary_has_match flag). Fall
        // through to normal output handling.
        // Without -c/-l, ag prints "Binary file X matches." to stdout.
        if result.is_binary && result.binary_has_match {
            found_any = true;
            println!("Binary file {display_path} matches.");
            continue;
        }
        if result.is_binary && result.matches.is_empty() && !result.binary_has_match {
            // Binary file with no matches at all — skip silently.
            continue;
        }

        if !result.matches.is_empty() {
            found_any = true;
        }

        // Emit max-count truncation diagnostic to stderr, matching ag behavior.
        // ag uses the raw file path (preserving "./" prefix) in stderr
        // diagnostics, unlike stdout which strips the "./" prefix.
        if result.max_count_hit {
            let raw_path = file_path.to_string_lossy();
            eprintln!("ERR: Too many matches in {raw_path}. Skipping the rest of this file.");
        }

        if opts.count {
            // --count mode: print count per file.
            if !result.matches.is_empty() || opts.invert_match {
                if multi_file {
                    println!("{}:{}", display_path, result.matches.len());
                } else {
                    println!("{}", result.matches.len());
                }
            }
        } else if opts.files_with_matches {
            // -l mode: print filename only.
            if !result.matches.is_empty() {
                println!("{display_path}");
            }
        } else {
            // Normal mode: print matching lines.
            for m in &result.matches {
                if multi_file {
                    println!("{}:{}:{}", display_path, m.line_number, m.line);
                } else {
                    println!("{}:{}", m.line_number, m.line);
                }
            }
        }
    }

    // Exit code: 0 if matches found, 1 if not, 2 if error.
    if found_any {
        process::exit(0);
    } else {
        process::exit(1);
    }
}

/// Compute the display path for output.
///
/// When the search path is ".", strip the "./" prefix to match `ag` behavior.
/// Otherwise, preserve the full path as given.
fn display_path_for(path: &std::path::Path, strip_dot: bool) -> String {
    let s = path.to_string_lossy();
    if strip_dot {
        let stripped = s.strip_prefix("./").unwrap_or(&s);
        stripped.to_string()
    } else {
        s.to_string()
    }
}

fn print_help() {
    println!(
        "\
rust-ag {VERSION} — Rust rewrite of The Silver Searcher

Usage: rust-ag [OPTIONS] PATTERN [PATH]

Output Options:
  -A --after [LINES]      Print lines after match (Default: 2)
  -B --before [LINES]     Print lines before match (Default: 2)
  -c --count              Only print the number of matches in each file
  -C --context [LINES]    Print lines before and after matches (Default: 2)
     --[no]color          Print color codes in results
  -l --files-with-matches Only print filenames that contain matches
     --[no]filename       Print file names
     --[no]numbers        Print line numbers

Search Options:
     --depth NUM          Search up to NUM directories deep (Default: 25)
  -f --follow             Follow symlinks
  -F --fixed-strings      Alias for --literal
     --hidden             Search hidden files (obeys .*ignore files)
  -i --ignore-case        Match case insensitively
     --ignore PATTERN     Ignore files/directories matching PATTERN
  -m --max-count NUM      Skip the rest of a file after NUM matches
     --one-device         Don't follow links to other devices
  -n --norecurse          Don't recurse into directories
  -Q --literal            Don't parse PATTERN as a regular expression
  -r --recurse            Recurse into directories (default)
  -s --case-sensitive     Match case sensitively
  -S --smart-case         Match case insensitively unless PATTERN has uppercase
     --search-binary      Search binary files for matches
  -U --skip-vcs-ignores   Ignore VCS ignore files (.gitignore, .hgignore)
  -u --unrestricted       Search all files (ignore .ignore, .gitignore, etc.)
  -v --invert-match       Invert match
  -w --word-regexp        Only match whole words
     --nocolor            Disable color output
     --workers=N          Number of worker threads
     --parallel           Parallel search
     --noaffinity         Disable CPU affinity

Exit codes:
  0  Matches found
  1  No matches found
  2  Error"
    );
}
