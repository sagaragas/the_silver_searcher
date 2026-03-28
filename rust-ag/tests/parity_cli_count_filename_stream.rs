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
    run_ag_stdin_bytes(args, stdin_data.as_bytes())
}

/// Helper: run rust-ag with raw bytes piped to stdin.
fn run_ag_stdin_bytes(args: &[&str], stdin_data: &[u8]) -> (String, String, i32) {
    let mut child = Command::new(rust_ag_bin())
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("failed to spawn rust-ag");

    if let Some(ref mut stdin) = child.stdin {
        stdin.write_all(stdin_data).unwrap();
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

// ============================================================
// Stream -c -v parity (invert-match in stream count mode)
// ============================================================

#[test]
fn val_cli_001_count_stream_invert_basic() {
    // ag -c -v hello on "hello hello\nworld\nfoo\n":
    // Line 1 matches → skipped (inverted). Lines 2,3 don't match → each prints "1".
    let (stdout, _stderr, exit) = run_ag_stdin(&["-c", "-v", "hello"], "hello hello\nworld\nfoo\n");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 2, "should have 2 non-matching lines");
    assert_eq!(lines[0], "1");
    assert_eq!(lines[1], "1");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_001_count_stream_invert_all_match() {
    // ag -c -v hello on "hello\nhello\n": all lines match → no inverted output.
    let (stdout, _stderr, exit) = run_ag_stdin(&["-c", "-v", "hello"], "hello\nhello\n");
    assert_eq!(stdout.trim(), "", "all matching → no inverted output");
    assert_eq!(exit, 1, "no inverted matches → exit 1");
}

#[test]
fn val_cli_001_count_stream_invert_none_match() {
    // ag -c -v hello on "foo\nbar\nbaz\n": no lines match → all inverted.
    let (stdout, _stderr, exit) = run_ag_stdin(&["-c", "-v", "hello"], "foo\nbar\nbaz\n");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 3, "should have 3 inverted lines");
    for l in &lines {
        assert_eq!(*l, "1");
    }
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_001_count_stream_invert_mixed() {
    // ag -c -v hello on "hello hello\nworld\nhello\nfoo\n":
    // Lines 1,3 match → skipped. Lines 2,4 don't → each prints "1".
    let (stdout, _stderr, exit) =
        run_ag_stdin(&["-c", "-v", "hello"], "hello hello\nworld\nhello\nfoo\n");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines.len(), 2, "2 non-matching lines");
    assert_eq!(lines[0], "1");
    assert_eq!(lines[1], "1");
    assert_eq!(exit, 0);
}

// ============================================================
// Non-UTF8 stdin handling (byte-tolerant stream mode)
// ============================================================

#[test]
fn val_cli_003_stream_non_utf8_normal() {
    // Pipe non-UTF8 bytes: \xFFhello\nworld\n
    // ag matches "hello" on line 1 and outputs the line (with replacement char).
    let mut input: Vec<u8> = vec![0xFF];
    input.extend_from_slice(b"hello\nworld\n");
    let (stdout, _stderr, exit) = run_ag_stdin_bytes(&["hello"], &input);
    // Should not panic. Should find the match on line 1.
    assert!(
        stdout.contains("hello"),
        "should find hello in non-UTF8 stream"
    );
    assert_eq!(exit, 0, "match found → exit 0");
}

#[test]
fn val_cli_003_stream_non_utf8_count() {
    // Pipe non-UTF8 bytes with -c: \xFFhello\nworld\n
    let mut input: Vec<u8> = vec![0xFF];
    input.extend_from_slice(b"hello\nworld\n");
    let (stdout, _stderr, exit) = run_ag_stdin_bytes(&["-c", "hello"], &input);
    // Should not panic. Line 1 has 1 match.
    assert_eq!(stdout.trim(), "1", "stream -c should count 1 match");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_003_stream_non_utf8_no_panic() {
    // Ensure non-UTF8 stdin does not cause a panic (exit code != 101).
    let input: Vec<u8> = vec![0xFF, 0xFE, b'\n', 0x80, 0x81, b'\n'];
    let (_stdout, _stderr, exit) = run_ag_stdin_bytes(&["hello"], &input);
    // No match expected, but must not panic.
    assert_ne!(exit, 101, "must not panic on non-UTF8 stdin");
    assert_eq!(exit, 1, "no match → exit 1");
}

// ============================================================
// Multi-file -c -v parity: suppress zero-count files
// ============================================================

#[test]
fn val_cli_001_count_invert_multi_file_suppresses_zero() {
    // Baseline ag -c -v: only files with non-zero inverted count are printed.
    // file1.txt: "hello world\nhello there\ngoodbye\n" → 2 match hello, 1 non-match → count=1
    // multi_match.txt: "hello hello hello\n" → 1 line matches → 0 non-match → suppressed
    // sub/file2.txt: "hello foo\nhello bar\n" → 2 lines match → 0 non-match → suppressed
    let dir = setup_fixture();
    let (stdout, _stderr, exit) = run_ag(&["-c", "-v", "hello", dir.path().to_str().unwrap()]);
    let mut lines: Vec<&str> = stdout.trim().lines().collect();
    lines.sort();
    // Only file1.txt should appear (1 non-matching line).
    assert_eq!(
        lines.len(),
        1,
        "only files with non-zero inverted count should appear, got: {:?}",
        lines
    );
    assert!(
        lines[0].ends_with(":1"),
        "file1.txt should show count 1: {}",
        lines[0]
    );
    assert!(
        lines[0].contains("file1.txt"),
        "should be file1.txt: {}",
        lines[0]
    );
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_001_count_invert_nofilename_multi_file_suppresses_zero() {
    // Same as above but with --nofilename: only non-zero counts.
    let dir = setup_fixture();
    let (stdout, _stderr, exit) = run_ag(&[
        "--nofilename",
        "-c",
        "-v",
        "hello",
        dir.path().to_str().unwrap(),
    ]);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    // Only 1 line (for file1.txt's count of 1).
    assert_eq!(
        lines.len(),
        1,
        "only non-zero inverted counts should appear, got: {:?}",
        lines
    );
    assert_eq!(lines[0], "1", "inverted count should be 1");
    assert_eq!(exit, 0);
}

#[test]
fn val_cli_001_count_invert_multi_file_all_match() {
    // If all files have all lines matching, -c -v produces no output.
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("a.txt"), "hello\n").unwrap();
    std::fs::write(dir.path().join("b.txt"), "hello world\n").unwrap();
    let (stdout, _stderr, exit) = run_ag(&["-c", "-v", "hello", dir.path().to_str().unwrap()]);
    assert_eq!(
        stdout.trim(),
        "",
        "all files fully matching → no inverted output"
    );
    assert_eq!(exit, 1, "no inverted matches → exit 1");
}

// ============================================================
// Direct baseline-vs-rust transcript comparisons (VAL-CLI-001..003)
// ============================================================

/// Path to the baseline ag binary from the repo root.
fn baseline_ag_path() -> std::path::PathBuf {
    let ag_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("ag");
    if !ag_path.exists() {
        panic!(
            "baseline ag binary not found at {}; build with ./build.sh first",
            ag_path.display()
        );
    }
    ag_path
}

/// Helper: run baseline ag on file paths and return (stdout, stderr, exit_code).
fn run_baseline_ag(args: &[&str]) -> (String, String, i32) {
    let ag_path = baseline_ag_path();
    let out = Command::new(&ag_path)
        .args(args)
        .output()
        .expect("failed to run baseline ag");
    (
        String::from_utf8_lossy(&out.stdout).to_string(),
        String::from_utf8_lossy(&out.stderr).to_string(),
        out.status.code().unwrap_or(-1),
    )
}

/// Helper: run baseline ag with stdin piped and return (stdout, stderr, exit_code).
fn run_baseline_ag_stdin(args: &[&str], stdin_data: &str) -> (String, String, i32) {
    let ag_path = baseline_ag_path();
    let mut child = Command::new(&ag_path)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("failed to spawn baseline ag");
    if let Some(ref mut stdin) = child.stdin {
        stdin.write_all(stdin_data.as_bytes()).unwrap();
    }
    drop(child.stdin.take());
    let out = child
        .wait_with_output()
        .expect("failed to wait on baseline ag");
    (
        String::from_utf8_lossy(&out.stdout).to_string(),
        String::from_utf8_lossy(&out.stderr).to_string(),
        out.status.code().unwrap_or(-1),
    )
}

/// Normalise multi-file output for comparison: sort non-empty lines, strip blanks.
fn normalise_multifile_output(text: &str) -> Vec<String> {
    let mut lines: Vec<String> = text
        .lines()
        .filter(|l| !l.is_empty())
        .map(|l| l.to_string())
        .collect();
    lines.sort();
    lines
}

#[test]
fn val_cli_001_transcript_count_multi_file() {
    // Direct transcript comparison: ag -c vs rust-ag -c on multi-file fixture.
    let dir = setup_fixture();
    let path = dir.path().to_str().unwrap();
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "-c",
        "hello",
        path,
    ]);
    let (rust_out, _rust_err, rust_exit) = run_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "-c",
        "hello",
        path,
    ]);

    let ag_norm = normalise_multifile_output(&ag_out);
    let rust_norm = normalise_multifile_output(&rust_out);
    assert_eq!(
        ag_norm, rust_norm,
        "sorted -c output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_norm, rust_norm
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

#[test]
fn val_cli_002_transcript_default_multi_file() {
    // Direct transcript comparison: default multi-file search.
    let dir = setup_fixture();
    let path = dir.path().to_str().unwrap();
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "hello",
        path,
    ]);
    let (rust_out, _rust_err, rust_exit) = run_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "hello",
        path,
    ]);

    let ag_norm = normalise_multifile_output(&ag_out);
    let rust_norm = normalise_multifile_output(&rust_out);
    assert_eq!(
        ag_norm, rust_norm,
        "sorted default output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_norm, rust_norm
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

#[test]
fn val_cli_003_transcript_nofilename_multi_file() {
    // Direct transcript comparison: --nofilename multi-file search.
    // Blank-line separated groups — compare sorted non-empty lines.
    let dir = setup_fixture();
    let path = dir.path().to_str().unwrap();
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "--nofilename",
        "hello",
        path,
    ]);
    let (rust_out, _rust_err, rust_exit) = run_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "--nofilename",
        "hello",
        path,
    ]);

    let ag_norm = normalise_multifile_output(&ag_out);
    let rust_norm = normalise_multifile_output(&rust_out);
    assert_eq!(
        ag_norm, rust_norm,
        "sorted --nofilename output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_norm, rust_norm
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

#[test]
fn val_cli_001_transcript_count_invert_multi_file() {
    // Direct transcript comparison: ag -c -v vs rust-ag -c -v on multi-file fixture.
    let dir = setup_fixture();
    let path = dir.path().to_str().unwrap();
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "-c",
        "-v",
        "hello",
        path,
    ]);
    let (rust_out, _rust_err, rust_exit) = run_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "-c",
        "-v",
        "hello",
        path,
    ]);

    let ag_norm = normalise_multifile_output(&ag_out);
    let rust_norm = normalise_multifile_output(&rust_out);
    assert_eq!(
        ag_norm, rust_norm,
        "sorted -c -v output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_norm, rust_norm
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

#[test]
fn val_cli_001_transcript_count_nofilename_multi_file() {
    // Direct transcript comparison: ag -c --nofilename vs rust-ag.
    let dir = setup_fixture();
    let path = dir.path().to_str().unwrap();
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "-c",
        "--nofilename",
        "hello",
        path,
    ]);
    let (rust_out, _rust_err, rust_exit) = run_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "-c",
        "--nofilename",
        "hello",
        path,
    ]);

    // For --nofilename -c, both should output sorted counts.
    let mut ag_lines: Vec<&str> = ag_out.trim().lines().collect();
    let mut rust_lines: Vec<&str> = rust_out.trim().lines().collect();
    ag_lines.sort();
    rust_lines.sort();
    assert_eq!(
        ag_lines, rust_lines,
        "sorted -c --nofilename output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_lines, rust_lines
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

#[test]
fn val_cli_002_transcript_nonumbers_multi_file() {
    // Direct transcript comparison: --nonumbers multi-file.
    let dir = setup_fixture();
    let path = dir.path().to_str().unwrap();
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "--nonumbers",
        "hello",
        path,
    ]);
    let (rust_out, _rust_err, rust_exit) = run_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "--nonumbers",
        "hello",
        path,
    ]);

    let ag_norm = normalise_multifile_output(&ag_out);
    let rust_norm = normalise_multifile_output(&rust_out);
    assert_eq!(
        ag_norm, rust_norm,
        "sorted --nonumbers output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_norm, rust_norm
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

#[test]
fn val_cli_003_transcript_nofilename_numbers_multi_file() {
    // Direct transcript comparison: --nofilename --numbers multi-file.
    let dir = setup_fixture();
    let path = dir.path().to_str().unwrap();
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "--nofilename",
        "--numbers",
        "hello",
        path,
    ]);
    let (rust_out, _rust_err, rust_exit) = run_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "--nofilename",
        "--numbers",
        "hello",
        path,
    ]);

    let ag_norm = normalise_multifile_output(&ag_out);
    let rust_norm = normalise_multifile_output(&rust_out);
    assert_eq!(
        ag_norm, rust_norm,
        "sorted --nofilename --numbers output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_norm, rust_norm
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

// ============================================================
// Single-file transcript comparisons (VAL-CLI-001 + VAL-CLI-002)
// ============================================================

/// Deterministic fixture path relative to the repo root.
fn fixture_path() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("tests")
        .join("cli-count-stream-fixture.txt")
}

#[test]
fn val_cli_001_transcript_count_single_file() {
    // Direct transcript: ag -c vs rust-ag -c on single fixture file.
    let f = fixture_path();
    let fstr = f.to_str().unwrap();
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "-c",
        "hello",
        fstr,
    ]);
    let (rust_out, _rust_err, rust_exit) = run_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "-c",
        "hello",
        fstr,
    ]);
    assert_eq!(
        ag_out.trim(),
        rust_out.trim(),
        "single-file -c output should match baseline:\nbaseline: {}\nrust-ag:  {}",
        ag_out.trim(),
        rust_out.trim()
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

#[test]
fn val_cli_002_transcript_default_single_file() {
    // Direct transcript: default search on single fixture file.
    // Single-file mode: no filename prefix, just "lineno:content".
    let f = fixture_path();
    let fstr = f.to_str().unwrap();
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "hello",
        fstr,
    ]);
    let (rust_out, _rust_err, rust_exit) = run_ag(&[
        "--nocolor",
        "--workers=1",
        "--parallel",
        "--noaffinity",
        "hello",
        fstr,
    ]);
    assert_eq!(
        ag_out, rust_out,
        "single-file default output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_out, rust_out
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

// ============================================================
// Stdin/stream transcript comparisons (VAL-CLI-001 + VAL-CLI-003)
// ============================================================

/// Deterministic stdin data matching the fixture file.
const STREAM_FIXTURE: &str = "hello world\nhello there\ngoodbye\nhello hello hello\n";

#[test]
fn val_cli_001_transcript_stream_count() {
    // Direct transcript: ag -c via stdin vs rust-ag -c via stdin.
    // Omit --parallel: baseline ag disables stream mode with --parallel.
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag_stdin(
        &["--nocolor", "--workers=1", "--noaffinity", "-c", "hello"],
        STREAM_FIXTURE,
    );
    let (rust_out, _rust_err, rust_exit) = run_ag_stdin(
        &["--nocolor", "--workers=1", "--noaffinity", "-c", "hello"],
        STREAM_FIXTURE,
    );
    assert_eq!(
        ag_out, rust_out,
        "stream -c output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_out, rust_out
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

#[test]
fn val_cli_003_transcript_stream_default() {
    // Direct transcript: default stdin search (no filename, no line numbers).
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag_stdin(
        &["--nocolor", "--workers=1", "--noaffinity", "hello"],
        STREAM_FIXTURE,
    );
    let (rust_out, _rust_err, rust_exit) = run_ag_stdin(
        &["--nocolor", "--workers=1", "--noaffinity", "hello"],
        STREAM_FIXTURE,
    );
    assert_eq!(
        ag_out, rust_out,
        "stream default output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_out, rust_out
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}

#[test]
fn val_cli_003_transcript_stream_numbers() {
    // Direct transcript: stdin search with --numbers.
    let (ag_out, _ag_err, ag_exit) = run_baseline_ag_stdin(
        &[
            "--nocolor",
            "--workers=1",
            "--noaffinity",
            "--numbers",
            "hello",
        ],
        STREAM_FIXTURE,
    );
    let (rust_out, _rust_err, rust_exit) = run_ag_stdin(
        &[
            "--nocolor",
            "--workers=1",
            "--noaffinity",
            "--numbers",
            "hello",
        ],
        STREAM_FIXTURE,
    );
    assert_eq!(
        ag_out, rust_out,
        "stream --numbers output should match baseline:\nbaseline: {:?}\nrust-ag:  {:?}",
        ag_out, rust_out
    );
    assert_eq!(ag_exit, rust_exit, "exit codes should match");
}
