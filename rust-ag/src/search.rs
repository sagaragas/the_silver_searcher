/// Search engine for rust-ag.
///
/// Implements file search with multiline support, producing matches
/// in `ag`-compatible output format. By default, `ag` uses multiline
/// matching (regex can span `\n`), and `--nomultiline` disables this.
use std::fs;
use std::path::Path;

use regex::Regex;

use crate::opts::{CaseMode, MultilineMode, Opts};

/// A single match result.
#[derive(Debug)]
pub struct Match {
    /// 1-based line number.
    pub line_number: usize,
    /// The full text of the matching line.
    pub line: String,
}

/// Result of searching a single file.
#[derive(Debug)]
pub struct FileSearchResult {
    /// Matches found in the file.
    pub matches: Vec<Match>,
    /// Whether the file was detected as binary (contains null bytes).
    pub is_binary: bool,
    /// Whether the file had any regex matches (used for "Binary file X matches." output).
    pub binary_has_match: bool,
    /// Whether max-count was reached (triggers "Too many matches" diagnostic).
    pub max_count_hit: bool,
}

/// Search a single file for the given pattern.
///
/// Returns a `FileSearchResult` containing matches and metadata about
/// binary detection and max-count truncation. This allows the caller
/// to produce the correct `ag`-compatible output messages.
pub fn search_file(path: &Path, re: &Regex, opts: &Opts) -> FileSearchResult {
    let content = match fs::read(path) {
        Ok(data) => data,
        Err(_) => {
            return FileSearchResult {
                matches: Vec::new(),
                is_binary: false,
                binary_has_match: false,
                max_count_hit: false,
            };
        }
    };

    // Skip empty files (ag skips 0-byte files).
    if content.is_empty() {
        return FileSearchResult {
            matches: Vec::new(),
            is_binary: false,
            binary_has_match: false,
            max_count_hit: false,
        };
    }

    // Binary check: detect null bytes in the first 512 bytes.
    let check_len = content.len().min(512);
    let has_null = content[..check_len].contains(&0);

    if has_null {
        if !opts.search_binary && !opts.unrestricted {
            // Skip binary files entirely when not in binary-search mode.
            return FileSearchResult {
                matches: Vec::new(),
                is_binary: true,
                binary_has_match: false,
                max_count_hit: false,
            };
        }

        // In --search-binary or -u mode: check if the regex matches anywhere
        // in the file, but don't return line-by-line matches. Instead, report
        // "Binary file X matches." via the binary_has_match flag.
        let text = String::from_utf8_lossy(&content);
        let has_match = re.is_match(&text);
        return FileSearchResult {
            matches: Vec::new(),
            is_binary: true,
            binary_has_match: has_match,
            max_count_hit: false,
        };
    }

    let text = match std::str::from_utf8(&content) {
        Ok(s) => s,
        Err(_) => {
            // Non-UTF8 file: try lossy conversion.
            let s = String::from_utf8_lossy(&content);
            let matches = search_text(&s, re, opts);
            let total = count_total_matches(&s, re, opts);
            let max_count_hit = total >= opts.max_count;
            return FileSearchResult {
                matches,
                is_binary: false,
                binary_has_match: false,
                max_count_hit,
            };
        }
    };

    let matches = search_text(text, re, opts);
    // ag emits "Too many matches" when total matches >= max_count
    // (i.e., even when the file has exactly max_count matches).
    let total = count_total_matches(text, re, opts);
    let max_count_hit = total >= opts.max_count;
    FileSearchResult {
        matches,
        is_binary: false,
        binary_has_match: false,
        max_count_hit,
    }
}

/// Search text content for matches.
///
/// When multiline is enabled (default), uses the regex against the whole file
/// content and maps match regions back to line numbers. When multiline is
/// disabled (`--nomultiline`), searches line-by-line.
fn search_text(text: &str, re: &Regex, opts: &Opts) -> Vec<Match> {
    if opts.multiline_mode == MultilineMode::Enabled {
        search_text_multiline(text, re, opts)
    } else {
        search_text_line_by_line(text, re, opts)
    }
}

/// Multiline search: run regex against the whole file content, simulating
/// `ag`'s print-state-machine to determine which lines to report.
///
/// In `ag`, the regex matches are found first (against the whole buffer with
/// `PCRE_MULTILINE`), then a byte-by-byte print loop decides which lines to
/// display based on match positions. The print loop maintains:
/// - `in_a_match`: whether the current byte position is inside a match region
/// - `lines_since_last_match`: reset to 0 when entering a match, incremented
///   at end-of-line when not inside a match
/// - A line is printed when `lines_since_last_match == 0` at end-of-line
///
/// This function faithfully reproduces that state machine.
fn search_text_multiline(text: &str, re: &Regex, opts: &Opts) -> Vec<Match> {
    let text_bytes = text.as_bytes();
    let buf_len = text_bytes.len();

    // First pass: collect all match regions.
    struct MatchRegion {
        start: usize,
        end: usize,
    }
    let mut regions = Vec::new();

    let mut search_start = 0;
    while let Some(m) = re.find_at(text, search_start) {
        regions.push(MatchRegion {
            start: m.start(),
            end: m.end(),
        });

        if m.start() == m.end() {
            if search_start >= buf_len {
                break;
            }
            search_start = next_char_boundary(text, m.end());
        } else {
            search_start = m.end();
            if search_start >= buf_len {
                break;
            }
        }
    }

    if regions.is_empty() && !opts.invert_match {
        return Vec::new();
    }

    // Second pass: simulate ag's print state machine to decide which
    // lines to output.
    let mut cur_match: usize = 0;
    let mut in_a_match = false;
    let mut lines_since_last_match: usize = usize::MAX;
    let mut prev_line_offset: usize = 0;
    let mut line_number: usize = 1;

    // Track which lines should be printed (for invert-match, we also need
    // to know which lines were matched).
    let mut printed_lines: Vec<(usize, usize, usize)> = Vec::new(); // (line_number, start, end)

    let mut i: usize = 0;
    while i <= buf_len && (cur_match < regions.len() || lines_since_last_match == 0) {
        // Check if we've entered a match region.
        if cur_match < regions.len() && i == regions[cur_match].start {
            in_a_match = true;
            lines_since_last_match = 0;
        }

        // Check if we've exited a match region.
        if cur_match < regions.len() && i == regions[cur_match].end {
            cur_match += 1;
            in_a_match = false;
        }

        // End of line (newline or end of buffer).
        if i == buf_len || text_bytes[i] == b'\n' {
            // Only print lines with actual content. Skip the phantom empty
            // line that appears when the file ends with a newline (i.e.,
            // prev_line_offset == buf_len means the "line" is empty and
            // exists only because of a trailing newline).
            if lines_since_last_match == 0 && prev_line_offset < buf_len {
                printed_lines.push((line_number, prev_line_offset, i));
            }

            prev_line_offset = i + 1;
            line_number += 1;

            if !in_a_match && lines_since_last_match < usize::MAX {
                lines_since_last_match = lines_since_last_match.saturating_add(1);
            }
        }

        i += 1;
    }

    // Build the output matches.
    if opts.invert_match {
        // For invert-match: report lines that were NOT in printed_lines.
        let printed_set: std::collections::HashSet<usize> =
            printed_lines.iter().map(|&(ln, _, _)| ln).collect();

        let mut matches = Vec::new();
        let mut match_count = 0;
        for (idx, line) in text.lines().enumerate() {
            if !printed_set.contains(&(idx + 1)) {
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
    } else {
        let mut matches = Vec::new();
        let mut match_count = 0;
        for &(ln, start, end) in &printed_lines {
            match_count += 1;
            if match_count > opts.max_count {
                break;
            }
            let line_text = &text[start..end];
            matches.push(Match {
                line_number: ln,
                line: line_text.to_string(),
            });
        }
        matches
    }
}

/// Get the next UTF-8 character boundary after `pos`.
fn next_char_boundary(text: &str, pos: usize) -> usize {
    let mut next = pos + 1;
    while next < text.len() && !text.is_char_boundary(next) {
        next += 1;
    }
    next
}

/// Line-by-line search (used when `--nomultiline` is set).
fn search_text_line_by_line(text: &str, re: &Regex, opts: &Opts) -> Vec<Match> {
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
///
/// Applies case-mode resolution using "last wins" flag precedence via
/// `opts.case_mode`, multiline mode (dot-matches-newline when multiline
/// is active), and literal/word-boundary wrapping.
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

    // Determine case sensitivity using "last wins" precedence.
    let case_insensitive = match opts.case_mode {
        CaseMode::Insensitive => true,
        CaseMode::Sensitive => false,
        CaseMode::Smart => {
            // Smart case: case-insensitive unless the *original* pattern
            // (before escaping) has uppercase characters.
            !pattern.chars().any(|c| c.is_uppercase())
        }
    };

    // ag's multiline mode uses PCRE_MULTILINE: ^ and $ match at line
    // boundaries, but . does NOT match \n (PCRE_DOTALL is not set).
    // The pattern can still contain literal \n to span lines.
    // When --nomultiline is set, we search line-by-line so \n in the
    // pattern cannot match.
    let re = regex::RegexBuilder::new(&regex_str)
        .case_insensitive(case_insensitive)
        .multi_line(true) // ^ and $ match at line boundaries
        .dot_matches_new_line(false) // . does NOT match \n (matches ag/PCRE)
        .build()
        .map_err(|e| format!("Invalid regex pattern: {e}"))?;

    Ok(re)
}

/// Count the total number of reportable matches in the text (without
/// the max-count cap). Used to determine whether `max_count` was exceeded.
fn count_total_matches(text: &str, re: &Regex, opts: &Opts) -> usize {
    if opts.multiline_mode == MultilineMode::Enabled {
        count_matches_multiline(text, re, opts)
    } else {
        count_matches_line_by_line(text, re, opts)
    }
}

/// Count multiline matches.
fn count_matches_multiline(text: &str, re: &Regex, opts: &Opts) -> usize {
    let text_bytes = text.as_bytes();
    let buf_len = text_bytes.len();

    struct MatchRegion {
        start: usize,
        end: usize,
    }
    let mut regions = Vec::new();
    let mut search_start = 0;
    while let Some(m) = re.find_at(text, search_start) {
        regions.push(MatchRegion {
            start: m.start(),
            end: m.end(),
        });
        if m.start() == m.end() {
            if search_start >= buf_len {
                break;
            }
            search_start = next_char_boundary(text, m.end());
        } else {
            search_start = m.end();
            if search_start >= buf_len {
                break;
            }
        }
    }

    if regions.is_empty() && !opts.invert_match {
        return 0;
    }

    // Simulate the print state machine to count lines that would print.
    let mut cur_match: usize = 0;
    let mut in_a_match = false;
    let mut lines_since_last_match: usize = usize::MAX;
    let mut prev_line_offset: usize = 0;
    let mut line_number: usize = 1;
    let mut printed_lines: Vec<usize> = Vec::new();

    let mut i: usize = 0;
    while i <= buf_len && (cur_match < regions.len() || lines_since_last_match == 0) {
        if cur_match < regions.len() && i == regions[cur_match].start {
            in_a_match = true;
            lines_since_last_match = 0;
        }
        if cur_match < regions.len() && i == regions[cur_match].end {
            cur_match += 1;
            in_a_match = false;
        }
        if i == buf_len || text_bytes[i] == b'\n' {
            if lines_since_last_match == 0 && prev_line_offset < buf_len {
                printed_lines.push(line_number);
            }
            prev_line_offset = i + 1;
            line_number += 1;
            if !in_a_match && lines_since_last_match < usize::MAX {
                lines_since_last_match = lines_since_last_match.saturating_add(1);
            }
        }
        i += 1;
    }

    if opts.invert_match {
        let printed_set: std::collections::HashSet<usize> = printed_lines.iter().copied().collect();
        text.lines()
            .enumerate()
            .filter(|(idx, _)| !printed_set.contains(&(idx + 1)))
            .count()
    } else {
        printed_lines.len()
    }
}

/// Count line-by-line matches.
fn count_matches_line_by_line(text: &str, re: &Regex, opts: &Opts) -> usize {
    let mut count = 0;
    for line in text.lines() {
        let has_match = re.is_match(line);
        let report = if opts.invert_match {
            !has_match
        } else {
            has_match
        };
        if report {
            count += 1;
        }
    }
    count
}
