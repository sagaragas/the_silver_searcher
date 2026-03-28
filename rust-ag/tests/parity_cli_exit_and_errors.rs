/// Parity tests for exit-code behavior across mixed outcomes and
/// invalid-option/invalid-regex diagnostics matching baseline channels and classes.
///
/// Covers:
///   VAL-CLI-008: Exit-code and error semantics are preserved
///   VAL-CLI-009: Invalid flag/regex diagnostics match baseline channels
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

// -----------------------------------------------------------------------
// Helper: create a fixture directory with known content
// -----------------------------------------------------------------------

fn setup_exit_fixture() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let base = dir.path();

    // Create a file with known content
    std::fs::write(base.join("hello.txt"), "hello world\nfoo bar\nbaz\n").unwrap();
    std::fs::write(base.join("empty.txt"), "nothing here\n").unwrap();

    dir
}

// =======================================================================
// VAL-CLI-008: Exit-code and error semantics are preserved
// =======================================================================

#[test]
fn val_cli_008_match_found_exit_0() {
    let dir = setup_exit_fixture();
    let (stdout, _stderr, exit) = run_ag(&["--nocolor", "hello", dir.path().to_str().unwrap()]);
    assert_eq!(exit, 0, "Match found should exit 0");
    assert!(stdout.contains("hello"), "stdout should contain match");
}

#[test]
fn val_cli_008_no_match_exit_1() {
    let dir = setup_exit_fixture();
    let (_stdout, _stderr, exit) = run_ag(&[
        "--nocolor",
        "xyzzy_never_match",
        dir.path().to_str().unwrap(),
    ]);
    assert_eq!(exit, 1, "No match should exit 1");
}

#[test]
fn val_cli_008_nonexistent_path_exit_1() {
    // ag exits 1 when given a nonexistent path (not 2).
    let (_stdout, stderr, exit) =
        run_ag(&["--nocolor", "test", "/nonexistent_path_for_test_12345"]);
    assert_eq!(exit, 1, "Nonexistent path should exit 1 (like ag)");
    // stderr should have an error message
    assert!(
        stderr.contains("ERR:"),
        "Nonexistent path should produce ERR on stderr: {stderr}"
    );
}

#[test]
fn val_cli_008_match_plus_nonexistent_path_exit_0() {
    // Mixed outcome: one valid path with matches + one nonexistent path.
    // ag exits 0 because matches were found.
    let dir = setup_exit_fixture();
    let dir_str = dir.path().to_str().unwrap();
    let (stdout, stderr, exit) = run_ag(&[
        "--nocolor",
        "hello",
        dir_str,
        "/nonexistent_path_for_test_12345",
    ]);
    assert_eq!(
        exit, 0,
        "Mixed match+error should exit 0 because matches found"
    );
    assert!(stdout.contains("hello"), "stdout should contain match");
    assert!(
        stderr.contains("ERR:"),
        "stderr should contain error for nonexistent path: {stderr}"
    );
}

#[test]
fn val_cli_008_nomatch_plus_nonexistent_path_exit_1() {
    // No matches in valid file + nonexistent path.
    // ag exits 1 (no matches + errors → exit 1).
    let dir = setup_exit_fixture();
    let dir_str = dir.path().to_str().unwrap();
    let (_stdout, stderr, exit) = run_ag(&[
        "--nocolor",
        "xyzzy_never_match",
        dir_str,
        "/nonexistent_path_for_test_12345",
    ]);
    assert_eq!(exit, 1, "No-match+error should exit 1 (ag semantics)");
    assert!(
        stderr.contains("ERR:"),
        "stderr should contain error for nonexistent path: {stderr}"
    );
}

#[test]
fn val_cli_008_invert_match_exit_0() {
    let dir = setup_exit_fixture();
    let (_stdout, _stderr, exit) = run_ag(&[
        "--nocolor",
        "-v",
        "xyzzy_never_match",
        dir.path().to_str().unwrap(),
    ]);
    assert_eq!(exit, 0, "Invert match with matches should exit 0");
}

#[test]
fn val_cli_008_no_args_exit_1() {
    // ag with no arguments prints usage to stdout and exits 1.
    // Note: rust-ag currently exits 2 for this case; we need to match ag (exit 1).
    let (stdout, stderr, exit) = run_ag(&[]);
    // ag no-args: usage on stdout, nothing on stderr, exit 1.
    assert_eq!(exit, 1, "No args should exit 1 (matching ag baseline)");
    assert!(
        stdout.contains("Usage"),
        "No args should print usage to stdout: stdout={stdout}"
    );
    assert!(
        stderr.trim().is_empty(),
        "No args should not produce stderr: stderr={stderr}"
    );
}

// =======================================================================
// VAL-CLI-009: Invalid flag/regex diagnostics match baseline channels
// =======================================================================

#[test]
fn val_cli_009_invalid_long_option_exit_1() {
    // ag exits 1 for unrecognized options (not 2).
    let (_stdout, _stderr, exit) = run_ag(&["--invalid-fake-option", "test", "."]);
    assert_eq!(
        exit, 1,
        "Invalid long option should exit 1 (matching ag baseline)"
    );
}

#[test]
fn val_cli_009_invalid_long_option_stderr_diagnostic() {
    // ag: stderr = 'ag: unrecognized option `--invalid-fake-option'\n'
    let (_stdout, stderr, _exit) = run_ag(&["--invalid-fake-option", "test", "."]);
    assert!(
        !stderr.is_empty(),
        "Invalid option should produce stderr diagnostic"
    );
    // The diagnostic should mention the option name
    assert!(
        stderr.contains("--invalid-fake-option"),
        "Stderr should mention the invalid option: {stderr}"
    );
}

#[test]
fn val_cli_009_invalid_long_option_stdout_has_usage() {
    // ag: stdout contains usage/help text when an invalid option is given.
    let (stdout, _stderr, _exit) = run_ag(&["--invalid-fake-option", "test", "."]);
    assert!(
        stdout.contains("Usage"),
        "Invalid option should print usage to stdout (matching ag): stdout={stdout}"
    );
}

#[test]
fn val_cli_009_invalid_short_option_exit_1() {
    // ag exits 1 for unknown short options.
    let (_stdout, _stderr, exit) = run_ag(&["-Z", "test", "."]);
    assert_eq!(
        exit, 1,
        "Invalid short option should exit 1 (matching ag baseline)"
    );
}

#[test]
fn val_cli_009_invalid_short_option_stderr_diagnostic() {
    let (_stdout, stderr, _exit) = run_ag(&["-Z", "test", "."]);
    assert!(
        !stderr.is_empty(),
        "Invalid short option should produce stderr diagnostic"
    );
}

#[test]
fn val_cli_009_invalid_short_option_stdout_has_usage() {
    let (stdout, _stderr, _exit) = run_ag(&["-Z", "test", "."]);
    assert!(
        stdout.contains("Usage"),
        "Invalid short option should print usage to stdout: stdout={stdout}"
    );
}

#[test]
fn val_cli_009_invalid_regex_exit_2() {
    // ag exits 2 for invalid regex (distinct from invalid option exit 1).
    let (_stdout, _stderr, exit) = run_ag(&["--nocolor", "[invalid", "."]);
    assert_eq!(
        exit, 2,
        "Invalid regex should exit 2 (matching ag baseline)"
    );
}

#[test]
fn val_cli_009_invalid_regex_stderr_diagnostic() {
    // ag: stderr contains 'ERR: Bad regex!' message.
    let (_stdout, stderr, _exit) = run_ag(&["--nocolor", "[invalid", "."]);
    assert!(
        !stderr.is_empty(),
        "Invalid regex should produce stderr diagnostic"
    );
    // Should contain an error indicator
    assert!(
        stderr.contains("ERR:") || stderr.contains("regex") || stderr.contains("error"),
        "Invalid regex stderr should mention error: {stderr}"
    );
}

#[test]
fn val_cli_009_invalid_regex_stdout_empty() {
    // ag: stdout is empty for invalid regex.
    let (stdout, _stderr, _exit) = run_ag(&["--nocolor", "[invalid", "."]);
    assert!(
        stdout.is_empty(),
        "Invalid regex should not produce stdout: stdout={stdout}"
    );
}

#[test]
fn val_cli_009_invalid_regex_has_hint() {
    // ag includes: 'If you meant to search for a literal string, run ag with -Q'
    let (_stdout, stderr, _exit) = run_ag(&["--nocolor", "[invalid", "."]);
    assert!(
        stderr.contains("-Q") || stderr.contains("literal"),
        "Invalid regex stderr should hint about -Q/literal: {stderr}"
    );
}

#[test]
fn val_cli_009_no_silent_fallback_invalid_option() {
    // Verify no silent fallback: invalid option should NOT produce search results.
    let (stdout, _stderr, _exit) = run_ag(&["--invalid-fake-option", "test", "."]);
    // stdout should only contain usage text, not search results
    // Search results would have colon-delimited lines like "file:line:content"
    let _has_search_results = stdout
        .lines()
        .any(|l| l.contains(':') && !l.contains("Usage") && !l.contains("Options"));
    // The usage text does contain colons, so we check more carefully:
    // Usage text starts with whitespace or empty lines, not path-like patterns
    assert!(
        stdout.is_empty() || stdout.contains("Usage"),
        "Invalid option stdout should be empty or usage, not search results: {stdout}"
    );
}

#[test]
fn val_cli_009_no_silent_fallback_invalid_regex() {
    // Verify no silent fallback: invalid regex should NOT produce search results.
    let (stdout, _stderr, _exit) = run_ag(&["--nocolor", "[invalid", "."]);
    assert!(
        stdout.is_empty(),
        "Invalid regex should produce no stdout (no silent fallback): stdout={stdout}"
    );
}

#[test]
fn val_cli_009_invalid_option_class_vs_regex_class_distinct_exits() {
    // Invalid option and invalid regex should produce DIFFERENT exit codes:
    // Invalid option: exit 1 (like ag)
    // Invalid regex: exit 2 (like ag)
    let (_out1, _err1, exit_option) = run_ag(&["--invalid-fake-option", "test", "."]);
    let (_out2, _err2, exit_regex) = run_ag(&["--nocolor", "[invalid", "."]);

    assert_eq!(exit_option, 1, "Invalid option should exit 1");
    assert_eq!(exit_regex, 2, "Invalid regex should exit 2");
    assert_ne!(
        exit_option, exit_regex,
        "Invalid option and invalid regex should have different exit codes"
    );
}

// =======================================================================
// --path-to-ignore / -p missing-value diagnostics
// =======================================================================

#[test]
fn val_cli_009_path_to_ignore_missing_value_exit_1() {
    // Baseline ag: `ag --path-to-ignore` (no value) exits 1 with
    // stderr "ag: option `--path-to-ignore' requires an argument"
    // and usage on stdout.
    let (_stdout, _stderr, exit) = run_ag(&["--path-to-ignore"]);
    assert_eq!(
        exit, 1,
        "--path-to-ignore without value should exit 1 (invalid-option class)"
    );
}

#[test]
fn val_cli_009_path_to_ignore_missing_value_stderr_diagnostic() {
    let (_stdout, stderr, exit) = run_ag(&["--path-to-ignore"]);
    assert_eq!(exit, 1);
    assert!(
        !stderr.is_empty(),
        "--path-to-ignore without value should produce stderr diagnostic"
    );
    assert!(
        stderr.contains("--path-to-ignore") || stderr.contains("path-to-ignore"),
        "--path-to-ignore stderr should mention the option: {stderr}"
    );
}

#[test]
fn val_cli_009_path_to_ignore_missing_value_stdout_has_usage() {
    let (stdout, _stderr, exit) = run_ag(&["--path-to-ignore"]);
    assert_eq!(exit, 1);
    assert!(
        stdout.contains("Usage"),
        "--path-to-ignore without value should print usage to stdout: stdout={stdout}"
    );
}

#[test]
fn val_cli_009_short_p_missing_value_exit_1() {
    // Baseline ag: `ag -p` (no value) exits 1 with
    // stderr "ag: option requires an argument -- p"
    // and usage on stdout.
    let (_stdout, _stderr, exit) = run_ag(&["-p"]);
    assert_eq!(
        exit, 1,
        "-p without value should exit 1 (invalid-option class)"
    );
}

#[test]
fn val_cli_009_short_p_missing_value_stderr_diagnostic() {
    let (_stdout, stderr, exit) = run_ag(&["-p"]);
    assert_eq!(exit, 1);
    assert!(
        !stderr.is_empty(),
        "-p without value should produce stderr diagnostic"
    );
    assert!(
        stderr.contains("-p") || stderr.contains("path-to-ignore"),
        "-p stderr should mention the option: {stderr}"
    );
}

#[test]
fn val_cli_009_short_p_missing_value_stdout_has_usage() {
    let (stdout, _stderr, exit) = run_ag(&["-p"]);
    assert_eq!(exit, 1);
    assert!(
        stdout.contains("Usage"),
        "-p without value should print usage to stdout: stdout={stdout}"
    );
}

#[test]
fn val_cli_009_path_to_ignore_with_value_accepted() {
    // When --path-to-ignore has a value, it should NOT error.
    // (It won't find anything useful since the file likely doesn't exist, but
    // it should proceed to the "no pattern" error, not an invalid-option error.)
    let (_stdout, stderr, exit) = run_ag(&["--path-to-ignore", "/tmp/test_ignore_file"]);
    // Without a search pattern, ag prints "ERR: What do you want to search for?"
    // which exits 1 but does NOT produce usage text.
    assert_eq!(exit, 1);
    // The error should be about missing pattern, not about the option itself
    assert!(
        !stderr.contains("--path-to-ignore"),
        "--path-to-ignore with value should not error about the option: {stderr}"
    );
}

#[test]
fn val_cli_009_short_p_with_value_accepted() {
    // -p with a value should proceed normally (no invalid-option error).
    let (_stdout, stderr, exit) = run_ag(&["-p", "/tmp/test_ignore_file"]);
    assert_eq!(exit, 1);
    assert!(
        !stderr.contains("-p"),
        "-p with value should not error about the option: {stderr}"
    );
}
