//! Smoke tests for the rust-ag CLI binary.
//!
//! These tests verify the binary builds, runs, and handles basic
//! CLI interactions correctly. Behavioral parity tests will be added
//! in subsequent milestones (rust-search-core, rust-cli-parity).

use std::process::Command;

fn rust_ag_bin() -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_rust-ag"));
    // Force consistent locale for test determinism.
    cmd.env("LANG", "C");
    cmd.env("LC_ALL", "C");
    cmd
}

#[test]
fn version_flag_exits_zero() {
    let output = rust_ag_bin()
        .arg("--version")
        .output()
        .expect("failed to execute rust-ag");

    assert!(
        output.status.success(),
        "Expected exit code 0 for --version, got {:?}",
        output.status.code()
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        stdout.contains("rust-ag"),
        "Expected version output to contain 'rust-ag', got: {stdout}"
    );
}

#[test]
fn help_flag_exits_zero() {
    let output = rust_ag_bin()
        .arg("--help")
        .output()
        .expect("failed to execute rust-ag");

    assert!(
        output.status.success(),
        "Expected exit code 0 for --help, got {:?}",
        output.status.code()
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        stdout.contains("Usage:"),
        "Expected help output to contain 'Usage:', got: {stdout}"
    );
}

#[test]
fn no_args_exits_with_error() {
    let output = rust_ag_bin().output().expect("failed to execute rust-ag");

    assert_eq!(
        output.status.code(),
        Some(2),
        "Expected exit code 2 when no arguments given"
    );
}

#[test]
fn placeholder_search_exits_one() {
    // Placeholder behavior: any search pattern exits with 1 (no match).
    // This will change once search is implemented.
    let output = rust_ag_bin()
        .arg("test_pattern")
        .arg(".")
        .output()
        .expect("failed to execute rust-ag");

    assert_eq!(
        output.status.code(),
        Some(1),
        "Expected exit code 1 for placeholder search"
    );
}

#[test]
fn accepts_ag_compatible_flags_without_crashing() {
    // The binary should accept common ag flags without crashing,
    // even though search is not yet implemented.
    let output = rust_ag_bin()
        .args([
            "--nocolor",
            "--workers=1",
            "--parallel",
            "--noaffinity",
            "pattern",
            ".",
        ])
        .output()
        .expect("failed to execute rust-ag");

    // Should not crash (exit 2 = error); 1 = no match is fine for placeholder.
    let code = output.status.code().unwrap_or(-1);
    assert!(
        code == 0 || code == 1,
        "Expected exit code 0 or 1 with valid flags, got {code}"
    );
}
