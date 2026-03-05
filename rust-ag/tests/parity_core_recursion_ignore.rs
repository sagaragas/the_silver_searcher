//! Parity tests for core recursion and ignore behavior.
//!
//! Covers validation contract assertions:
//! - VAL-CORE-001: Recursive discovery finds nested matches
//! - VAL-CORE-002: Default ignore stack is respected
//! - VAL-CORE-003: `-U` semantics match baseline
//! - VAL-CORE-004: Hidden file behavior is correct
//! - VAL-CORE-009: Recursion controls are preserved
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
    // Fall back to PATH.
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
    // Strip ANSI.
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
    #[allow(dead_code)]
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

// ---------------------------------------------------------------------------
// VAL-CORE-001: Recursive discovery finds nested matches
// ---------------------------------------------------------------------------

#[test]
fn val_core_001_recursive_discovery_ignore_source() {
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
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
fn val_core_001_recursive_discovery_hidden_files() {
    let fixture = repo_root().join("tests/edge-cases/hidden-files");
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

// ---------------------------------------------------------------------------
// VAL-CORE-002: Default ignore stack is respected
// ---------------------------------------------------------------------------

#[test]
fn val_core_002_default_ignore_stack() {
    // Default search should exclude .gitignore'd and .ignore'd files.
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
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
fn val_core_002_dot_ignore_respected() {
    // dot-ignored.txt is in .ignore → should be excluded.
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
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
        !stdout.contains("dot-ignored.txt"),
        "dot-ignored.txt should be excluded by .ignore: {stdout}"
    );
}

#[test]
fn val_core_002_gitignore_respected() {
    // git-ignored.txt is in .gitignore → should be excluded by default.
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
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
        !stdout.contains("git-ignored.txt"),
        "git-ignored.txt should be excluded by .gitignore: {stdout}"
    );
}

#[test]
fn val_core_002_git_exclude_respected() {
    // git-excluded.txt is in .git/info/exclude → should be excluded by default.
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
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
        !stdout.contains("git-excluded.txt"),
        "git-excluded.txt should be excluded by .git/info/exclude: {stdout}"
    );
}

// ---------------------------------------------------------------------------
// VAL-CORE-003: `-U` semantics match baseline
// ---------------------------------------------------------------------------

#[test]
fn val_core_003_u_flag_includes_gitignored() {
    // With -U, git-ignored files should appear but .ignore'd files should not.
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-U",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_003_u_flag_still_honors_dot_ignore() {
    // -U should still exclude dot-ignored.txt (from .ignore).
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-U",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
    let stdout = String::from_utf8_lossy(&rust.stdout);
    assert!(
        !stdout.contains("dot-ignored.txt"),
        "-U should still honor .ignore: {stdout}"
    );
    assert!(
        stdout.contains("git-ignored.txt"),
        "-U should include git-ignored files: {stdout}"
    );
    assert!(
        stdout.contains("git-excluded.txt"),
        "-U should include git-excluded files: {stdout}"
    );
}

// ---------------------------------------------------------------------------
// VAL-CORE-004: Hidden file behavior is correct
// ---------------------------------------------------------------------------

#[test]
fn val_core_004_default_hides_hidden_files() {
    let fixture = repo_root().join("tests/edge-cases/hidden-files");
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
        !stdout.contains(".hidden"),
        "Hidden files should be excluded by default: {stdout}"
    );
}

#[test]
fn val_core_004_hidden_flag_includes_hidden() {
    let fixture = repo_root().join("tests/edge-cases/hidden-files");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--hidden",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_004_hidden_parity_with_baseline() {
    let fixture = repo_root().join("tests/edge-cases/hidden-files");
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--hidden",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
    let stdout = String::from_utf8_lossy(&rust.stdout);
    assert!(
        stdout.contains(".hidden-file.txt"),
        "--hidden should include hidden files: {stdout}"
    );
    assert!(
        stdout.contains(".hidden-dir/nested.txt"),
        "--hidden should include files in hidden directories: {stdout}"
    );
}

// ---------------------------------------------------------------------------
// VAL-CORE-009: Recursion controls are preserved
// ---------------------------------------------------------------------------

#[test]
fn val_core_009_norecurse_flag() {
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-n",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_009_norecurse_excludes_subdir() {
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
    let rust = run_cmd(
        &rust_ag_bin(),
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-n",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
    let stdout = String::from_utf8_lossy(&rust.stdout);
    assert!(
        !stdout.contains("subdir/"),
        "-n should not recurse into subdirectories: {stdout}"
    );
    assert!(
        stdout.contains("visible.txt"),
        "-n should still find top-level files: {stdout}"
    );
}

#[test]
fn val_core_009_depth_zero() {
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--depth=0",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_009_depth_one() {
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "--depth=1",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_009_recurse_flag() {
    // -r should behave same as default recursive.
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
    assert_parity(
        &[
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "-r",
            "NEEDLE",
            ".",
        ],
        &fixture,
    );
}

#[test]
fn val_core_009_default_recursive() {
    // Default behavior is recursive with depth 25.
    let fixture = repo_root().join("tests/edge-cases/ignore-source");
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
        stdout.contains("subdir/sub-visible.txt"),
        "Default recursive search should find files in subdirectories: {stdout}"
    );
}
