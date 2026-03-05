mod ignore;
mod opts;
mod output;
mod search;
mod walk;

use std::env;
use std::io::Read;
use std::process;

use regex::Regex;

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();

    if args.is_empty() {
        // ag: no-args prints usage to stdout and exits 1.
        print_help();
        process::exit(1);
    }

    let opts = match opts::Opts::parse(&args) {
        Ok(o) => o,
        Err(e) => {
            // ag: invalid-option errors exit 1 (not 2) and print the error
            // to stderr plus usage/help to stdout. This is a distinct error
            // class from regex errors (which exit 2).
            eprintln!("rust-ag: {e}");
            print_help();
            process::exit(1);
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

    // -g mode: filename pattern search (no content search).
    if opts.filename_pattern.is_some() {
        let exit_code = run_filename_pattern_mode(&opts);
        process::exit(exit_code);
    }

    // Need a pattern to search.
    if opts.pattern.is_none() {
        // ag: prints "ERR: What do you want to search for?" to stderr, exits 1.
        eprintln!("ERR: What do you want to search for?");
        process::exit(1);
    }

    // Detect stdin pipe mode: if stdin is a pipe/FIFO, ag initially sets
    // search_stream = 1, which disables line numbers (unless --numbers was
    // explicit). If explicit paths are given later, search_stream is reset
    // to 0 but the line-number suppression persists (an ag quirk we match).
    let stdin_is_pipe = is_stdin_pipe();
    let search_stream = stdin_is_pipe && !opts.paths_were_explicit;

    // Build the regex.
    let re = match search::build_regex(&opts) {
        Ok(r) => r,
        Err(e) => {
            // ag: invalid regex prints diagnostic to stderr and exits 2.
            // Format: "ERR: Bad regex! ..." followed by hint about -Q.
            eprintln!("ERR: {e}");
            eprintln!("If you meant to search for a literal string, run ag with -Q");
            process::exit(2);
        }
    };

    // Resolve color mode.
    // ag defaults: color when stdout is a TTY.
    // --color forces on; --nocolor forces off.
    // Since we're a CLI tool and tests pipe stdout, default to no color
    // unless --color is explicitly set.
    let use_color = resolve_color(&opts);

    if search_stream {
        // Stream mode: read all of stdin and search it.
        // Use byte-tolerant reading to avoid panicking on non-UTF8 input
        // (baseline ag handles arbitrary byte streams without crashing).
        let mut raw = Vec::new();
        std::io::stdin()
            .read_to_end(&mut raw)
            .expect("failed to read stdin");
        let input = String::from_utf8_lossy(&raw).into_owned();

        // Resolve line number display for stream mode:
        // In stream mode, ag defaults to no line numbers unless --numbers
        // was explicitly requested (value 2 in ag's model).
        let show_line_numbers = opts.numbers && !opts.no_numbers;

        let found_any = if opts.count {
            search_stream_count(&input, &re, &opts)
        } else {
            search_stream_normal(&input, &re, &opts, show_line_numbers, use_color)
        };

        if found_any {
            process::exit(0);
        } else {
            process::exit(1);
        }
    }

    // Validate -G / --file-search-regex up front. Baseline ag treats an
    // invalid file-search regex identically to an invalid content regex:
    // stderr diagnostic + exit 2.
    if let Some(ref file_re_str) = opts.file_search_regex {
        if let Err(e) = Regex::new(file_re_str) {
            eprintln!("ERR: Bad regex! {e}");
            eprintln!("If you meant to search for a literal string, run ag with -Q");
            process::exit(2);
        }
    }

    // File mode: walk to collect files, applying -G filter.
    let mut files = walk::walk_paths(&opts);

    // Apply -G / --file-search-regex filter.
    if let Some(ref file_re_str) = opts.file_search_regex {
        // Safety: regex was already validated above.
        let file_re = Regex::new(file_re_str).unwrap();
        files.retain(|p| {
            let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
            file_re.is_match(name)
        });
    }

    let multi_file = files.len() > 1 || opts.paths.iter().any(|p| std::path::Path::new(p).is_dir());

    let show_filename = if opts.no_filename {
        false
    } else {
        // Default and --filename: multi-file = yes, single = no.
        multi_file
    };

    let show_line_numbers = opts.numbers || !(opts.no_numbers || opts.no_filename || stdin_is_pipe);

    let has_context = opts.before_context > 0 || opts.after_context > 0;

    let mut found_any = false;
    let mut first_file_output = true;

    for file_path in &files {
        let result = search::search_file(file_path, &re, &opts);

        let display_path = display_path_for(file_path);

        // Handle binary files.
        if result.is_binary && result.binary_has_match {
            found_any = true;
            println!("Binary file {display_path} matches.");
            continue;
        }
        if result.is_binary && result.matches.is_empty() && !result.binary_has_match {
            continue;
        }

        if !result.matches.is_empty() {
            found_any = true;
        }

        // Emit max-count truncation diagnostic to stderr.
        if result.max_count_hit {
            let raw_path = file_path.to_string_lossy();
            eprintln!("ERR: Too many matches in {raw_path}. Skipping the rest of this file.");
        }

        if opts.count {
            if !result.matches.is_empty() || opts.invert_match {
                let line = output::format_count_line(
                    if show_filename {
                        Some(&display_path)
                    } else {
                        None
                    },
                    result.match_count,
                    use_color,
                );
                println!("{line}");
            }
        } else if opts.files_with_matches {
            if !result.matches.is_empty() {
                println!("{display_path}");
            }
        } else if has_context {
            // Context mode: read file content, emit context lines.
            if !result.matches.is_empty() {
                let cfg = ContextConfig {
                    file_path,
                    result: &result,
                    display_path: &display_path,
                    re: &re,
                    opts: &opts,
                    show_filename,
                    show_line_numbers,
                    use_color,
                };
                emit_context_output(&cfg);
            }
        } else {
            // Normal mode: print matching lines.
            if !show_filename && multi_file && !result.matches.is_empty() {
                if !first_file_output {
                    println!();
                }
                first_file_output = false;
            }

            for m in &result.matches {
                let line = output::format_match_line(
                    if show_filename {
                        Some(&display_path)
                    } else {
                        None
                    },
                    m.line_number,
                    &m.line,
                    &re,
                    use_color,
                    show_line_numbers,
                );
                println!("{line}");
            }
        }
    }

    if found_any {
        process::exit(0);
    } else {
        process::exit(1);
    }
}

/// Resolve whether color output should be enabled.
///
/// ag defaults: color when stdout is a TTY.
/// --color forces on; --nocolor forces off.
/// The last flag wins when both are specified.
fn resolve_color(opts: &opts::Opts) -> bool {
    if opts.no_color {
        return false;
    }
    if opts.color {
        return true;
    }
    // Default: color if stdout is a TTY.
    is_stdout_tty()
}

/// Check if stdout is a TTY.
fn is_stdout_tty() -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::io::AsRawFd;
        let fd = std::io::stdout().as_raw_fd();
        unsafe { libc::isatty(fd) != 0 }
    }
    #[cfg(not(unix))]
    {
        false
    }
}

/// Run -g / --filename-pattern mode: list files matching the pattern.
///
/// In ag, `-g PATTERN` uses PATTERN as a filename filter regex.
/// The first positional argument becomes the filename pattern (not a
/// content search pattern). Exit 0 if any files found, 1 if none.
fn run_filename_pattern_mode(opts: &opts::Opts) -> i32 {
    let pattern_str = opts.filename_pattern.as_ref().unwrap();
    let file_re = match Regex::new(pattern_str) {
        Ok(r) => r,
        Err(e) => {
            eprintln!("rust-ag: Invalid filename pattern: {e}");
            return 2;
        }
    };

    let files = walk::walk_paths(opts);

    let mut found = false;
    for f in &files {
        // Match the regex against the raw traversal path (including leading
        // "./" when searching from "."), mirroring baseline ag which runs
        // pcre_exec against `dir_full_path` before normalize_path().
        let raw_path = f.to_string_lossy();
        if file_re.is_match(&raw_path) {
            // Display the normalized path (strip leading "./" etc.).
            let display = display_path_for(f);
            println!("{display}");
            found = true;
        }
    }

    if found {
        0
    } else {
        1
    }
}

/// Configuration for context output rendering.
struct ContextConfig<'a> {
    file_path: &'a std::path::Path,
    result: &'a search::FileSearchResult,
    display_path: &'a str,
    re: &'a Regex,
    opts: &'a opts::Opts,
    show_filename: bool,
    show_line_numbers: bool,
    use_color: bool,
}

/// Emit context-mode output for a single file.
///
/// Reads the file's lines, determines which are match lines vs context lines,
/// and prints them with the appropriate separators (`:` for matches, `-` for
/// context, `--` between non-contiguous groups).
fn emit_context_output(cfg: &ContextConfig<'_>) {
    // Read file content to get all lines using byte-tolerant processing.
    // Non-UTF8 files are handled via lossy conversion (matching how
    // search.rs already processes non-UTF8 files for normal output).
    let raw = match std::fs::read(cfg.file_path) {
        Ok(data) => data,
        Err(_) => return,
    };
    let content = String::from_utf8_lossy(&raw).into_owned();
    // ag treats a trailing newline as creating an additional empty line.
    // Rust's `lines()` omits the trailing empty string, so we manually
    // split to match ag's line counting.
    let mut all_lines: Vec<&str> = content.split('\n').collect();
    // If the file doesn't end with \n, split gives the right result.
    // If it ends with \n, split gives an extra empty string at the end,
    // which is what ag includes as a context line. However, if the last
    // "line" is truly empty and would be the phantom line, we keep it
    // (ag shows it as an empty context line).
    // But we should NOT keep it if it's the phantom empty string from
    // a file that just ends with \n and the search engine didn't produce
    // a line for it. Actually, ag does show it, so keep it.
    // Remove trailing phantom ONLY if the file is empty.
    if all_lines.last() == Some(&"") && all_lines.len() > 1 && content.ends_with('\n') {
        // Keep the trailing empty line — ag shows it as context.
    } else if all_lines.last() == Some(&"") && content.is_empty() {
        all_lines.pop();
    }

    // Build a set of matching line numbers.
    let match_line_set: std::collections::HashSet<usize> =
        cfg.result.matches.iter().map(|m| m.line_number).collect();

    let before = cfg.opts.before_context;
    let after = cfg.opts.after_context;

    // Build ranges of lines to display.
    let mut ranges: Vec<(usize, usize)> = Vec::new();
    for m in &cfg.result.matches {
        let start = if m.line_number > before {
            m.line_number - before
        } else {
            1
        };
        let end = (m.line_number + after).min(all_lines.len());
        ranges.push((start, end));
    }

    // Merge overlapping ranges.
    let merged = merge_ranges(&ranges);

    let path_prefix = if cfg.show_filename {
        Some(cfg.display_path)
    } else {
        None
    };

    let mut first_group = true;
    for (start, end) in &merged {
        if !first_group {
            println!("--");
        }
        first_group = false;

        for line_num in *start..=*end {
            if line_num > all_lines.len() || line_num == 0 {
                continue;
            }
            let line_text = all_lines[line_num - 1];

            if match_line_set.contains(&line_num) {
                let formatted = output::format_match_line(
                    path_prefix,
                    line_num,
                    line_text,
                    cfg.re,
                    cfg.use_color,
                    cfg.show_line_numbers,
                );
                println!("{formatted}");
            } else {
                let formatted = output::format_context_line(
                    path_prefix,
                    line_num,
                    line_text,
                    cfg.use_color,
                    cfg.show_line_numbers,
                );
                println!("{formatted}");
            }
        }
    }
}

/// Merge overlapping or adjacent ranges into non-overlapping ranges.
fn merge_ranges(ranges: &[(usize, usize)]) -> Vec<(usize, usize)> {
    if ranges.is_empty() {
        return Vec::new();
    }

    let mut sorted = ranges.to_vec();
    sorted.sort_by_key(|&(s, _)| s);

    let mut merged = vec![sorted[0]];
    for &(start, end) in &sorted[1..] {
        let last = merged.last_mut().unwrap();
        if start <= last.1 + 1 {
            // Overlapping or adjacent — extend.
            last.1 = last.1.max(end);
        } else {
            merged.push((start, end));
        }
    }

    merged
}

/// Detect whether stdin is a pipe/FIFO (not a TTY).
fn is_stdin_pipe() -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::io::AsRawFd;
        let fd = std::io::stdin().as_raw_fd();
        unsafe {
            let mut stat: libc::stat = std::mem::zeroed();
            if libc::fstat(fd, &mut stat) == 0 {
                let mode = stat.st_mode;
                return (mode & libc::S_IFMT) == libc::S_IFIFO
                    || (mode & libc::S_IFMT) == libc::S_IFREG;
            }
        }
        false
    }
    #[cfg(not(unix))]
    {
        false
    }
}

/// Stream count mode: output per-line match counts for matching lines.
///
/// In baseline ag, stream mode with `-c` calls `search_buf` per line,
/// which applies invert-match after finding matches. So:
/// - Without `-v`: print the match count for each line that has matches.
/// - With `-v`: for each non-matching line, print `1` (the inverted
///   "match" count — one inverted region per non-matching line).
fn search_stream_count(input: &str, re: &regex::Regex, opts: &opts::Opts) -> bool {
    let mut found = false;
    for line in input.lines() {
        let count = search::count_line_matches(line, re);
        if opts.invert_match {
            // Inverted: non-matching lines produce 1 inverted match each.
            if count == 0 {
                found = true;
                println!("1");
            }
        } else if count > 0 {
            found = true;
            println!("{count}");
        }
    }
    found
}

/// Stream normal mode: output matching lines.
fn search_stream_normal(
    input: &str,
    re: &regex::Regex,
    opts: &opts::Opts,
    show_line_numbers: bool,
    use_color: bool,
) -> bool {
    let (matches, _match_count) = search::search_text_content(input, re, opts);
    if matches.is_empty() {
        return false;
    }
    for m in &matches {
        let line = output::format_match_line(
            None,
            m.line_number,
            &m.line,
            re,
            use_color,
            show_line_numbers,
        );
        println!("{line}");
    }
    true
}

/// Compute the display path for output.
///
/// Mirrors baseline ag's `normalize_path()` in `print.c`:
///   - Strip leading "./" when path length >= 3
///   - Collapse leading "//" to "/"
fn display_path_for(path: &std::path::Path) -> String {
    let s = path.to_string_lossy();
    if s.len() >= 3 {
        if let Some(rest) = s.strip_prefix("./") {
            return rest.to_string();
        }
        if let Some(rest) = s.strip_prefix("//") {
            return format!("/{rest}");
        }
    }
    s.to_string()
}

fn print_help() {
    println!(
        "\
Usage: rust-ag [FILE-TYPE] [OPTIONS] PATTERN [PATH]

  Recursively search for PATTERN in PATH.
  Like grep or ack, but faster.

Output Options:
  -A --after [LINES]      Print lines after match (Default: 2)
  -B --before [LINES]     Print lines before match (Default: 2)
  -c --count              Only print the number of matches in each file.
                          (This often differs from the number of matching lines)
     --[no]color          Print color codes in results (Enabled by default)
  -C --context [LINES]    Print lines before and after matches (Default: 2)
     --[no]filename       Print file names (Enabled unless searching a single file)
  -g --filename-pattern PATTERN
                          Print filenames matching PATTERN
  -l --files-with-matches Only print filenames that contain matches
                          (don't print the matching lines)
     --[no]numbers        Print line numbers. Default is to omit line numbers
                          when searching streams
  -o --only-matching      Prints only the matching part of the lines

Search Options:
  -a --all-types          Search all files (doesn't include hidden files
                          or patterns from ignore files)
  -D --debug              Ridiculous debugging (probably not useful)
     --depth NUM          Search up to NUM directories deep (Default: 25)
  -f --follow             Follow symlinks
  -F --fixed-strings      Alias for --literal for compatibility with grep
  -G --file-search-regex PATTERN
                          Limit search to filenames matching PATTERN
     --hidden             Search hidden files (obeys .*ignore files)
  -i --ignore-case        Match case insensitively
     --ignore PATTERN     Ignore files/directories matching PATTERN
                          (literal file/directory names also allowed)
  -m --max-count NUM      Skip the rest of a file after NUM matches
                          (Default: 10,000)
     --one-device         Don't follow links to other devices.
  -p --path-to-ignore STRING
                          Use .ignore file at STRING
  -Q --literal            Don't parse PATTERN as a regular expression
  -r --recurse            Recurse into directories (Default: on)
  -s --case-sensitive     Match case sensitively
  -S --smart-case         Match case insensitively unless PATTERN contains
                          uppercase characters (Enabled by default)
     --search-binary      Search binary files for matches
  -t --all-text           Search all text files (doesn't include hidden files)
  -u --unrestricted       Search all files (ignore .ignore, .gitignore, etc.;
                          searches binary and hidden files as well)
  -U --skip-vcs-ignores   Ignore VCS ignore files
                          (.gitignore, .hgignore; still obey .ignore)
  -v --invert-match       Invert match
  -w --word-regexp        Only match whole words
     --workers NUM        Use NUM worker threads
     --parallel           Parse input with parallel threads
     --noaffinity         Don't set processor affinity
  -n --norecurse          Don't recurse into directories

Exit codes:
  0  Matches found
  1  No matches found
  2  Error"
    );
}
