/// Parity tests for CLI count semantics, filename prefix behavior,
/// and stream (stdin) numbering conventions.
///
/// Covers:
///   VAL-CLI-001: --count reports match counts correctly
///   VAL-CLI-002: Filename prefix semantics match baseline
///   VAL-CLI-003: --nofilename and stream numbering semantics
use std::io::Write;
use std::process::{Command, Stdio};

/// Path to the rust-ag binary built by cargo.
fn rust_ag_bin() -> std::path::PathBuf {
    let mut path = std::path::PathBuf::from(env!("CARGO_BIN_EXE_rust-ag"));
    // Fallback for test environments.
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
    // Drop stdin to signal EOF.
    drop(child.stdin.take());

    let out = child.wait_with_output().expect("failed to wait on rust-ag");
    (
        String::from_utf8_lossy(&out.stdout).to_string(),
        String::from_utf8_lossy(&out.stderr).to_string(),
        out.status.code().unwrap_or(-1),
    )
}

/// Create a temporary directory with test fixtures.
fn setup_fixture() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let base = dir.path();

    // file1.txt: "hello world\nhello there\ngoodbye\n"
    std::fs::write(
        base.join("file1.txt"),
        "hello world\nhello there\ngoodbye\n",
    )
    .unwrap();

    // sub/file2.txt: "hello foo\nhello bar\n"
    std::fs::create_dir_all(base.join("sub")).unwrap();
    std::fs::write(base.join("sub").join("file2.txt"), "hello foo\nhello bar\n").unwrap();

    // multi_match.txt: "hello hello hello\n"
    std::fs::write(base.join("multi_match.txt"), "hello hello hello\n").unwrap();

    dir
}

// ============================================================
// VAL-CLI-001: --count reports match counts correctly
// ============================================================

#[test]
fn val_cli_001_count_single_file() {
    let dir = setup_fixture();
    let f = dir.path().join("file1.txt");
    let (stdout, _stderr, exit) = run_ag(&["-c", "hello", f.to_str().unwrap()]);
    // ag -c on single file: total match occurrences, no filename prefix
    assert_eq!(stdout.trim(), "2", "single-file count should be 2 matches");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_001_count_multi_file() {
    let dir = setup_fixture();
    let (stdout, _stderr, exit) = run_ag(&["-c", "hello", dir.path().to_str().unwrap()]);
    // ag -c on multi-file: "filename:count" per file with matches, sorted
    let mut lines: Vec<&str> = stdout.trim().lines().collect();
    lines.sort();
    // Expect 3 files: file1.txt:2, multi_match.txt:3, sub/file2.txt:2
    assert_eq!(lines.len(), 3, "should have 3 files with matches");
    // Check each line has filename:count format
    for line in &lines {
        assert!(
            line.contains(':'),
            "multi-file count line should have filename:count format: {line}"
        );
    }
    // Verify match counts (not line counts)
    let counts: Vec<&str> = lines
        .iter()
        .map(|l| l.rsplit(':').next().unwrap())
        .collect();
    assert!(counts.contains(&"2"), "file1.txt should have 2 matches");
    assert!(
        counts.contains(&"3"),
        "multi_match.txt should have 3 matches"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_001_count_matches_not_lines() {
    // "hello hello hello" has 3 regex match occurrences on 1 line.
    let dir = setup_fixture();
    let f = dir.path().join("multi_match.txt");
    let (stdout, _stderr, exit) = run_ag(&["-c", "hello", f.to_str().unwrap()]);
    assert_eq!(
        stdout.trim(),
        "3",
        "--count should report regex match occurrences (3), not lines (1)"
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_001_count_no_matches() {
    let dir = setup_fixture();
    let (stdout, _stderr, exit) = run_ag(&["-c", "zzzznotfound", dir.path().to_str().unwrap()]);
    assert_eq!(stdout.trim(), "", "no matches should produce empty output");
    assert_eq!(exit, 1, "no matches should exit 1");
}

#[test]
fn val_cli_001_count_invert_single_file() {
    let dir = setup_fixture();
    let f = dir.path().join("file1.txt");
    let (stdout, _stderr, exit) = run_ag(&["-c", "-v", "hello", f.to_str().unwrap()]);
    // file1.txt has 3 lines, 2 match "hello", so invert = 1 non-matching line
    assert_eq!(stdout.trim(), "1", "inverted count should be 1");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_001_count_nofilename_multi_file() {
    let dir = setup_fixture();
    let (stdout, _stderr, exit) =
        run_ag(&["--nofilename", "-c", "hello", dir.path().to_str().unwrap()]);
    // --nofilename + -c: just counts, no filenames
    let mut counts: Vec<&str> = stdout.trim().lines().collect();
    counts.sort();
    assert_eq!(counts.len(), 3, "should have 3 count lines");
    // All should be pure numbers
    for c in &counts {
        assert!(
            c.parse::<usize>().is_ok(),
            "nofilename count should be pure number: {c}"
        );
    }
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_001_count_stream_per_line() {
    // In stream mode, ag -c prints the match count for each matching line
    let (stdout, _stderr, exit) = run_ag_stdin(&["-c", "hello"], "hello hello\nworld\nhello\n");
    // Line 1 has 2 matches, line 3 has 1 match
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 2, "stream -c should produce 2 lines");
    assert_eq!(lines[0], "2", "line 1 should have 2 matches");
    assert_eq!(lines[1], "1", "line 3 should have 1 match");
    assert_eq!(exit, 0);
}

// ============================================================
// VAL-CLI-002: Filename prefix semantics match baseline
// ============================================================

#[test]
fn val_cli_002_single_file_no_prefix() {
    let dir = setup_fixture();
    let f = dir.path().join("file1.txt");
    let (stdout, _stderr, exit) = run_ag(&["hello", f.to_str().unwrap()]);
    // Single file: no filename prefix, just "line_number:content"
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 2);
    assert_eq!(lines[0], "1:hello world");
    assert_eq!(lines[1], "2:hello there");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_002_multi_file_has_prefix() {
    let dir = setup_fixture();
    let (stdout, _stderr, exit) = run_ag(&["hello", dir.path().to_str().unwrap()]);
    // Multi-file: "filename:line_number:content"
    for line in stdout.trim().lines() {
        let parts: Vec<&str> = line.splitn(3, ':').collect();
        assert!(
            parts.len() >= 3,
            "multi-file line should have filename:lineno:content format: {line}"
        );
    }
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_002_nofilename_single_file() {
    let dir = setup_fixture();
    let f = dir.path().join("file1.txt");
    let (stdout, _stderr, exit) = run_ag(&["--nofilename", "hello", f.to_str().unwrap()]);
    // --nofilename on single file: no filename, no line numbers
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 2);
    assert_eq!(lines[0], "hello world");
    assert_eq!(lines[1], "hello there");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_002_nofilename_multi_file() {
    let dir = setup_fixture();
    let (stdout, _stderr, exit) = run_ag(&["--nofilename", "hello", dir.path().to_str().unwrap()]);
    // --nofilename on multi-file: no filename prefix, no line numbers
    // Blank line separators between files
    for line in stdout.lines() {
        if !line.is_empty() {
            // No colon prefix (no "filename:" or "lineno:")
            assert!(
                !line.starts_with('/') || !line.contains(':'),
                "nofilename should not have filename prefix: {line}"
            );
        }
    }
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_002_nonumbers_single_file() {
    let dir = setup_fixture();
    let f = dir.path().join("file1.txt");
    let (stdout, _stderr, exit) = run_ag(&["--nonumbers", "hello", f.to_str().unwrap()]);
    // --nonumbers on single file: no line numbers
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 2);
    assert_eq!(lines[0], "hello world");
    assert_eq!(lines[1], "hello there");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_002_nonumbers_multi_file() {
    let dir = setup_fixture();
    let (stdout, _stderr, exit) = run_ag(&["--nonumbers", "hello", dir.path().to_str().unwrap()]);
    // --nonumbers on multi-file: filename prefix but no line numbers
    // Format: "filename:content" (2 parts, not 3)
    for line in stdout.trim().lines() {
        let parts: Vec<&str> = line.splitn(3, ':').collect();
        assert!(
            parts.len() == 2,
            "nonumbers multi-file should have filename:content (2 parts): {line}"
        );
    }
    assert_eq!(exit, 0);
}

// ============================================================
// VAL-CLI-003: --nofilename and stream numbering semantics
// ============================================================

#[test]
fn val_cli_003_stream_default_no_numbers() {
    // Stream mode default: no filename, no line numbers
    let (stdout, _stderr, exit) = run_ag_stdin(&["hello"], "hello world\nhello there\ngoodbye\n");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 2);
    assert_eq!(lines[0], "hello world");
    assert_eq!(lines[1], "hello there");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_003_stream_with_numbers() {
    // Stream + --numbers: adds line numbers
    let (stdout, _stderr, exit) = run_ag_stdin(
        &["--numbers", "hello"],
        "hello world\nhello there\ngoodbye\n",
    );
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 2);
    assert_eq!(lines[0], "1:hello world");
    assert_eq!(lines[1], "2:hello there");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_003_stream_with_nonumbers() {
    // Stream + --nonumbers: no line numbers (same as default)
    let (stdout, _stderr, exit) = run_ag_stdin(
        &["--nonumbers", "hello"],
        "hello world\nhello there\ngoodbye\n",
    );
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 2);
    assert_eq!(lines[0], "hello world");
    assert_eq!(lines[1], "hello there");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_003_stream_no_matches() {
    let (stdout, _stderr, exit) = run_ag_stdin(&["zzzznotfound"], "hello world\ngoodbye\n");
    assert_eq!(stdout.trim(), "");
    assert_eq!(exit, 1);
}

#[test]
fn val_cli_003_stream_count() {
    // Stream + -c: per-line match counts
    let (stdout, _stderr, exit) = run_ag_stdin(&["-c", "hello"], "hello hello\nworld\nhello\n");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 2);
    assert_eq!(lines[0], "2");
    assert_eq!(lines[1], "1");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_003_nofilename_numbers_multi_file() {
    let dir = setup_fixture();
    let (stdout, _stderr, exit) = run_ag(&[
        "--nofilename",
        "--numbers",
        "hello",
        dir.path().to_str().unwrap(),
    ]);
    // --nofilename + --numbers: no filename, but line numbers present
    // Lines should be like "1:content" or blank separators
    for line in stdout.lines() {
        if !line.is_empty() {
            let parts: Vec<&str> = line.splitn(2, ':').collect();
            assert_eq!(
                parts.len(),
                2,
                "nofilename+numbers should have lineno:content: {line}"
            );
            assert!(
                parts[0].parse::<usize>().is_ok(),
                "first part should be a line number: {}",
                parts[0]
            );
        }
    }
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_003_nofilename_nonumbers_multi_file() {
    let dir = setup_fixture();
    let (stdout, _stderr, exit) = run_ag(&[
        "--nofilename",
        "--nonumbers",
        "hello",
        dir.path().to_str().unwrap(),
    ]);
    // --nofilename + --nonumbers: no filename, no line numbers
    for line in stdout.lines() {
        if !line.is_empty() {
            // Should not start with a number followed by ':'
            let first_colon = line.find(':');
            if let Some(idx) = first_colon {
                let prefix = &line[..idx];
                assert!(
                    prefix.parse::<usize>().is_err(),
                    "should not have line number prefix: {line}"
                );
            }
        }
    }
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_003_filename_count_single_file() {
    let dir = setup_fixture();
    let f = dir.path().join("file1.txt");
    // --filename with -c on single file: ag still outputs just the count (no filename)
    let (stdout, _stderr, exit) = run_ag(&["--filename", "-c", "hello", f.to_str().unwrap()]);
    assert_eq!(stdout.trim(), "2");
    assert_eq!(exit, 0);
}
