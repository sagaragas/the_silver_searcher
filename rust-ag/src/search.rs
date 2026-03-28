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
    /// Total number of regex match occurrences (not lines).
    /// Used by --count mode which reports match occurrences, not line counts.
    pub match_count: usize,
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
                match_count: 0,
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
            match_count: 0,
        };
    }

    // Binary check: replicate baseline ag's is_binary() heuristics.
    let is_binary = is_binary_buf(&content);

    if is_binary {
        if !opts.search_binary && !opts.unrestricted {
            // Skip binary files entirely when not in binary-search mode.
            return FileSearchResult {
                matches: Vec::new(),
                is_binary: true,
                binary_has_match: false,
                max_count_hit: false,
                match_count: 0,
            };
        }

        // In --search-binary or -u mode with -c or -l: actually search the
        // binary file content and return real match results so the caller can
        // print counts or filenames (matching ag behavior where -c/-l bypass
        // the "Binary file X matches." message).
        //
        // ag counts individual regex match regions for -c (not lines),
        // so we count match occurrences for binary content.
        //
        // Without -c/-l, report "Binary file X matches." via binary_has_match.
        let text = String::from_utf8_lossy(&content);
        if opts.count || opts.files_with_matches {
            let match_count = count_regex_occurrences(&text, re);
            let total_positive = match_count;
            let max_count_hit = total_positive >= opts.max_count;
            // Build synthetic Match entries — one per match region for
            // counting purposes. ag uses match-region count for -c on
            // binary files.
            let capped = if opts.invert_match {
                // For binary files with -v, ag reports inverted matches;
                // this is hard to replicate meaningfully for binary content.
                // Fall back to text-based search for -v.
                let matches = search_text(&text, re, opts);
                let mc = matches.len();
                return FileSearchResult {
                    matches,
                    is_binary: true,
                    binary_has_match: false,
                    max_count_hit,
                    match_count: mc,
                };
            } else {
                match_count.min(opts.max_count)
            };
            let matches: Vec<Match> = (0..capped)
                .map(|i| Match {
                    line_number: i + 1,
                    line: String::new(),
                })
                .collect();
            return FileSearchResult {
                matches,
                is_binary: true,
                binary_has_match: false,
                max_count_hit,
                match_count,
            };
        }
        let has_match = re.is_match(&text);
        return FileSearchResult {
            matches: Vec::new(),
            is_binary: true,
            binary_has_match: has_match,
            max_count_hit: false,
            match_count: 0,
        };
    }

    let text = match std::str::from_utf8(&content) {
        Ok(s) => s,
        Err(_) => {
            // Non-UTF8 file: try lossy conversion.
            let s = String::from_utf8_lossy(&content);
            let matches = search_text(&s, re, opts);
            let total = count_total_matches_positive(&s, re, opts);
            let max_count_hit = total >= opts.max_count;
            let match_count = count_regex_occurrences(&s, re);
            return FileSearchResult {
                matches,
                is_binary: false,
                binary_has_match: false,
                max_count_hit,
                match_count,
            };
        }
    };

    let matches = search_text(text, re, opts);
    // ag emits "Too many matches" when total *positive* matches >= max_count
    // (i.e., even when the file has exactly max_count matches).
    // The diagnostic is always based on positive (non-inverted) match count,
    // regardless of whether -v/--invert-match is set.
    let total = count_total_matches_positive(text, re, opts);
    let max_count_hit = total >= opts.max_count;
    let match_count = if opts.invert_match {
        // For inverted match, the "count" is the number of non-matching lines.
        matches.len()
    } else {
        count_regex_occurrences(text, re)
    };
    FileSearchResult {
        matches,
        is_binary: false,
        binary_has_match: false,
        max_count_hit,
        match_count,
    }
}

/// Search text content for matches (public interface for stream/stdin mode).
///
/// Returns matching lines with line numbers and the total match count.
pub fn search_text_content(text: &str, re: &Regex, opts: &Opts) -> (Vec<Match>, usize) {
    let matches = search_text(text, re, opts);
    let match_count = if opts.invert_match {
        matches.len()
    } else {
        count_regex_occurrences(text, re)
    };
    (matches, match_count)
}

/// Count regex match occurrences on a single line.
/// Used by stream -c mode where ag outputs per-line match counts.
pub fn count_line_matches(line: &str, re: &Regex) -> usize {
    let buf_len = line.len();
    let mut count = 0;
    let mut search_start = 0;
    while let Some(m) = re.find_at(line, search_start) {
        count += 1;
        if m.start() == m.end() {
            if search_start >= buf_len {
                break;
            }
            search_start = next_char_boundary(line, m.end());
        } else {
            search_start = m.end();
            if search_start >= buf_len {
                break;
            }
        }
    }
    count
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

    // First pass: collect match regions, limited by max_count.
    // ag limits positive match regions to max_matches_per_file, then
    // inverts AFTER the limited scan. This means lines beyond the last
    // scanned region are treated as non-matching when -v is used.
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

        // Stop collecting regions at max_count (matches ag behavior).
        if regions.len() >= opts.max_count {
            break;
        }

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
        // ag inverts AFTER the max-count limited scan, so lines beyond
        // the scan cutoff are all "not matched" and included in output.
        let printed_set: std::collections::HashSet<usize> =
            printed_lines.iter().map(|&(ln, _, _)| ln).collect();

        let mut matches = Vec::new();
        for (idx, line) in text.lines().enumerate() {
            if !printed_set.contains(&(idx + 1)) {
                matches.push(Match {
                    line_number: idx + 1,
                    line: line.to_string(),
                });
            }
        }
        matches
    } else {
        let mut matches = Vec::new();
        for &(ln, start, end) in &printed_lines {
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
///
/// Mirrors ag behavior: positive matches are counted up to max_count,
/// then if -v is set, the match set is inverted. This means lines after
/// the max_count cutoff point are all treated as "not matched" and
/// included in inverted output.
fn search_text_line_by_line(text: &str, re: &Regex, opts: &Opts) -> Vec<Match> {
    if opts.invert_match {
        // ag scans for positive matches (limited to max_count), then
        // inverts. Lines beyond the scan cutoff are all "not matched."
        let mut matched_line_numbers = std::collections::HashSet::new();
        let mut positive_count = 0;
        let lines: Vec<&str> = text.lines().collect();

        for (idx, line) in lines.iter().enumerate() {
            if re.is_match(line) {
                matched_line_numbers.insert(idx + 1);
                positive_count += 1;
                if positive_count >= opts.max_count {
                    break;
                }
            }
        }

        // Invert: report lines not matched within the scan range, plus
        // all lines after the scan cutoff.
        let scan_end = if positive_count >= opts.max_count {
            // Find the line index where we stopped scanning.
            // The scan stopped at the line where positive_count reached max_count.
            lines
                .iter()
                .enumerate()
                .filter(|(_, l)| re.is_match(l))
                .nth(opts.max_count - 1)
                .map(|(i, _)| i + 1)
                .unwrap_or(lines.len())
        } else {
            lines.len()
        };

        let mut matches = Vec::new();
        for (idx, line) in lines.iter().enumerate() {
            let ln = idx + 1;
            if ln <= scan_end {
                // Within scanned range: only include if NOT matched.
                if !matched_line_numbers.contains(&ln) {
                    matches.push(Match {
                        line_number: ln,
                        line: line.to_string(),
                    });
                }
            } else {
                // Beyond scan cutoff: include everything (not scanned = not matched).
                matches.push(Match {
                    line_number: ln,
                    line: line.to_string(),
                });
            }
        }
        matches
    } else {
        let mut matches = Vec::new();
        let mut match_count = 0;

        for (idx, line) in text.lines().enumerate() {
            if re.is_match(line) {
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
        .map_err(|e| format!("Bad regex! {e}"))?;

    Ok(re)
}

/// Count the total number of reportable matches in the text (without
/// the max-count cap). Used to determine whether `max_count` was exceeded.
#[allow(dead_code)]
fn count_total_matches(text: &str, re: &Regex, opts: &Opts) -> usize {
    if opts.multiline_mode == MultilineMode::Enabled {
        count_matches_multiline(text, re, opts)
    } else {
        count_matches_line_by_line(text, re, opts)
    }
}

/// Count the total number of *positive* (non-inverted) matches in the text.
/// Always counts lines that the regex matches, regardless of `--invert-match`.
/// ag's max-count diagnostic is based on positive match count.
fn count_total_matches_positive(text: &str, re: &Regex, opts: &Opts) -> usize {
    if opts.multiline_mode == MultilineMode::Enabled {
        count_matches_multiline_positive(text, re, opts)
    } else {
        count_matches_line_by_line_positive(text, re)
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

/// Count multiline positive matches (always positive, ignoring -v).
fn count_matches_multiline_positive(text: &str, re: &Regex, _opts: &Opts) -> usize {
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

    if regions.is_empty() {
        return 0;
    }

    // Simulate the print state machine to count positive match lines.
    let mut cur_match: usize = 0;
    let mut in_a_match = false;
    let mut lines_since_last_match: usize = usize::MAX;
    let mut prev_line_offset: usize = 0;
    let mut count: usize = 0;

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
                count += 1;
            }
            prev_line_offset = i + 1;
            if !in_a_match && lines_since_last_match < usize::MAX {
                lines_since_last_match = lines_since_last_match.saturating_add(1);
            }
        }
        i += 1;
    }

    count
}

/// Count line-by-line positive matches (always positive, ignoring -v).
fn count_matches_line_by_line_positive(text: &str, re: &Regex) -> usize {
    text.lines().filter(|line| re.is_match(line)).count()
}

/// Count individual regex match occurrences in text (match regions, not lines).
/// Used for binary file counting where ag counts match regions, not lines.
fn count_regex_occurrences(text: &str, re: &Regex) -> usize {
    let buf_len = text.len();
    let mut count = 0;
    let mut search_start = 0;
    while let Some(m) = re.find_at(text, search_start) {
        count += 1;
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
    count
}

/// Check whether a buffer looks like binary content, replicating baseline ag's
/// `is_binary()` heuristics from `src/util.c`.
///
/// The checks, in order:
///   1. Empty → not binary
///   2. UTF-8 BOM (EF BB BF) → not binary
///   3. `%PDF-` header → binary
///   4. Null byte in first 512 bytes → binary
///   5. >10% suspicious (non-ASCII, non-UTF-8) bytes in first 512 → binary
pub fn is_binary_buf(buf: &[u8]) -> bool {
    if buf.is_empty() {
        return false;
    }

    // UTF-8 BOM → not binary.
    if buf.len() >= 3 && buf[0] == 0xEF && buf[1] == 0xBB && buf[2] == 0xBF {
        return false;
    }

    // PDF header → binary.
    if buf.len() >= 5 && &buf[..5] == b"%PDF-" {
        return true;
    }

    let total_bytes = buf.len().min(512);
    let mut suspicious_bytes: usize = 0;

    let mut i = 0;
    while i < total_bytes {
        if buf[i] == 0 {
            // Null byte → binary.
            return true;
        }

        // Check for suspicious bytes: non-printable, non-standard-ASCII.
        // ag checks: (byte < 7 || byte > 14) && (byte < 32 || byte > 127)
        if (buf[i] < 7 || buf[i] > 14) && (buf[i] < 32 || buf[i] > 127) {
            // Try to decode as valid UTF-8 multi-byte sequence.
            if buf[i] > 193 && buf[i] < 224 && i + 1 < total_bytes {
                // 2-byte UTF-8 sequence.
                if buf[i + 1] > 127 && buf[i + 1] < 192 {
                    i += 2; // Skip continuation byte.
                    continue;
                }
            } else if buf[i] > 223 && buf[i] < 240 && i + 2 < total_bytes {
                // 3-byte UTF-8 sequence.
                if buf[i + 1] > 127 && buf[i + 1] < 192 && buf[i + 2] > 127 && buf[i + 2] < 192 {
                    i += 3; // Skip continuation bytes.
                    continue;
                }
            }
            suspicious_bytes += 1;
            // After 32 bytes, check ratio.
            if i >= 32 && (suspicious_bytes * 100) / total_bytes > 10 {
                return true;
            }
        }
        i += 1;
    }

    // Final ratio check after processing all bytes.
    // Baseline ag applies this check for all buffer lengths (no minimum),
    // so short files with >10% suspicious bytes are classified as binary.
    if (suspicious_bytes * 100) / total_bytes > 10 {
        return true;
    }

    false
}
