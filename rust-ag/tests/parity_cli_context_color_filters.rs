/// Parity tests for context rendering, color toggles, file filtering,
/// and help/version output contracts.
///
/// Covers:
///   VAL-CLI-004: Context flags produce expected format
///   VAL-CLI-005: Color controls are correct
///   VAL-CLI-006: Filename filtering flags are preserved
///   VAL-CLI-007: Help and version interfaces are stable
use std::io::Write;
use std::process::{Command, Stdio};

/// Path to the rust-ag binary built by cargo.
fn rust_ag_bin() -> std::path::PathBuf {
    let mut path = std::path::PathBuf::from(env!("CARGO_BIN_EXE_rust-ag"));
    if !path.exists() {
        path = std::path::PathBuf::from("target/debug/rust-ag");
    }
    path
}

/// Helper: run rust-ag on file paths and return (stdout, stderr, exit_code).
fn run_ag(args: &[&str]) -> (String, String, i32) {
    let out = Command::new(rust_ag_bin())
        .args(args)
        .output()
        .expect("failed to run rust-ag");
    (
        String::from_utf8_lossy(&out.stdout).to_string(),
        String::from_utf8_lossy(&out.stderr).to_string(),
        out.status.code().unwrap_or(-1),
    )
}

/// Helper: run rust-ag with stdin piped and return (stdout, stderr, exit_code).
#[allow(dead_code)]
fn run_ag_stdin(args: &[&str], stdin_data: &str) -> (String, String, i32) {
    let mut child = Command::new(rust_ag_bin())
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("failed to spawn rust-ag");

    if let Some(ref mut stdin) = child.stdin {
        stdin.write_all(stdin_data.as_bytes()).unwrap();
    }
    drop(child.stdin.take());

    let out = child.wait_with_output().expect("failed to wait on rust-ag");
    (
        String::from_utf8_lossy(&out.stdout).to_string(),
        String::from_utf8_lossy(&out.stderr).to_string(),
        out.status.code().unwrap_or(-1),
    )
}

/// Helper: run rust-ag and return raw stdout bytes.
fn run_ag_raw(args: &[&str]) -> (Vec<u8>, Vec<u8>, i32) {
    let out = Command::new(rust_ag_bin())
        .args(args)
        .output()
        .expect("failed to run rust-ag");
    (out.stdout, out.stderr, out.status.code().unwrap_or(-1))
}

fn setup_context_fixture() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let base = dir.path();

    // context.txt has lines spaced enough to test context groups and separators
    // line1
    // line2 hello
    // line3
    // line4
    // line5
    // line6 hello
    // line7
    // line8
    std::fs::write(
        base.join("context.txt"),
        "line1\nline2 hello\nline3\nline4\nline5\nline6 hello\nline7\nline8\n",
    )
    .unwrap();

    // adjacent.txt: matches close enough that context overlaps
    // line1 hello
    // line2
    // line3 hello
    // line4
    std::fs::write(
        base.join("adjacent.txt"),
        "line1 hello\nline2\nline3 hello\nline4\n",
    )
    .unwrap();

    dir
}

fn setup_filter_fixture() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let base = dir.path();

    std::fs::write(base.join("foo.rs"), "hello from rust\n").unwrap();
    std::fs::write(base.join("bar.txt"), "hello from text\n").unwrap();
    std::fs::write(base.join("baz.py"), "hello from python\n").unwrap();

    std::fs::create_dir_all(base.join("sub")).unwrap();
    std::fs::write(base.join("sub").join("deep.rs"), "hello deep\n").unwrap();

    dir
}

// ============================================================
// VAL-CLI-004: Context flags produce expected format
// ============================================================

#[test]
fn val_cli_004_after_context() {
    let dir = setup_context_fixture();
    let f = dir.path().join("context.txt");
    let (stdout, _stderr, exit) = run_ag(&["--nocolor", "-A1", "hello", f.to_str().unwrap()]);
    // Expected: match lines with `:`, after-context lines with `-`
    let lines: Vec<&str> = stdout.lines().collect();
    // line2 hello (match) and line3 (after), line6 hello (match) and line7 (after)
    assert!(
        lines
            .iter()
            .any(|l| l.starts_with("2:") && l.contains("hello")),
        "Should have match at line 2: {lines:?}"
    );
    assert!(
        lines.iter().any(|l| l.starts_with("3-")),
        "Should have after-context at line 3: {lines:?}"
    );
    assert!(
        lines
            .iter()
            .any(|l| l.starts_with("6:") && l.contains("hello")),
        "Should have match at line 6: {lines:?}"
    );
    assert!(
        lines.iter().any(|l| l.starts_with("7-")),
        "Should have after-context at line 7: {lines:?}"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_004_before_context() {
    let dir = setup_context_fixture();
    let f = dir.path().join("context.txt");
    let (stdout, _stderr, exit) = run_ag(&["--nocolor", "-B1", "hello", f.to_str().unwrap()]);
    let lines: Vec<&str> = stdout.lines().collect();
    // line1 (before), line2 hello (match), line5 (before), line6 hello (match)
    assert!(
        lines.iter().any(|l| l.starts_with("1-")),
        "Should have before-context at line 1: {lines:?}"
    );
    assert!(
        lines
            .iter()
            .any(|l| l.starts_with("2:") && l.contains("hello")),
        "Should have match at line 2: {lines:?}"
    );
    assert!(
        lines.iter().any(|l| l.starts_with("5-")),
        "Should have before-context at line 5: {lines:?}"
    );
    assert!(
        lines
            .iter()
            .any(|l| l.starts_with("6:") && l.contains("hello")),
        "Should have match at line 6: {lines:?}"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_004_context_separator() {
    let dir = setup_context_fixture();
    let f = dir.path().join("context.txt");
    let (stdout, _stderr, exit) = run_ag(&["--nocolor", "-C1", "hello", f.to_str().unwrap()]);
    // With -C1, line1-3 and line5-7 are two separate groups separated by "--"
    assert!(
        stdout.contains("--\n"),
        "Non-overlapping context groups should be separated by '--': {stdout}"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_004_context_overlapping_no_separator() {
    let dir = setup_context_fixture();
    let f = dir.path().join("adjacent.txt");
    let (stdout, _stderr, exit) = run_ag(&["--nocolor", "-C1", "hello", f.to_str().unwrap()]);
    // line1 hello, line2 (ctx), line3 hello, line4 (ctx) — all contiguous, no "--"
    assert!(
        !stdout.contains("--"),
        "Overlapping context should NOT have separator: {stdout}"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_004_context_match_uses_colon() {
    let dir = setup_context_fixture();
    let f = dir.path().join("context.txt");
    let (stdout, _stderr, exit) = run_ag(&["--nocolor", "-C1", "hello", f.to_str().unwrap()]);
    // Match lines use ":" separator
    for line in stdout.lines() {
        if line == "--" {
            continue;
        }
        let sep_pos = line.find([':', '-']);
        assert!(
            sep_pos.is_some(),
            "Every output line should have a : or - separator: {line}"
        );
    }
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_004_context_zero() {
    // -C0 should produce no context lines, just matches
    let dir = setup_context_fixture();
    let f = dir.path().join("context.txt");
    let (stdout, _stderr, exit) = run_ag(&["--nocolor", "-C0", "hello", f.to_str().unwrap()]);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    // Should only have match lines
    assert_eq!(lines.len(), 2, "C0 should show only match lines: {lines:?}");
    assert!(lines[0].starts_with("2:"));
    assert!(lines[1].starts_with("6:"));
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_004_context_multi_file() {
    let dir = setup_context_fixture();
    let (stdout, _stderr, exit) = run_ag(&[
        "--nocolor",
        "--workers=1",
        "-C1",
        "hello",
        dir.path().to_str().unwrap(),
    ]);
    // Multi-file context: should have filename prefix
    for line in stdout.lines() {
        if line == "--" {
            continue;
        }
        if line.is_empty() {
            continue;
        }
        // Should contain filename prefix with either : or - separator
        assert!(
            line.contains(':') || line.contains('-'),
            "Multi-file context line should have separator: {line}"
        );
    }
    assert_eq!(exit, 0);
}

// ============================================================
// VAL-CLI-005: Color controls are correct
// ============================================================

#[test]
fn val_cli_005_nocolor_no_ansi() {
    let dir = setup_context_fixture();
    let f = dir.path().join("context.txt");
    let (raw_stdout, _stderr, exit) = run_ag_raw(&["--nocolor", "hello", f.to_str().unwrap()]);
    // No ANSI escape sequences should be present
    let has_ansi = raw_stdout.windows(2).any(|w| w[0] == 0x1b && w[1] == b'[');
    assert!(
        !has_ansi,
        "nocolor output should not contain ANSI escape sequences"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_005_color_has_ansi() {
    let dir = setup_context_fixture();
    let f = dir.path().join("context.txt");
    let (raw_stdout, _stderr, exit) = run_ag_raw(&["--color", "hello", f.to_str().unwrap()]);
    // Should contain ANSI escape sequences
    let has_ansi = raw_stdout.windows(2).any(|w| w[0] == 0x1b && w[1] == b'[');
    assert!(
        has_ansi,
        "color output should contain ANSI escape sequences"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_005_color_match_highlight() {
    let dir = setup_context_fixture();
    let f = dir.path().join("context.txt");
    let (raw_stdout, _stderr, exit) = run_ag_raw(&["--color", "hello", f.to_str().unwrap()]);
    let stdout = String::from_utf8_lossy(&raw_stdout);
    // Match highlight: \e[30;43m...\e[0m\e[K
    assert!(
        stdout.contains("\x1b[30;43m"),
        "Color output should contain match highlight escape: {stdout}"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_005_color_line_number_highlight() {
    let dir = setup_context_fixture();
    let f = dir.path().join("context.txt");
    let (raw_stdout, _stderr, exit) = run_ag_raw(&["--color", "hello", f.to_str().unwrap()]);
    let stdout = String::from_utf8_lossy(&raw_stdout);
    // Line number highlight: \e[1;33m...\e[0m\e[K
    assert!(
        stdout.contains("\x1b[1;33m"),
        "Color output should contain line number escape: {stdout}"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_005_color_path_highlight_multifile() {
    let dir = setup_context_fixture();
    let (raw_stdout, _stderr, exit) = run_ag_raw(&[
        "--color",
        "--workers=1",
        "--noaffinity",
        "--parallel",
        "hello",
        dir.path().to_str().unwrap(),
    ]);
    let stdout = String::from_utf8_lossy(&raw_stdout);
    // Path highlight in multi-file: \e[1;32m...\e[0m\e[K
    assert!(
        stdout.contains("\x1b[1;32m"),
        "Color multi-file output should contain path escape: {stdout}"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_005_nocolor_explicit_overrides() {
    let dir = setup_context_fixture();
    let f = dir.path().join("context.txt");
    // --color then --nocolor: last flag wins
    let (raw_stdout, _stderr, exit) =
        run_ag_raw(&["--color", "--nocolor", "hello", f.to_str().unwrap()]);
    let has_ansi = raw_stdout.windows(2).any(|w| w[0] == 0x1b && w[1] == b'[');
    assert!(!has_ansi, "nocolor after color should suppress ANSI");
    assert_eq!(exit, 0);
}

// ============================================================
// VAL-CLI-006: Filename filtering flags are preserved
// ============================================================

#[test]
fn val_cli_006_g_flag_lists_matching_files() {
    let dir = setup_filter_fixture();
    let (stdout, _stderr, exit) = run_ag(&["-g", "\\.rs$", dir.path().to_str().unwrap()]);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    // Should find .rs files only
    assert!(
        lines.len() >= 2,
        "Should find at least 2 .rs files: {lines:?}"
    );
    for line in &lines {
        assert!(
            line.ends_with(".rs"),
            "-g should list only .rs files: {line}"
        );
    }
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_006_g_flag_no_match() {
    let dir = setup_filter_fixture();
    let (stdout, _stderr, exit) = run_ag(&["-g", "nonexistent_xyz", dir.path().to_str().unwrap()]);
    assert_eq!(stdout.trim(), "");
    assert_eq!(exit, 1, "-g with no matching files should exit 1");
}

#[test]
fn val_cli_006_g_flag_no_content_search() {
    // -g should only list files, not search content
    let dir = setup_filter_fixture();
    let (stdout, _stderr, exit) = run_ag(&["-g", "\\.txt$", dir.path().to_str().unwrap()]);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 1, "Should find 1 .txt file");
    // Should not contain file content
    assert!(
        !stdout.contains("hello"),
        "-g should not output file content"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_006_file_search_regex_filters() {
    let dir = setup_filter_fixture();
    let (stdout, _stderr, exit) = run_ag(&["-G", "\\.rs$", "hello", dir.path().to_str().unwrap()]);
    // -G filters to .rs files, then searches for "hello" in them
    let lines: Vec<&str> = stdout.trim().lines().collect();
    // Should only have results from .rs files
    for line in &lines {
        assert!(
            line.contains(".rs"),
            "-G should only show results from .rs files: {line}"
        );
    }
    assert!(
        !stdout.contains(".txt"),
        "-G should exclude .txt files: {stdout}"
    );
    assert!(
        !stdout.contains(".py"),
        "-G should exclude .py files: {stdout}"
    );
    assert_eq!(exit, 0);
}

// ============================================================
// VAL-CLI-007: Help and version interfaces are stable
// ============================================================

#[test]
fn val_cli_007_version_stdout() {
    let (stdout, stderr, exit) = run_ag(&["--version"]);
    // Version should be on stdout
    assert!(
        stdout.contains("rust-ag"),
        "Version output should contain 'rust-ag': {stdout}"
    );
    assert!(!stdout.trim().is_empty(), "Version should produce output");
    assert_eq!(exit, 0, "Version should exit 0");
    // stderr should be empty or minimal
    assert!(
        stderr.trim().is_empty(),
        "Version should not produce stderr: {stderr}"
    );
}

#[test]
fn val_cli_007_help_stdout() {
    let (stdout, stderr, exit) = run_ag(&["--help"]);
    // Help should be on stdout
    assert!(
        stdout.contains("Usage"),
        "Help output should contain 'Usage': {stdout}"
    );
    assert!(
        stdout.contains("PATTERN"),
        "Help output should describe PATTERN: {stdout}"
    );
    assert_eq!(exit, 0, "Help should exit 0");
    assert!(
        stderr.trim().is_empty(),
        "Help should not produce stderr: {stderr}"
    );
}

#[test]
fn val_cli_007_help_contains_key_flags() {
    let (stdout, _stderr, _exit) = run_ag(&["--help"]);
    // Should document key flags from our scope
    assert!(
        stdout.contains("--after") || stdout.contains("-A"),
        "Help should document -A"
    );
    assert!(
        stdout.contains("--before") || stdout.contains("-B"),
        "Help should document -B"
    );
    assert!(
        stdout.contains("--context") || stdout.contains("-C"),
        "Help should document -C"
    );
    assert!(stdout.contains("color"), "Help should document color");
    assert!(
        stdout.contains("-g") || stdout.contains("filename-pattern"),
        "Help should document -g"
    );
    assert!(
        stdout.contains("-G") || stdout.contains("file-search-regex"),
        "Help should document -G"
    );
}

#[test]
fn val_cli_007_version_has_semver_like() {
    let (stdout, _stderr, _exit) = run_ag(&["--version"]);
    // Should contain version-like string (e.g. "0.1.0")
    let re = regex::Regex::new(r"\d+\.\d+\.\d+").unwrap();
    assert!(
        re.is_match(&stdout),
        "Version should contain semver-like string: {stdout}"
    );
}

#[test]
fn val_cli_007_help_short_flag() {
    let (stdout, _stderr, exit) = run_ag(&["-h"]);
    assert!(stdout.contains("Usage"), "-h should show help: {stdout}");
    assert_eq!(exit, 0);
}
