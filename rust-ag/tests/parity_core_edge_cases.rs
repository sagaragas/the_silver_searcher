//! Parity tests for core edge-case behavior.
//!
//! Covers validation contract assertions:
//! - VAL-CORE-007: Binary file handling is preserved
//! - VAL-CORE-008: Symlink/device traversal rules are preserved
//! - VAL-CORE-011: Large-file behavior matches baseline limits
//! - VAL-CORE-014: Match-cap behavior is preserved
//!
//! Each test runs both `ag` (baseline) and `rust-ag` on the same fixture
//! directory and compares normalised output (sorted lines, stripped ANSI).

use std::path::{Path, PathBuf};
use std::process::Command;

/// Locate the repo root (parent of `rust-ag/`).
fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("rust-ag should be inside repo root")
        .to_path_buf()
}

/// Locate the baseline `ag` binary.
fn ag_bin() -> PathBuf {
    let root = repo_root();
    let local = root.join("ag");
    if local.is_file() {
        return local;
    }
    PathBuf::from("ag")
}

/// Locate the rust-ag binary built by cargo.
fn rust_ag_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_rust-ag"))
}

/// Normalise output for comparison:
/// - Strip ANSI escape codes.
/// - Trim trailing whitespace per line.
/// - Drop empty lines.
/// - Sort lines.
fn normalise(raw: &[u8]) -> String {
    let text = String::from_utf8_lossy(raw);
    let ansi_re = regex::Regex::new(r"\x1b\[[0-9;]*m").unwrap();
    let text = ansi_re.replace_all(&text, "");

    let mut lines: Vec<&str> = text
        .lines()
        .map(|l| l.trim_end())
        .filter(|l| !l.is_empty())
        .collect();
    lines.sort();
    lines.join("\n")
}

/// Run a command and capture stdout, stderr, and exit code.
struct RunResult {
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    exit_code: i32,
}

fn run_cmd(bin: &Path, args: &[&str], cwd: &Path) -> RunResult {
    let output = Command::new(bin)
        .args(args)
        .current_dir(cwd)
        .env("LANG", "C")
        .env("LC_ALL", "C")
        .env("NO_COLOR", "1")
        .env("TERM", "dumb")
        .output()
        .unwrap_or_else(|e| panic!("Failed to run {}: {e}", bin.display()));
    RunResult {
        stdout: output.stdout,
        stderr: output.stderr,
        exit_code: output.status.code().unwrap_or(-1),
    }
}

/// Compare baseline ag and rust-ag on the same command, asserting output parity.
fn assert_parity(args: &[&str], cwd: &Path) {
    let ag = run_cmd(&ag_bin(), args, cwd);
    let rust = run_cmd(&rust_ag_bin(), args, cwd);

    let ag_out = normalise(&ag.stdout);
    let rust_out = normalise(&rust.stdout);

    assert_eq!(
        ag.exit_code, rust.exit_code,
        "Exit code mismatch for args {:?}\nag exit={}, rust-ag exit={}\nag stdout:\n{}\nrust-ag stdout:\n{}",
        args, ag.exit_code, rust.exit_code, ag_out, rust_out
    );

    assert_eq!(
        ag_out, rust_out,
        "Output mismatch for args {:?}\nag output:\n{}\nrust-ag output:\n{}",
        args, ag_out, rust_out
    );
}

/// Compare baseline ag and rust-ag including stderr output.
fn assert_parity_with_stderr(args: &[&str], cwd: &Path) {
    let ag = run_cmd(&ag_bin(), args, cwd);
    let rust = run_cmd(&rust_ag_bin(), args, cwd);

    let ag_out = normalise(&ag.stdout);
    let rust_out = normalise(&rust.stdout);

    let ag_err = normalise(&ag.stderr);
    let rust_err = normalise(&rust.stderr);

    assert_eq!(
        ag.exit_code, rust.exit_code,
        "Exit code mismatch for args {:?}\nag exit={}, rust-ag exit={}",
        args, ag.exit_code, rust.exit_code
    );

    assert_eq!(
        ag_out, rust_out,
        "Stdout mismatch for args {:?}\nag stdout:\n{}\nrust-ag stdout:\n{}",
        args, ag_out, rust_out
    );

    assert_eq!(
        ag_err, rust_err,
        "Stderr mismatch for args {:?}\nag stderr:\n{}\nrust-ag stderr:\n{}",
        args, ag_err, rust_err
    );
}

// ---------------------------------------------------------------------------
// VAL-CORE-007: Binary file handling is preserved
// ---------------------------------------------------------------------------

#[test]
fn val_core_007_binary_files_skipped_by_default() {
    // By default, binary files should be skipped.
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_007_binary_default_only_text() {
    // Default mode should only show text-file.txt.
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
    let stdout = String::from_utf8_lossy(&rust.stdout);
    assert!(
        stdout.contains("text-file.txt"),
        "Default mode should include text files: {stdout}"
    );
    assert!(
        !stdout.contains("binary-file.bin"),
        "Default mode should skip binary files: {stdout}"
    );
    assert!(
        !stdout.contains("mixed-binary.dat"),
        "Default mode should skip mixed-binary files: {stdout}"
    );
}

#[test]
fn val_core_007_search_binary_shows_binary_message() {
    // --search-binary should print "Binary file X matches." for binary files.
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--search-binary",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_007_search_binary_format() {
    // Verify "Binary file X matches." output format.
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--search-binary",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
    let stdout = String::from_utf8_lossy(&rust.stdout);
    assert!(
        stdout.contains("Binary file"),
        "Should contain 'Binary file' message: {stdout}"
    );
    assert!(
        stdout.contains("matches."),
        "Should contain 'matches.' suffix: {stdout}"
    );
}

#[test]
fn val_core_007_unrestricted_binary_behavior() {
    // -u (unrestricted) should also show binary file messages.
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-u",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

// ---------------------------------------------------------------------------
// VAL-CORE-007: Short-buffer binary detection parity
// Short (<32 byte) files with >10% suspicious bytes must be classified
// as binary, matching baseline ag's ratio check that applies to all
// buffer lengths (not only buffers >= 32 bytes).
// ---------------------------------------------------------------------------

#[test]
fn val_core_007_short_binary_skipped_by_default() {
    // short-binary.dat is 15 bytes with 20% suspicious bytes.
    // Baseline ag classifies it as binary and skips it in default mode.
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    let ag = run_cmd(
        &ag_bin(),
        &["--nocolor", "NEEDLE", "short-binary.dat"],
        &fixture,
    );
    let rust = run_cmd(
        &rust_ag_bin(),
        &["--nocolor", "NEEDLE", "short-binary.dat"],
        &fixture,
    );
    // ag skips this file (exit 1, no output).
    assert_eq!(ag.exit_code, 1, "ag should skip short-binary.dat");
    assert_eq!(
        rust.exit_code, ag.exit_code,
        "rust-ag should skip short-binary.dat like ag (exit {}), got exit {}",
        ag.exit_code, rust.exit_code
    );
    assert_eq!(
        normalise(&rust.stdout),
        normalise(&ag.stdout),
        "stdout mismatch on short-binary.dat"
    );
}

#[test]
fn val_core_007_short_binary_excluded_from_directory_results() {
    // When searching the binary-files directory, short-binary.dat should
    // be excluded from default results just like other binary files.
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
    let stdout = String::from_utf8_lossy(&rust.stdout);
    assert!(
        !stdout.contains("short-binary.dat"),
        "Default mode should skip short-binary.dat: {stdout}"
    );
}

#[test]
fn val_core_007_short_binary_search_binary_message() {
    // --search-binary on short-binary.dat should emit "Binary file X matches."
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--search-binary",
            "NEEDLE",
            "short-binary.dat",
        ],
        &fixture,
    );
}

#[test]
fn val_core_007_short_binary_files_with_matches_excluded() {
    // --files-with-matches on the directory should not list short-binary.dat
    // because it is binary and default mode skips binary files.
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-l",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

// ---------------------------------------------------------------------------
// VAL-CORE-008: Symlink/device traversal rules are preserved
// ---------------------------------------------------------------------------

#[test]
fn val_core_008_symlink_default_no_follow_dirs() {
    // Default: symlink directories should NOT be followed.
    let fixture = repo_root().join("tests/edge-cases/symlink-traversal");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_008_symlink_follow_dirs() {
    // -f: symlink directories should be followed.
    let fixture = repo_root().join("tests/edge-cases/symlink-traversal");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-f",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_008_symlink_follow_includes_linked_dir_content() {
    // -f should include files from symlinked directories.
    let fixture = repo_root().join("tests/edge-cases/symlink-traversal");
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-f",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
    let stdout = String::from_utf8_lossy(&rust.stdout);
    assert!(
        stdout.contains("link-to-dir/real-file.txt"),
        "-f should include symlinked directory content: {stdout}"
    );
    assert!(
        stdout.contains("link-to-file"),
        "-f should include symlinked files: {stdout}"
    );
}

#[test]
fn val_core_008_broken_symlink_error() {
    // Broken symlinks should produce an error message when -f is used.
    let fixture = repo_root().join("tests/edge-cases/symlink-traversal");
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-f",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
    let stderr = String::from_utf8_lossy(&rust.stderr);
    assert!(
        stderr.contains("broken-link") && stderr.contains("ERR"),
        "Broken symlink should produce error on stderr: {stderr}"
    );
}

#[test]
fn val_core_008_one_device_basic() {
    // --one-device should work without errors on the one-device fixture.
    // On macOS, cross-device boundary is not available, so this primarily
    // tests that --one-device doesn't break normal same-device traversal.
    let fixture = repo_root().join("tests/edge-cases/one-device");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--one-device",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_008_one_device_platform_marker() {
    // Verify the platform metadata accurately reflects one-device availability.
    let meta_path = repo_root().join("tests/edge-cases/platform_metadata.json");
    let content = std::fs::read_to_string(&meta_path).expect("platform_metadata.json should exist");
    let meta: serde_json::Value =
        serde_json::from_str(&content).expect("platform_metadata.json should be valid JSON");
    let one_device = &meta["fixture_applicability"]["one-device"];
    // On macOS, one-device cross-device is not supported.
    if cfg!(target_os = "macos") {
        assert_eq!(
            one_device["supported"].as_bool(),
            Some(false),
            "one-device should not be supported on macOS: {one_device}"
        );
    }
}

// ---------------------------------------------------------------------------
// VAL-CORE-011: Large-file behavior matches baseline limits
// ---------------------------------------------------------------------------

#[test]
fn val_core_011_large_file_search() {
    // Large file should be searched and produce matching output.
    let fixture = repo_root().join("tests/edge-cases/large-file");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_011_large_file_match_positions() {
    // Verify matches at specific line positions in the large file.
    let fixture = repo_root().join("tests/edge-cases/large-file");
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
    let stdout = String::from_utf8_lossy(&rust.stdout);
    // large.txt has NEEDLE at lines 1, 10001, 20001, 30001.
    assert!(
        stdout.contains("large.txt:1:"),
        "Should find match at line 1: {stdout}"
    );
    assert!(
        stdout.contains("large.txt:10001:"),
        "Should find match at line 10001: {stdout}"
    );
    assert!(
        stdout.contains("large.txt:20001:"),
        "Should find match at line 20001: {stdout}"
    );
    assert!(
        stdout.contains("large.txt:30001:"),
        "Should find match at line 30001: {stdout}"
    );
}

#[test]
fn val_core_011_large_file_literal_search() {
    // Literal search on large file should match baseline.
    let fixture = repo_root().join("tests/edge-cases/large-file");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-Q",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

// ---------------------------------------------------------------------------
// VAL-CORE-014: Match-cap behavior is preserved
// ---------------------------------------------------------------------------

#[test]
fn val_core_014_max_count_truncation() {
    // --max-count=3 should limit output to 3 matches per file.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--max-count=3",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_diagnostic() {
    // --max-count should produce "Too many matches" diagnostic on stderr.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--max-count=3",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_exact_boundary() {
    // When matches == max-count, ag still emits the diagnostic.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    let ag = run_cmd(
        &ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--max-count=3",
            "NEEDLE",
            "few-matches.txt",
        ],
        &fixture,
    );
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--max-count=3",
            "NEEDLE",
            "few-matches.txt",
        ],
        &fixture,
    );
    // Both should emit the diagnostic for exactly 3 matches with --max-count=3.
    let ag_err = String::from_utf8_lossy(&ag.stderr);
    let rust_err = String::from_utf8_lossy(&rust.stderr);
    assert!(
        ag_err.contains("Too many matches"),
        "ag should emit diagnostic: {ag_err}"
    );
    assert!(
        rust_err.contains("Too many matches"),
        "rust-ag should emit diagnostic: {rust_err}"
    );
}

#[test]
fn val_core_014_max_count_below_total_no_diagnostic() {
    // When max-count is well above actual matches, no diagnostic should appear.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--max-count=100",
            "NEEDLE",
            "few-matches.txt",
        ],
        &fixture,
    );
    let stderr = String::from_utf8_lossy(&rust.stderr);
    assert!(
        !stderr.contains("Too many matches"),
        "No diagnostic when matches < max-count: {stderr}"
    );
}

#[test]
fn val_core_014_max_count_m_flag() {
    // -m shorthand should work identically to --max-count.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-m3",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_literal() {
    // --max-count with literal search should match baseline.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--max-count=2",
            "-Q",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

// ---------------------------------------------------------------------------
// Binary-enabled mode with -c/-l: should honor count/list semantics
// (not print "Binary file X matches." when -c or -l is used)
// ---------------------------------------------------------------------------

#[test]
fn val_core_007_search_binary_with_count() {
    // --search-binary -c should print path:count for binary files, not "Binary file X matches."
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--search-binary",
            "-c",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_007_search_binary_with_files_with_matches() {
    // --search-binary -l should print filenames only for binary files, not "Binary file X matches."
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--search-binary",
            "-l",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_007_unrestricted_with_count() {
    // -u -c should print path:count for binary files.
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-u",
            "-c",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_007_unrestricted_with_files_with_matches() {
    // -u -l should print filenames only for binary files.
    let fixture = repo_root().join("tests/edge-cases/binary-files");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-u",
            "-l",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

// ---------------------------------------------------------------------------
// Max-count diagnostics under invert-match (-v)
// ag's max-count diagnostic is based on positive match count, not inverted count
// ---------------------------------------------------------------------------

#[test]
fn val_core_014_max_count_invert_diagnostic_few_matches() {
    // --max-count=3 -v on few-matches.txt: ag emits "Too many matches"
    // because 3 positive NEEDLE matches reach the cap.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--max-count=3",
            "-v",
            "NEEDLE",
            "few-matches.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_invert_many_matches() {
    // --max-count=3 -v on many-matches.txt: ag emits diagnostic and
    // outputs lines after the max-count cutoff as inverted output.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--max-count=3",
            "-v",
            "NEEDLE",
            "many-matches.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_invert_mixed() {
    // --max-count=3 -v on mixed.txt: ag emits diagnostic and shows
    // non-matched lines before cutoff plus all lines after cutoff.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--max-count=3",
            "-v",
            "NEEDLE",
            "mixed.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_invert_directory() {
    // --max-count=3 -v on the whole max-count directory.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--max-count=3",
            "-v",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

// ---------------------------------------------------------------------------
// VAL-CORE-014: --max-count=0 means "no limit" (ag treats 0 as unlimited)
// ---------------------------------------------------------------------------

#[test]
fn val_core_014_max_count_zero_invert_nomultiline_high_match_all_match() {
    // --nomultiline -m0 -v on a 12050-line all-match file.
    // ag treats -m0 as truly unlimited: scans all 12050 positive matches,
    // inverts to 0 output lines, exit 1, no stderr diagnostic.
    // This catches the bug where -m0 was capped at 10000 (DEFAULT_MAX_COUNT),
    // causing 2050 spurious inverted lines + "Too many matches" diagnostic.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--nomultiline",
            "-m0",
            "-v",
            "NEEDLE",
            "all-match-12050.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_zero_nomultiline_high_match_positive() {
    // --nomultiline -m0 on a 12050-line all-match file (no -v).
    // ag outputs all 12050 lines with no diagnostic.
    // This catches the bug where -m0 was capped at 10000, truncating
    // output to 10000 lines + emitting a spurious "Too many matches".
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--nomultiline",
            "-m0",
            "NEEDLE",
            "all-match-12050.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_zero_multiline_high_match_positive() {
    // Multiline mode -m0 on a 12050-line all-match file (no -v).
    // ag outputs all 12050 lines with no diagnostic.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-m0",
            "NEEDLE",
            "all-match-12050.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_zero_multiline_high_match_invert() {
    // Multiline mode -m0 -v on a 12050-line all-match file.
    // ag outputs 0 lines, exit 1, no diagnostic.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-m0",
            "-v",
            "NEEDLE",
            "all-match-12050.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_zero_nomultiline_positive() {
    // --nomultiline -m0 without -v: ag treats 0 as unlimited, all matches shown.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--nomultiline",
            "-m0",
            "NEEDLE",
            "few-matches.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_zero_invert_nomultiline() {
    // --nomultiline -m0 -v: ag treats 0 as unlimited, inverted matches shown.
    // Must not panic (underflow) and must match ag output/exit behavior.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--nomultiline",
            "-m0",
            "-v",
            "NEEDLE",
            "few-matches.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_zero_invert_nomultiline_all_match() {
    // --nomultiline -m0 -v on a file where all lines match: no inverted output.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--nomultiline",
            "-m0",
            "-v",
            "NEEDLE",
            "many-matches.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_zero_multiline_positive() {
    // Multiline mode -m0 without -v: all matches shown.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-m0",
            "NEEDLE",
            "few-matches.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_zero_multiline_invert() {
    // Multiline mode -m0 -v: inverted matches shown.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-m0",
            "-v",
            "NEEDLE",
            "few-matches.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_zero_long_flag() {
    // --max-count=0 long form: same as -m0.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--nomultiline",
            "--max-count=0",
            "-v",
            "NEEDLE",
            "few-matches.txt",
        ],
        &fixture,
    );
}

#[test]
fn val_core_014_max_count_zero_directory() {
    // -m0 on directory: unlimited matches, no spurious diagnostics.
    let fixture = repo_root().join("tests/edge-cases/max-count");
    assert_parity_with_stderr(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-m0",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}
