//! Output formatting for rust-ag.
//!
//! Implements ANSI color output and context line rendering that mirrors
//! `ag`'s formatting behavior:
//!   - Match lines use `:` separator between line number and content
//!   - Context lines use `-` separator
//!   - Non-contiguous context groups are separated by `--`
//!   - Color codes: path = `\e[1;32m`, line number = `\e[1;33m`,
//!     match highlight = `\e[30;43m`, reset = `\e[0m\e[K`

use regex::Regex;

/// ANSI escape codes matching ag's defaults.
pub const COLOR_PATH: &str = "\x1b[1;32m";
pub const COLOR_LINE_NUMBER: &str = "\x1b[1;33m";
pub const COLOR_MATCH: &str = "\x1b[30;43m";
pub const COLOR_RESET: &str = "\x1b[0m\x1b[K";

/// Format a match line with optional color highlighting.
///
/// When `color` is true, the match regions in `line` are highlighted
/// with ANSI escape codes, the line number is colored, and (if provided)
/// the path prefix is colored.
pub fn format_match_line(
    path: Option<&str>,
    line_number: usize,
    line: &str,
    re: &Regex,
    color: bool,
    show_line_number: bool,
) -> String {
    let mut out = String::new();

    // Path prefix (multi-file mode).
    if let Some(p) = path {
        if color {
            out.push_str(COLOR_PATH);
            out.push_str(p);
            out.push_str(COLOR_RESET);
        } else {
            out.push_str(p);
        }
        out.push(':');
    }

    // Line number.
    if show_line_number {
        if color {
            out.push_str(COLOR_LINE_NUMBER);
            out.push_str(&line_number.to_string());
            out.push_str(COLOR_RESET);
        } else {
            out.push_str(&line_number.to_string());
        }
        out.push(':');
    }

    // Line content with match highlighting.
    if color {
        out.push_str(&highlight_matches(line, re));
    } else {
        out.push_str(line);
    }

    out
}

/// Format a context line (non-matching line in context output).
///
/// In ag, context lines use `:` after the filename (same as match lines)
/// but `-` after the line number. When there's no filename prefix and only
/// a line number, the format is `lineno-content`.
pub fn format_context_line(
    path: Option<&str>,
    line_number: usize,
    line: &str,
    color: bool,
    show_line_number: bool,
) -> String {
    let mut out = String::new();

    // Path prefix — ag uses `:` after filename even for context lines.
    if let Some(p) = path {
        if color {
            out.push_str(COLOR_PATH);
            out.push_str(p);
            out.push_str(COLOR_RESET);
        } else {
            out.push_str(p);
        }
        out.push(':');
    }

    // Line number with `-` separator (context indicator).
    if show_line_number {
        if color {
            out.push_str(COLOR_LINE_NUMBER);
            out.push_str(&line_number.to_string());
            out.push_str(COLOR_RESET);
        } else {
            out.push_str(&line_number.to_string());
        }
        out.push('-');
    }

    // Line content (no highlighting for context lines).
    out.push_str(line);

    out
}

/// Highlight match regions in a line using ANSI escape codes.
fn highlight_matches(line: &str, re: &Regex) -> String {
    let mut result = String::new();
    let mut last_end = 0;

    for m in re.find_iter(line) {
        // Append text before the match.
        result.push_str(&line[last_end..m.start()]);
        // Append highlighted match.
        result.push_str(COLOR_MATCH);
        result.push_str(&line[m.start()..m.end()]);
        result.push_str(COLOR_RESET);
        last_end = m.end();
    }

    // Append remaining text after last match.
    result.push_str(&line[last_end..]);
    result
}

/// Format a count line for --count mode with optional color.
pub fn format_count_line(path: Option<&str>, count: usize, color: bool) -> String {
    let mut out = String::new();

    if let Some(p) = path {
        if color {
            out.push_str(COLOR_PATH);
            out.push_str(p);
            out.push_str(COLOR_RESET);
        } else {
            out.push_str(p);
        }
        out.push(':');
    }

    out.push_str(&count.to_string());
    out
}
