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
fn val_core_001_recursive_discovery() {
    // VAL-CORE-001: Recursive discovery finds nested matches.
    // Full parity tests in parity_core_recursion_ignore.rs.
    let output = rust_ag_bin()
        .args(["NEEDLE", "tests/edge-cases/ignore-source"])
        .current_dir(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap(),
        )
        .output()
        .expect("failed to execute rust-ag");
    assert!(
        output.status.success(),
        "Recursive search should find matches (exit 0)"
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        stdout.contains("sub-visible.txt"),
        "Should find files in subdirectories"
    );
}

#[test]
fn val_core_002_default_ignore_stack() {
    // VAL-CORE-002: Default ignore stack is respected.
    // Full parity tests in parity_core_recursion_ignore.rs.
    let output = rust_ag_bin()
        .args(["NEEDLE", "tests/edge-cases/ignore-source"])
        .current_dir(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap(),
        )
        .output()
        .expect("failed to execute rust-ag");
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        !stdout.contains("git-ignored.txt"),
        "git-ignored files should be excluded"
    );
    assert!(
        !stdout.contains("dot-ignored.txt"),
        ".ignore'd files should be excluded"
    );
}

#[test]
fn val_core_003_u_flag_semantics() {
    // VAL-CORE-003: `-U` semantics match baseline.
    // Full parity tests in parity_core_recursion_ignore.rs.
    let output = rust_ag_bin()
        .args(["-U", "NEEDLE", "tests/edge-cases/ignore-source"])
        .current_dir(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap(),
        )
        .output()
        .expect("failed to execute rust-ag");
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        stdout.contains("git-ignored.txt"),
        "-U should include VCS-ignored files"
    );
    assert!(
        !stdout.contains("dot-ignored.txt"),
        "-U should still honor .ignore"
    );
}

#[test]
fn val_core_004_hidden_file_behavior() {
    // VAL-CORE-004: Hidden file behavior is correct.
    // Full parity tests in parity_core_recursion_ignore.rs.
    let output = rust_ag_bin()
        .args(["--hidden", "NEEDLE", "tests/edge-cases/hidden-files"])
        .current_dir(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap(),
        )
        .output()
        .expect("failed to execute rust-ag");
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        stdout.contains(".hidden-file.txt"),
        "--hidden should include hidden files"
    );
}

#[test]
fn val_core_005_case_sensitivity() {
    // VAL-CORE-005: Case-sensitivity semantics are preserved.
    // Full parity tests in parity_core_matching.rs.
    let fixture = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("tests/edge-cases/case-sensitivity");
    let output = rust_ag_bin()
        .args(["--nocolor", "--workers=1", "-i", "Hello", "."])
        .current_dir(&fixture)
        .output()
        .expect("failed to execute rust-ag");
    assert!(
        output.status.success(),
        "Case-insensitive search should find matches (exit 0)"
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        stdout.contains("hello world"),
        "Should match case-insensitively"
    );
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
