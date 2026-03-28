//! Command-line option parsing for rust-ag.
//!
//! Implements a hand-rolled parser that mirrors `ag`'s flag semantics.
//! This avoids pulling in a heavy CLI framework and gives us precise control
//! over flag precedence and interaction rules.

/// Tracks which case flag was set last for "last wins" precedence.
///
/// In `ag`, conflicting case flags are resolved by the last one specified
/// on the command line. For example, `-i -s` is case-sensitive (last wins),
/// while `-s -i` is case-insensitive (last wins).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaseMode {
    /// Smart-case (default): insensitive if pattern is all lowercase.
    Smart,
    /// Explicitly case-insensitive (`-i`).
    Insensitive,
    /// Explicitly case-sensitive (`-s`).
    Sensitive,
}

/// Tracks which recursion flag was set last for "last wins" precedence.
///
/// In `ag`, conflicting recursion flags are resolved by the last one specified
/// on the command line. For example, `-n -r` recurses (last wins),
/// while `-r -n` does not recurse (last wins).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecurseMode {
    /// Recurse into directories (default).
    Recurse,
    /// Do not recurse (`-n` / `--norecurse`).
    NoRecurse,
}

/// Tracks which multiline flag was set last for "last wins" precedence.
///
/// In `ag`, conflicting multiline flags are resolved by the last one specified
/// on the command line. For example, `--nomultiline --multiline` enables
/// multiline (last wins), while `--multiline --nomultiline` disables it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MultilineMode {
    /// Multiline matching enabled (default).
    Enabled,
    /// Multiline matching disabled (`--nomultiline`).
    Disabled,
}

/// Parsed options for a single invocation.
#[derive(Debug, Clone)]
pub struct Opts {
    /// The search pattern (first non-flag argument).
    pub pattern: Option<String>,

    /// Paths to search (remaining non-flag arguments; default to ".").
    pub paths: Vec<String>,

    /// Case-insensitive search (`-i`).
    pub case_insensitive: bool,

    /// Case-sensitive search (`-s`).
    pub case_sensitive: bool,

    /// Smart-case: case-insensitive unless pattern has uppercase (default).
    pub smart_case: bool,

    /// The resolved case mode after applying "last wins" flag precedence.
    /// This is the authoritative field for determining case behavior.
    pub case_mode: CaseMode,

    /// Print only count of matches per file (`-c` / `--count`).
    pub count: bool,

    /// Print only filenames with matches (`-l`).
    pub files_with_matches: bool,

    /// Invert match (`-v`).
    pub invert_match: bool,

    /// Search hidden files (`--hidden`).
    pub hidden: bool,

    /// Skip VCS ignores (`-U` / `--skip-vcs-ignores`).
    pub skip_vcs_ignores: bool,

    /// Unrestricted search (`-u`): ignore all ignore files, search hidden and binary.
    pub unrestricted: bool,

    /// Follow symlinks (`-f` / `--follow`).
    pub follow_symlinks: bool,

    /// Non-recursive: only search files in the specified directory (`-n` / `--norecurse`).
    pub no_recurse: bool,

    /// Recurse into directories (`-r` / `--recurse`). Default true.
    pub recurse: bool,

    /// The resolved recurse mode after applying "last wins" flag precedence.
    /// This is the authoritative field for determining recursion behavior.
    pub recurse_mode: RecurseMode,

    /// Maximum directory depth (`--depth NUM`). Default 25.
    pub max_depth: usize,

    /// Disable colour output (`--nocolor`).
    pub no_color: bool,

    /// Enable colour output (`--color`).
    pub color: bool,

    /// Number of worker threads (`--workers=N`). Accepted but currently unused.
    pub workers: Option<usize>,

    /// Parallel search (`--parallel`). Accepted but currently unused.
    pub parallel: bool,

    /// No CPU affinity (`--noaffinity`). Accepted but currently unused.
    pub no_affinity: bool,

    /// Literal / fixed-string mode (`-Q` / `--literal` / `-F`).
    pub literal: bool,

    /// Whole-word matching (`-w` / `--word-regexp`).
    pub word_regexp: bool,

    /// Search binary files (`--search-binary`).
    pub search_binary: bool,

    /// One-device restriction (`--one-device`).
    pub one_device: bool,

    /// Max matches per file (`-m` / `--max-count`). Default 10000.
    pub max_count: usize,

    /// Lines of context after match (`-A`).
    pub after_context: usize,

    /// Lines of context before match (`-B`).
    pub before_context: usize,

    /// Additional ignore patterns from `--ignore`.
    pub ignore_patterns: Vec<String>,

    /// File search regex (`-G` / `--file-search-regex`).
    pub file_search_regex: Option<String>,

    /// Filename pattern (`-g` / `--filename-pattern`).
    pub filename_pattern: Option<String>,

    /// All types (`-a` / `--all-types`).
    pub all_types: bool,

    /// All text (`-t` / `--all-text`).
    pub all_text: bool,

    /// Print version.
    pub version: bool,

    /// Print help.
    pub help: bool,

    /// Search all files ignoring ignore files (`-u`).
    #[allow(dead_code)]
    pub search_all_files: bool,

    /// Multiline matching (default on in ag).
    pub multiline: bool,

    /// No multiline.
    pub no_multiline: bool,

    /// The resolved multiline mode after applying "last wins" flag precedence.
    /// This is the authoritative field for determining multiline behavior.
    pub multiline_mode: MultilineMode,

    /// Numbers (line numbers).
    pub numbers: bool,

    /// No numbers.
    pub no_numbers: bool,

    /// No filename.
    pub no_filename: bool,

    /// Print filenames.
    pub filename: bool,

    /// Heading mode.
    pub heading: bool,

    /// No heading mode.
    pub no_heading: bool,

    /// Break between files.
    pub file_break: bool,

    /// No break between files.
    pub no_break: bool,

    /// Whether explicit paths were provided on the command line.
    /// When false and stdin is a pipe, the tool reads from stdin instead of
    /// defaulting to the current directory.
    pub paths_were_explicit: bool,
}

impl Default for Opts {
    fn default() -> Self {
        Self {
            pattern: None,
            paths: Vec::new(),
            case_insensitive: false,
            case_sensitive: false,
            smart_case: true,
            case_mode: CaseMode::Smart,
            count: false,
            files_with_matches: false,
            invert_match: false,
            hidden: false,
            skip_vcs_ignores: false,
            unrestricted: false,
            follow_symlinks: false,
            no_recurse: false,
            recurse: true,
            recurse_mode: RecurseMode::Recurse,
            max_depth: 25,
            no_color: false,
            color: false,
            workers: None,
            parallel: false,
            no_affinity: false,
            literal: false,
            word_regexp: false,
            search_binary: false,
            one_device: false,
            max_count: 10_000,
            after_context: 0,
            before_context: 0,
            ignore_patterns: Vec::new(),
            file_search_regex: None,
            filename_pattern: None,
            all_types: false,
            all_text: false,
            version: false,
            help: false,
            search_all_files: false,
            multiline: true,
            no_multiline: false,
            multiline_mode: MultilineMode::Enabled,
            numbers: false,
            no_numbers: false,
            no_filename: false,
            filename: false,
            heading: false,
            no_heading: false,
            file_break: false,
            no_break: false,
            paths_were_explicit: false,
        }
    }
}

impl Opts {
    /// Default max-count cap (matches ag's internal limit for per-file
    /// match scanning when no `--max-count` / `-m` flag is given).
    #[allow(dead_code)]
    const DEFAULT_MAX_COUNT: usize = 10_000;

    /// Parse command-line arguments into options.
    ///
    /// Returns `Err(msg)` if an unrecognised flag is encountered or a required
    /// value is missing.
    pub fn parse<I, S>(args: I) -> Result<Self, String>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let mut opts = Opts::default();
        let mut positional: Vec<String> = Vec::new();
        let mut iter = args.into_iter().peekable();

        while let Some(arg) = iter.next() {
            let a = arg.as_ref();

            // Stop option parsing on "--".
            if a == "--" {
                for rest in iter.by_ref() {
                    positional.push(rest.as_ref().to_string());
                }
                break;
            }

            // Handle --key=value style.
            if let Some(rest) = a.strip_prefix("--") {
                if let Some((key, val)) = rest.split_once('=') {
                    match key {
                        "depth" => {
                            opts.max_depth = val
                                .parse()
                                .map_err(|_| format!("Invalid --depth value: {val}"))?;
                        }
                        "workers" => {
                            opts.workers = Some(
                                val.parse()
                                    .map_err(|_| format!("Invalid --workers value: {val}"))?,
                            );
                        }
                        "max-count" => {
                            opts.max_count = val
                                .parse()
                                .map_err(|_| format!("Invalid --max-count value: {val}"))?;
                        }
                        "after" => {
                            opts.after_context = val
                                .parse()
                                .map_err(|_| format!("Invalid --after value: {val}"))?;
                        }
                        "before" => {
                            opts.before_context = val
                                .parse()
                                .map_err(|_| format!("Invalid --before value: {val}"))?;
                        }
                        "context" => {
                            let n: usize = val
                                .parse()
                                .map_err(|_| format!("Invalid --context value: {val}"))?;
                            opts.before_context = n;
                            opts.after_context = n;
                        }
                        "ignore" | "ignore-dir" => {
                            opts.ignore_patterns.push(val.to_string());
                        }
                        "file-search-regex" => {
                            opts.file_search_regex = Some(val.to_string());
                        }
                        "filename-pattern" => {
                            opts.filename_pattern = Some(val.to_string());
                        }
                        "color-line-number" | "color-match" | "color-path" | "width" => {
                            // Accept and ignore for compatibility.
                        }
                        _ => {
                            return Err(format!("Unknown option: --{key}={val}"));
                        }
                    }
                    continue;
                }
            }

            if a.starts_with("--") {
                match a {
                    "--version" => opts.version = true,
                    "--help" => opts.help = true,
                    "--hidden" => opts.hidden = true,
                    "--skip-vcs-ignores" => opts.skip_vcs_ignores = true,
                    "--unrestricted" => opts.unrestricted = true,
                    "--follow" => opts.follow_symlinks = true,
                    "--norecurse" => {
                        opts.no_recurse = true;
                        opts.recurse_mode = RecurseMode::NoRecurse;
                    }
                    "--recurse" => {
                        opts.recurse = true;
                        opts.recurse_mode = RecurseMode::Recurse;
                    }
                    "--nocolor" | "--no-color" => {
                        opts.no_color = true;
                        opts.color = false;
                    }
                    "--color" => {
                        opts.color = true;
                        opts.no_color = false;
                    }
                    "--parallel" => opts.parallel = true,
                    "--noaffinity" => opts.no_affinity = true,
                    "--literal" => opts.literal = true,
                    "--fixed-strings" => opts.literal = true,
                    "--word-regexp" => opts.word_regexp = true,
                    "--search-binary" => opts.search_binary = true,
                    "--one-device" => opts.one_device = true,
                    "--count" => opts.count = true,
                    "--files-with-matches" => opts.files_with_matches = true,
                    "--invert-match" => opts.invert_match = true,
                    "--all-types" => opts.all_types = true,
                    "--all-text" => opts.all_text = true,
                    "--ignore-case" => {
                        opts.case_insensitive = true;
                        opts.case_mode = CaseMode::Insensitive;
                    }
                    "--case-sensitive" => {
                        opts.case_sensitive = true;
                        opts.case_mode = CaseMode::Sensitive;
                    }
                    "--smart-case" => {
                        opts.smart_case = true;
                        opts.case_mode = CaseMode::Smart;
                    }
                    "--nomultiline" => {
                        opts.no_multiline = true;
                        opts.multiline_mode = MultilineMode::Disabled;
                    }
                    "--multiline" => {
                        opts.multiline = true;
                        opts.multiline_mode = MultilineMode::Enabled;
                    }
                    "--numbers" => opts.numbers = true,
                    "--nonumbers" => opts.no_numbers = true,
                    "--nofilename" => opts.no_filename = true,
                    "--filename" => opts.filename = true,
                    "--heading" => opts.heading = true,
                    "--noheading" => opts.no_heading = true,
                    "--break" => opts.file_break = true,
                    "--nobreak" => opts.no_break = true,
                    "--silent" | "--stats" | "--stats-only" | "--vimgrep" | "--ackmate"
                    | "--print-long-lines" | "--passthrough" | "--null" | "--print0"
                    | "--print-all-files" | "--column" | "--nogroup" | "--group" => {
                        // Accept for compatibility, not yet implemented.
                    }
                    "--depth" => {
                        let val = iter.next().ok_or("--depth requires a value")?;
                        opts.max_depth = val
                            .as_ref()
                            .parse()
                            .map_err(|_| format!("Invalid --depth value: {}", val.as_ref()))?;
                    }
                    "--workers" => {
                        let val = iter.next().ok_or("--workers requires a value")?;
                        opts.workers =
                            Some(val.as_ref().parse().map_err(|_| {
                                format!("Invalid --workers value: {}", val.as_ref())
                            })?);
                    }
                    "--max-count" => {
                        let val = iter.next().ok_or("--max-count requires a value")?;
                        opts.max_count = val
                            .as_ref()
                            .parse()
                            .map_err(|_| format!("Invalid --max-count value: {}", val.as_ref()))?;
                    }
                    "--after" => {
                        let val = iter.next().ok_or("--after requires a value")?;
                        opts.after_context = val
                            .as_ref()
                            .parse()
                            .map_err(|_| format!("Invalid --after value: {}", val.as_ref()))?;
                    }
                    "--before" => {
                        let val = iter.next().ok_or("--before requires a value")?;
                        opts.before_context = val
                            .as_ref()
                            .parse()
                            .map_err(|_| format!("Invalid --before value: {}", val.as_ref()))?;
                    }
                    "--context" => {
                        let val = iter.next().ok_or("--context requires a value")?;
                        let n: usize = val
                            .as_ref()
                            .parse()
                            .map_err(|_| format!("Invalid --context value: {}", val.as_ref()))?;
                        opts.before_context = n;
                        opts.after_context = n;
                    }
                    "--ignore" | "--ignore-dir" => {
                        let val = iter.next().ok_or("--ignore requires a value")?;
                        opts.ignore_patterns.push(val.as_ref().to_string());
                    }
                    "--file-search-regex" => {
                        let val = iter.next().ok_or("--file-search-regex requires a value")?;
                        opts.file_search_regex = Some(val.as_ref().to_string());
                    }
                    "--path-to-ignore" => {
                        // Accept and consume value; not yet fully implemented.
                        let _val = iter.next().ok_or("--path-to-ignore requires a value")?;
                    }
                    _ => {
                        return Err(format!("Unknown option: {a}"));
                    }
                }
                continue;
            }

            // Short options (can be combined: -ivU).
            if a.starts_with('-') && a.len() > 1 && !a.starts_with("--") {
                let chars: Vec<char> = a[1..].chars().collect();
                let mut i = 0;
                while i < chars.len() {
                    match chars[i] {
                        'h' => opts.help = true,
                        'i' => {
                            opts.case_insensitive = true;
                            opts.case_mode = CaseMode::Insensitive;
                        }
                        's' => {
                            opts.case_sensitive = true;
                            opts.case_mode = CaseMode::Sensitive;
                        }
                        'S' => {
                            opts.smart_case = true;
                            opts.case_mode = CaseMode::Smart;
                        }
                        'c' => opts.count = true,
                        'l' => opts.files_with_matches = true,
                        'v' => opts.invert_match = true,
                        'U' => opts.skip_vcs_ignores = true,
                        'u' => opts.unrestricted = true,
                        'f' => opts.follow_symlinks = true,
                        'n' => {
                            opts.no_recurse = true;
                            opts.recurse_mode = RecurseMode::NoRecurse;
                        }
                        'r' => {
                            opts.recurse = true;
                            opts.recurse_mode = RecurseMode::Recurse;
                        }
                        'Q' => opts.literal = true,
                        'F' => opts.literal = true,
                        'w' => opts.word_regexp = true,
                        'a' => opts.all_types = true,
                        't' => opts.all_text = true,
                        'D' => { /* debug — accept, ignore */ }
                        'z' => { /* search-zip — accept, ignore */ }
                        'o' => { /* only-matching — accept, ignore */ }
                        'H' => opts.heading = true,
                        'L' => opts.files_with_matches = true, // files-without-matches inverts later
                        '0' => { /* null — accept, ignore */ }
                        'A' => {
                            // -A NUM or -ANUM
                            let rest: String = chars[i + 1..].iter().collect();
                            if !rest.is_empty() {
                                opts.after_context = rest
                                    .parse()
                                    .map_err(|_| format!("Invalid -A value: {rest}"))?;
                                i = chars.len(); // consume rest
                                continue;
                            } else {
                                let val = iter.next().ok_or("-A requires a value")?;
                                opts.after_context = val
                                    .as_ref()
                                    .parse()
                                    .map_err(|_| format!("Invalid -A value: {}", val.as_ref()))?;
                            }
                        }
                        'B' => {
                            let rest: String = chars[i + 1..].iter().collect();
                            if !rest.is_empty() {
                                opts.before_context = rest
                                    .parse()
                                    .map_err(|_| format!("Invalid -B value: {rest}"))?;
                                i = chars.len();
                                continue;
                            } else {
                                let val = iter.next().ok_or("-B requires a value")?;
                                opts.before_context = val
                                    .as_ref()
                                    .parse()
                                    .map_err(|_| format!("Invalid -B value: {}", val.as_ref()))?;
                            }
                        }
                        'C' => {
                            let rest: String = chars[i + 1..].iter().collect();
                            let n = if !rest.is_empty() {
                                rest.parse()
                                    .map_err(|_| format!("Invalid -C value: {rest}"))?
                            } else {
                                let val = iter.next().ok_or("-C requires a value")?;
                                val.as_ref()
                                    .parse()
                                    .map_err(|_| format!("Invalid -C value: {}", val.as_ref()))?
                            };
                            opts.before_context = n;
                            opts.after_context = n;
                            if !rest.is_empty() {
                                i = chars.len();
                                continue;
                            }
                        }
                        'm' => {
                            let rest: String = chars[i + 1..].iter().collect();
                            if !rest.is_empty() {
                                opts.max_count = rest
                                    .parse()
                                    .map_err(|_| format!("Invalid -m value: {rest}"))?;
                                i = chars.len();
                                continue;
                            } else {
                                let val = iter.next().ok_or("-m requires a value")?;
                                opts.max_count = val
                                    .as_ref()
                                    .parse()
                                    .map_err(|_| format!("Invalid -m value: {}", val.as_ref()))?;
                            }
                        }
                        'g' => {
                            let rest: String = chars[i + 1..].iter().collect();
                            if !rest.is_empty() {
                                opts.filename_pattern = Some(rest);
                                i = chars.len();
                                continue;
                            } else {
                                let val = iter.next().ok_or("-g requires a value")?;
                                opts.filename_pattern = Some(val.as_ref().to_string());
                            }
                        }
                        'G' => {
                            let rest: String = chars[i + 1..].iter().collect();
                            if !rest.is_empty() {
                                opts.file_search_regex = Some(rest);
                                i = chars.len();
                                continue;
                            } else {
                                let val = iter.next().ok_or("-G requires a value")?;
                                opts.file_search_regex = Some(val.as_ref().to_string());
                            }
                        }
                        'p' => {
                            // --path-to-ignore shorthand; consumes rest of
                            // combined flags or next argument as value.
                            let rest: String = chars[i + 1..].iter().collect();
                            if !rest.is_empty() {
                                // Value is the remainder of the combined flag
                                // (e.g. -p/tmp/ignore).
                            } else {
                                let _val = iter.next().ok_or("-p requires a value")?;
                            }
                            i = chars.len();
                            continue;
                        }
                        'W' => {
                            // Width — accept, consume value
                            let rest: String = chars[i + 1..].iter().collect();
                            if rest.is_empty() {
                                let _val = iter.next();
                            }
                            i = chars.len();
                            continue;
                        }
                        _ => {
                            return Err(format!("Unknown option: -{}", chars[i]));
                        }
                    }
                    i += 1;
                }
                continue;
            }

            // Positional argument.
            positional.push(a.to_string());
        }

        // Assign positional args.
        // When -g is set, all positional args are paths (no content pattern needed).
        // Otherwise, first positional is the pattern, rest are paths.
        if opts.filename_pattern.is_some() {
            // -g mode: all positional args are paths.
            if !positional.is_empty() {
                opts.paths = positional;
                opts.paths_were_explicit = true;
            }
        } else {
            if let Some(pat) = positional.first() {
                opts.pattern = Some(pat.clone());
            }
            if positional.len() > 1 {
                opts.paths = positional[1..].to_vec();
                opts.paths_were_explicit = true;
            }
        }

        // If no paths specified, default to current directory.
        if opts.paths.is_empty() && (opts.pattern.is_some() || opts.filename_pattern.is_some()) {
            opts.paths.push(".".to_string());
            // paths_were_explicit remains false — no paths were given
        }

        // ag treats --max-count=0 / -m0 as "no limit" (its internal default
        // is 0 meaning unlimited, guarded by `> 0` checks in search.c).
        // Map to usize::MAX so downstream comparisons (total >= max_count)
        // are effectively never true, giving truly unlimited behavior.
        if opts.max_count == 0 {
            opts.max_count = usize::MAX;
        }

        Ok(opts)
    }
}
