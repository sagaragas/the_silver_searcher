//! Parity test skeletons.
//!
//! These tests are stubs that will be filled in during subsequent milestones.
//! Each test corresponds to a validation contract assertion from VAL-CORE
//! and VAL-CLI areas. They currently assert placeholder conditions and are
//! marked with `#[ignore]` where search functionality is required.

use std::process::Command;

fn rust_ag_bin() -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_rust-ag"));
    cmd.env("LANG", "C");
    cmd.env("LC_ALL", "C");
    cmd
}

// ---------------------------------------------------------------------------
// VAL-CORE parity skeletons
// ---------------------------------------------------------------------------

#[test]
#[ignore = "requires search implementation (rust-search-core milestone)"]
fn val_core_001_recursive_discovery() {
    // VAL-CORE-001: Recursive discovery finds nested matches.
    let _output = rust_ag_bin()
        .args(["test_pattern", "."])
        .output()
        .expect("failed to execute rust-ag");
    // TODO: Assert matches from nested directories.
}

#[test]
#[ignore = "requires search implementation (rust-search-core milestone)"]
fn val_core_002_default_ignore_stack() {
    // VAL-CORE-002: Default ignore stack is respected.
    let _output = rust_ag_bin()
        .args(["test_pattern", "."])
        .output()
        .expect("failed to execute rust-ag");
    // TODO: Assert ignored paths are excluded.
}

#[test]
#[ignore = "requires search implementation (rust-search-core milestone)"]
fn val_core_003_u_flag_semantics() {
    // VAL-CORE-003: `-U` semantics match baseline.
    let _output = rust_ag_bin()
        .args(["-U", "test_pattern", "."])
        .output()
        .expect("failed to execute rust-ag");
    // TODO: Assert VCS ignore disabled but .ignore still honored.
}

#[test]
#[ignore = "requires search implementation (rust-search-core milestone)"]
fn val_core_004_hidden_file_behavior() {
    // VAL-CORE-004: Hidden file behavior is correct.
    let _output = rust_ag_bin()
        .args(["--hidden", "test_pattern", "."])
        .output()
        .expect("failed to execute rust-ag");
    // TODO: Assert hidden files included with --hidden.
}

#[test]
#[ignore = "requires search implementation (rust-search-core milestone)"]
fn val_core_005_case_sensitivity() {
    // VAL-CORE-005: Case-sensitivity semantics are preserved.
    let _output = rust_ag_bin()
        .args(["-i", "test_pattern", "."])
        .output()
        .expect("failed to execute rust-ag");
    // TODO: Assert case-insensitive matching with -i.
}

// ---------------------------------------------------------------------------
// VAL-CLI parity skeletons
// ---------------------------------------------------------------------------

#[test]
#[ignore = "requires CLI output implementation (rust-cli-parity milestone)"]
fn val_cli_001_count_mode() {
    // VAL-CLI-001: --count reports match counts correctly.
    let _output = rust_ag_bin()
        .args(["--count", "test_pattern", "."])
        .output()
        .expect("failed to execute rust-ag");
    // TODO: Assert match count output format.
}

#[test]
#[ignore = "requires CLI output implementation (rust-cli-parity milestone)"]
fn val_cli_004_context_flags() {
    // VAL-CLI-004: Context flags produce expected format.
    let _output = rust_ag_bin()
        .args(["-C", "2", "test_pattern", "."])
        .output()
        .expect("failed to execute rust-ag");
    // TODO: Assert context line output format.
}

#[test]
#[ignore = "requires CLI output implementation (rust-cli-parity milestone)"]
fn val_cli_007_help_and_version() {
    // VAL-CLI-007: Help and version interfaces are stable.
    // (Non-ignored part tested in cli_smoke.rs)
    let _output = rust_ag_bin()
        .arg("--version")
        .output()
        .expect("failed to execute rust-ag");
    // TODO: Assert structured version output contract.
}

#[test]
#[ignore = "requires CLI output implementation (rust-cli-parity milestone)"]
fn val_cli_008_exit_code_semantics() {
    // VAL-CLI-008: Exit-code and error semantics are preserved.
    let _output = rust_ag_bin()
        .args(["test_pattern", "/nonexistent/path"])
        .output()
        .expect("failed to execute rust-ag");
    // TODO: Assert error exit code for nonexistent path.
}
