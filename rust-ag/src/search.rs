/// Search engine for rust-ag.
///
/// Implements line-by-line search through files, producing matches
/// in `ag`-compatible output format.
use std::fs;
use std::path::Path;

use regex::Regex;

use crate::opts::Opts;

/// A single match result.
#[derive(Debug)]
pub struct Match {
    /// 1-based line number.
    pub line_number: usize,
    /// The full text of the matching line.
    pub line: String,
}

/// Search a single file for the given pattern.
///
/// Returns a vector of matches found. Respects `--max-count` per file.
pub fn search_file(path: &Path, re: &Regex, opts: &Opts) -> Vec<Match> {
    let content = match fs::read(path) {
        Ok(data) => data,
        Err(_) => return Vec::new(),
    };

    // Binary check: if file contains null bytes, skip unless --search-binary.
    if !opts.search_binary && !opts.unrestricted {
        let check_len = content.len().min(512);
        if content[..check_len].contains(&0) {
            return Vec::new();
        }
    }

    let text = match std::str::from_utf8(&content) {
        Ok(s) => s,
        Err(_) => {
            // Non-UTF8 file: try lossy conversion.
            let s = String::from_utf8_lossy(&content);
            return search_text(path, &s, re, opts);
        }
    };

    search_text(path, text, re, opts)
}

/// Search text content for matches.
fn search_text(_path: &Path, text: &str, re: &Regex, opts: &Opts) -> Vec<Match> {
    let mut matches = Vec::new();
    let mut match_count = 0;

    for (idx, line) in text.lines().enumerate() {
        let has_match = re.is_match(line);

        // Handle --invert-match.
        let report = if opts.invert_match {
            !has_match
        } else {
            has_match
        };

        if report {
            match_count += 1;
            if match_count > opts.max_count {
                break;
            }
            matches.push(Match {
                line_number: idx + 1,
                line: line.to_string(),
            });
        }
    }

    matches
}

/// Build a regex from the pattern and options.
pub fn build_regex(opts: &Opts) -> Result<Regex, String> {
    let pattern = match &opts.pattern {
        Some(p) => p.clone(),
        None => return Err("No pattern specified".to_string()),
    };

    // Build the actual regex string.
    let mut regex_str = if opts.literal {
        regex::escape(&pattern)
    } else {
        pattern.clone()
    };

    // Word boundary wrapping.
    if opts.word_regexp {
        regex_str = format!("\\b{regex_str}\\b");
    }

    // Determine case sensitivity.
    let case_insensitive = if opts.case_sensitive {
        false
    } else if opts.case_insensitive {
        true
    } else if opts.smart_case {
        // Smart case: case-insensitive unless pattern has uppercase.
        !pattern.chars().any(|c| c.is_uppercase())
    } else {
        false
    };

    let re = regex::RegexBuilder::new(&regex_str)
        .case_insensitive(case_insensitive)
        .build()
        .map_err(|e| format!("Invalid regex pattern: {e}"))?;

    Ok(re)
}
