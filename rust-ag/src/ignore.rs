/// Ignore-file engine for rust-ag.
///
/// Implements the ignore-file hierarchy that `ag` uses:
///   1. `.gitignore` (and `.git/info/exclude`) — skipped when `-U` is active
///   2. `.hgignore` — skipped when `-U` is active
///   3. `.ignore` — always honored (even with `-U`)
///   4. CLI `--ignore` patterns — always honored
///
/// The engine builds a stack of ignore rules as it descends into directories,
/// respecting the correct precedence and scope.
use std::fs;
use std::path::{Path, PathBuf};

/// A single ignore rule parsed from a gitignore-style file.
#[derive(Debug, Clone)]
struct IgnoreRule {
    /// The original pattern string.
    pattern: String,
    /// Whether this rule is a negation (starts with `!`).
    negated: bool,
    /// Whether this rule applies only to directories (ends with `/`).
    dir_only: bool,
    /// Whether this pattern starts with `/` (anchored to the ignore-file's directory).
    /// In baseline ag, only leading-`/` patterns are anchored.
    anchored: bool,
    /// Whether this pattern is a glob/fnmatch pattern (contains `*`, `?`, `[`, `]`).
    /// In baseline ag, non-anchored glob patterns with `/` in them are matched
    /// only against the filename (and thus effectively never match), while
    /// non-anchored literal patterns with `/` are substring-matched against
    /// the relative path with component-boundary checks.
    is_glob: bool,
    /// The directory containing the ignore file this rule came from.
    base_dir: PathBuf,
}

/// Source of an ignore rule set.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[allow(clippy::enum_variant_names)]
pub enum IgnoreSource {
    /// `.gitignore` or `.git/info/exclude`
    GitIgnore,
    /// `.hgignore`
    HgIgnore,
    /// `.ignore`
    DotIgnore,
    /// CLI `--ignore` patterns
    CliIgnore,
}

/// A collection of ignore rules from a single source file.
#[derive(Debug, Clone)]
struct IgnoreRuleSet {
    source: IgnoreSource,
    rules: Vec<IgnoreRule>,
}

/// The ignore engine.
#[derive(Debug)]
pub struct IgnoreEngine {
    /// Stack of rule sets, innermost last.
    rule_sets: Vec<IgnoreRuleSet>,
    /// Whether VCS ignores are active.
    vcs_ignores_active: bool,
    /// Stack of rule-set counts pushed per `push_directory` call.
    /// Used by `pop_directory` to restore state on recursion unwind.
    dir_rule_counts: Vec<usize>,
}

impl IgnoreEngine {
    /// Create a new ignore engine.
    ///
    /// - `skip_vcs_ignores`: if true, `.gitignore` and `.hgignore` rules are not loaded.
    /// - `cli_ignores`: patterns from `--ignore` flags.
    pub fn new(skip_vcs_ignores: bool, cli_ignores: &[String]) -> Self {
        let mut engine = Self {
            rule_sets: Vec::new(),
            vcs_ignores_active: !skip_vcs_ignores,
            dir_rule_counts: Vec::new(),
        };

        // Add CLI ignore patterns.
        if !cli_ignores.is_empty() {
            let rules: Vec<IgnoreRule> = cli_ignores
                .iter()
                .map(|p| IgnoreRule {
                    pattern: p.clone(),
                    negated: false,
                    dir_only: false,
                    anchored: false,
                    is_glob: is_fnmatch_pattern(p),
                    base_dir: PathBuf::from("."),
                })
                .collect();
            engine.rule_sets.push(IgnoreRuleSet {
                source: IgnoreSource::CliIgnore,
                rules,
            });
        }

        engine
    }

    /// Load ignore files from the given directory and push them onto the stack.
    ///
    /// Call [`pop_directory`] after finishing traversal of this directory to
    /// restore the ignore state and prevent rule leakage into sibling dirs.
    pub fn push_directory(&mut self, dir: &Path) {
        let before = self.rule_sets.len();

        // Always load `.ignore` files.
        let dot_ignore = dir.join(".ignore");
        if dot_ignore.is_file() {
            if let Some(rs) = Self::parse_ignore_file(&dot_ignore, IgnoreSource::DotIgnore, dir) {
                self.rule_sets.push(rs);
            }
        }

        // Load VCS ignores if active.
        if self.vcs_ignores_active {
            let gitignore = dir.join(".gitignore");
            if gitignore.is_file() {
                if let Some(rs) = Self::parse_ignore_file(&gitignore, IgnoreSource::GitIgnore, dir)
                {
                    self.rule_sets.push(rs);
                }
            }

            // Also check `.git/info/exclude`.
            let git_exclude = dir.join(".git").join("info").join("exclude");
            if git_exclude.is_file() {
                if let Some(rs) =
                    Self::parse_ignore_file(&git_exclude, IgnoreSource::GitIgnore, dir)
                {
                    self.rule_sets.push(rs);
                }
            }

            let hgignore = dir.join(".hgignore");
            if hgignore.is_file() {
                if let Some(rs) = Self::parse_ignore_file(&hgignore, IgnoreSource::HgIgnore, dir) {
                    self.rule_sets.push(rs);
                }
            }
        }

        self.dir_rule_counts.push(self.rule_sets.len() - before);
    }

    /// Pop the ignore rules that were pushed by the most recent
    /// [`push_directory`] call.
    ///
    /// This must be called after finishing traversal of a directory so that
    /// directory-scoped ignore rules do not leak into sibling directories.
    pub fn pop_directory(&mut self) {
        if let Some(count) = self.dir_rule_counts.pop() {
            let new_len = self.rule_sets.len().saturating_sub(count);
            self.rule_sets.truncate(new_len);
        }
    }

    /// Parse a single ignore file into a rule set.
    fn parse_ignore_file(
        path: &Path,
        source: IgnoreSource,
        base_dir: &Path,
    ) -> Option<IgnoreRuleSet> {
        let content = fs::read_to_string(path).ok()?;
        let mut rules = Vec::new();

        for line in content.lines() {
            let line = line.trim_end();

            // Skip empty lines and comments.
            if line.is_empty() || line.starts_with('#') {
                continue;
            }

            let (pattern, negated) = if let Some(rest) = line.strip_prefix('!') {
                (rest.to_string(), true)
            } else {
                (line.to_string(), false)
            };

            let dir_only = pattern.ends_with('/');
            let pattern = if dir_only {
                pattern.trim_end_matches('/').to_string()
            } else {
                pattern
            };

            // ag-style anchoring: strip leading `./` (like ag's add_ignore_pattern).
            let pattern = if let Some(rest) = pattern.strip_prefix("./") {
                format!("/{rest}")
            } else {
                pattern
            };

            // ag-style anchoring: a pattern is "anchored" (matched against the
            // relative path) ONLY if it starts with `/`.  In baseline ag,
            // patterns containing `/` elsewhere (e.g. `src/config.h*`) are
            // placed in the `regexes` array and matched against only the
            // filename—effectively making them non-matching when the filename
            // alone doesn't include the path prefix.  We replicate this by
            // marking only leading-slash patterns as anchored.
            let anchored = pattern.starts_with('/');
            let pattern = if anchored {
                pattern[1..].to_string()
            } else {
                pattern
            };

            let is_glob = is_fnmatch_pattern(&pattern);

            rules.push(IgnoreRule {
                pattern,
                negated,
                dir_only,
                anchored,
                is_glob,
                base_dir: base_dir.to_path_buf(),
            });
        }

        if rules.is_empty() {
            None
        } else {
            Some(IgnoreRuleSet { source, rules })
        }
    }

    /// Check if a path should be ignored.
    ///
    /// Returns `true` if the path matches an ignore rule and should be excluded.
    pub fn is_ignored(&self, path: &Path, is_dir: bool) -> bool {
        // Process rule sets from last to first (innermost to outermost).
        // Last matching rule wins (with negation support).
        let mut ignored = false;

        for rule_set in &self.rule_sets {
            // Skip VCS ignores if disabled.
            if !self.vcs_ignores_active
                && matches!(
                    rule_set.source,
                    IgnoreSource::GitIgnore | IgnoreSource::HgIgnore
                )
            {
                continue;
            }

            for rule in &rule_set.rules {
                // Skip dir-only rules for files.
                if rule.dir_only && !is_dir {
                    continue;
                }

                if self.matches_rule(rule, path) {
                    ignored = !rule.negated;
                }
            }
        }

        ignored
    }

    /// Check if a rule matches a path.
    fn matches_rule(&self, rule: &IgnoreRule, path: &Path) -> bool {
        let pattern = &rule.pattern;

        // Get the path relative to the rule's base directory.
        let rel_path = if let Ok(rel) = path.strip_prefix(&rule.base_dir) {
            rel
        } else {
            path
        };

        let path_str = rel_path.to_string_lossy();

        if rule.anchored {
            // Anchored pattern (started with `/`): match against the full
            // relative path from the ignore-file's directory.
            gitignore_match(pattern, &path_str)
        } else {
            // Unanchored pattern.  Behaviour depends on whether the pattern
            // is a glob (fnmatch) or a literal name, replicating baseline ag.
            //
            // 1. GLOB patterns (contain `*`, `?`, `[`, `]`):
            //    In baseline ag these go to `ig->regexes` and are matched
            //    only against the filename via fnmatch.  A pattern like
            //    `src/config.h*` or `tests/*.err` will never match because
            //    the filename alone doesn't include path components.
            //
            // 2. LITERAL patterns (no glob chars):
            //    In baseline ag these go to `ig->names`.  They are:
            //      a. Binary-searched against the filename (exact match), and
            //      b. Substring-matched against the relative path with
            //         component-boundary checks (the pattern must appear at
            //         position 0 or after a `/`, and end at `\0` or before
            //         a `/`).  This lets `tests/edge-cases/large-file/large.txt`
            //         match the file at that exact relative path.
            let filename = path.file_name().map(|n| n.to_string_lossy().to_string());

            // Try filename match first (both glob and literal).
            if let Some(ref name) = filename {
                if gitignore_match(pattern, name) {
                    return true;
                }
            }

            // For literal patterns, also try path-substring matching.
            if !rule.is_glob && pattern.contains('/') {
                return path_component_match(pattern, &path_str);
            }

            false
        }
    }

    /// Check if the ignore engine uses VCS ignores.
    #[allow(dead_code)]
    pub fn uses_vcs_ignores(&self) -> bool {
        self.vcs_ignores_active
    }
}

/// Check whether a pattern is a fnmatch/glob pattern (contains `*`, `?`, `[`, `]`).
///
/// Mirrors baseline ag's `is_fnmatch()` which checks for `!`, `*`, `?`, `[`, `]`.
/// We exclude `!` here because negation is handled separately during parsing.
fn is_fnmatch_pattern(pattern: &str) -> bool {
    pattern.contains('*') || pattern.contains('?') || pattern.contains('[') || pattern.contains(']')
}

/// Check if a literal pattern matches a relative path with component-boundary
/// semantics, replicating baseline ag's `path_ignore_search` substring loop
/// for non-fnmatch patterns stored in `ig->names`.
///
/// The pattern must appear as a substring of `path_str` starting at position 0
/// or immediately after a `/`, and ending at the end of `path_str` or
/// immediately before a `/`.
fn path_component_match(pattern: &str, path_str: &str) -> bool {
    let mut start = 0;
    while let Some(pos) = path_str[start..].find(pattern) {
        let abs_pos = start + pos;
        let end_pos = abs_pos + pattern.len();

        // Check left boundary: must be at start or after '/'.
        let left_ok = abs_pos == 0 || path_str.as_bytes()[abs_pos - 1] == b'/';
        // Check right boundary: must be at end or before '/'.
        let right_ok = end_pos == path_str.len() || path_str.as_bytes()[end_pos] == b'/';

        if left_ok && right_ok {
            return true;
        }
        // Move past the found position to prevent infinite loops.
        start = abs_pos + 1;
        if start >= path_str.len() {
            break;
        }
    }
    false
}

/// Simple gitignore-style glob matching.
///
/// Supports `*` (match any sequence), `?` (match single char), and basic patterns.
/// This is a simplified implementation covering the most common patterns.
fn gitignore_match(pattern: &str, text: &str) -> bool {
    glob_match(pattern.as_bytes(), text.as_bytes())
}

fn glob_match(pattern: &[u8], text: &[u8]) -> bool {
    let mut px = 0;
    let mut tx = 0;
    let mut next_px = 0;
    let mut next_tx = 0;

    while px < pattern.len() || tx < text.len() {
        if px < pattern.len() {
            match pattern[px] {
                b'*' => {
                    // If double star, match path separators too.
                    if px + 1 < pattern.len() && pattern[px + 1] == b'*' {
                        // `**` matches everything including `/`.
                        next_px = px;
                        next_tx = tx + 1;
                        px += 2;
                        // Skip optional trailing `/` after `**`.
                        if px < pattern.len() && pattern[px] == b'/' {
                            px += 1;
                        }
                        continue;
                    }
                    // Single `*` matches everything except `/`.
                    next_px = px;
                    next_tx = tx + 1;
                    px += 1;
                    continue;
                }
                b'?' if tx < text.len() && text[tx] != b'/' => {
                    px += 1;
                    tx += 1;
                    continue;
                }
                b'[' if tx < text.len() => {
                    // Character class.
                    if let Some((matched, end)) = match_char_class(&pattern[px..], text[tx]) {
                        if matched {
                            px += end;
                            tx += 1;
                            continue;
                        }
                    }
                }
                c if tx < text.len() && c == text[tx] => {
                    px += 1;
                    tx += 1;
                    continue;
                }
                _ => {}
            }
        }

        // Mismatch — try to backtrack to the last `*`.
        if next_tx > 0 && next_tx <= text.len() {
            px = next_px;
            tx = next_tx;
            continue;
        }

        return false;
    }

    true
}

/// Match a character class `[...]` pattern.
/// Returns `Some((matched, bytes_consumed))` or `None` if malformed.
fn match_char_class(pattern: &[u8], ch: u8) -> Option<(bool, usize)> {
    if pattern.is_empty() || pattern[0] != b'[' {
        return None;
    }

    let mut i = 1;
    let negated = if i < pattern.len() && (pattern[i] == b'!' || pattern[i] == b'^') {
        i += 1;
        true
    } else {
        false
    };

    let mut matched = false;

    while i < pattern.len() && pattern[i] != b']' {
        if i + 2 < pattern.len() && pattern[i + 1] == b'-' && pattern[i + 2] != b']' {
            // Range: a-z.
            let lo = pattern[i];
            let hi = pattern[i + 2];
            if ch >= lo && ch <= hi {
                matched = true;
            }
            i += 3;
        } else {
            if pattern[i] == ch {
                matched = true;
            }
            i += 1;
        }
    }

    if i < pattern.len() && pattern[i] == b']' {
        Some((matched ^ negated, i + 1))
    } else {
        None // Malformed.
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_glob_match_literal() {
        assert!(gitignore_match("foo.txt", "foo.txt"));
        assert!(!gitignore_match("foo.txt", "bar.txt"));
    }

    #[test]
    fn test_glob_match_star() {
        assert!(gitignore_match("*.txt", "foo.txt"));
        assert!(!gitignore_match("*.txt", "foo.rs"));
        assert!(gitignore_match("foo*", "foobar"));
        assert!(!gitignore_match("foo*", "barfoo"));
    }

    #[test]
    fn test_glob_match_question() {
        assert!(gitignore_match("fo?", "foo"));
        assert!(!gitignore_match("fo?", "fooo"));
    }

    #[test]
    fn test_glob_anchored_path() {
        assert!(gitignore_match("dir/file.txt", "dir/file.txt"));
        assert!(!gitignore_match("dir/file.txt", "other/file.txt"));
    }

    /// ag-style anchoring: only patterns starting with `/` are treated as
    /// path-anchored.  Patterns like `src/config.h*` that contain `/` but
    /// do NOT start with `/` are matched only against the filename, so they
    /// effectively never match when the filename alone doesn't contain `/`.
    #[test]
    fn test_ag_anchor_semantics_slash_pattern_not_leading() {
        use tempfile::tempdir;

        let dir = tempdir().unwrap();
        let base = dir.path();

        // Create src/config.h
        std::fs::create_dir_all(base.join("src")).unwrap();
        std::fs::write(base.join("src").join("config.h"), "/* generated */\n").unwrap();

        // Create a .gitignore with `src/config.h*` (slash in middle, not leading)
        std::fs::write(base.join(".gitignore"), "src/config.h*\n").unwrap();

        // Also create .git dir so gitignore is loaded
        std::fs::create_dir_all(base.join(".git")).unwrap();

        let mut engine = IgnoreEngine::new(false, &[]);
        engine.push_directory(base);

        // ag treats `src/config.h*` as a non-anchored regex matched against
        // just the filename.  Since `fnmatch("src/config.h*", "config.h",
        // FNM_PATHNAME)` does NOT match, the file is NOT ignored.
        let config_path = base.join("src").join("config.h");
        assert!(
            !engine.is_ignored(&config_path, false),
            "src/config.h should NOT be ignored by pattern 'src/config.h*' (ag semantics: \
             slash-containing patterns without leading / are matched against filename only)"
        );
    }

    /// Patterns starting with `/` should be anchored and matched against the
    /// relative path from the ignore file's directory.
    #[test]
    fn test_ag_anchor_semantics_leading_slash_pattern() {
        use tempfile::tempdir;

        let dir = tempdir().unwrap();
        let base = dir.path();

        // Create src/config.h
        std::fs::create_dir_all(base.join("src")).unwrap();
        std::fs::write(base.join("src").join("config.h"), "/* generated */\n").unwrap();

        // Create a .gitignore with `/src/config.h*` (leading slash = anchored)
        std::fs::write(base.join(".gitignore"), "/src/config.h*\n").unwrap();

        // Also create .git dir so gitignore is loaded
        std::fs::create_dir_all(base.join(".git")).unwrap();

        let mut engine = IgnoreEngine::new(false, &[]);
        engine.push_directory(base);

        // Leading-slash pattern IS anchored and matched against relative path.
        let config_path = base.join("src").join("config.h");
        assert!(
            engine.is_ignored(&config_path, false),
            "src/config.h SHOULD be ignored by pattern '/src/config.h*' (anchored)"
        );
    }

    /// Test the `tests/*.err` gitignore pattern behaves like ag:
    /// Without leading `/`, it's matched only against filename.
    #[test]
    fn test_ag_anchor_semantics_tests_err_pattern() {
        use tempfile::tempdir;

        let dir = tempdir().unwrap();
        let base = dir.path();

        // Create tests/fail/test.t.err
        std::fs::create_dir_all(base.join("tests").join("fail")).unwrap();
        std::fs::write(
            base.join("tests").join("fail").join("test.t.err"),
            "error output\n",
        )
        .unwrap();

        // Create a .gitignore with `tests/*.err` (slash in middle, not leading)
        std::fs::write(base.join(".gitignore"), "tests/*.err\n").unwrap();
        std::fs::create_dir_all(base.join(".git")).unwrap();

        let mut engine = IgnoreEngine::new(false, &[]);
        engine.push_directory(base);

        // ag treats `tests/*.err` as a non-anchored regex matched against
        // just the filename.  fnmatch("tests/*.err", "test.t.err", FNM_PATHNAME)
        // does NOT match, so the file is NOT ignored.
        let err_path = base.join("tests").join("fail").join("test.t.err");
        assert!(
            !engine.is_ignored(&err_path, false),
            "test.t.err should NOT be ignored by pattern 'tests/*.err' (ag semantics)"
        );
    }

    /// Simple unanchored patterns without `/` still work as before.
    #[test]
    fn test_ag_anchor_semantics_simple_glob_still_works() {
        use tempfile::tempdir;

        let dir = tempdir().unwrap();
        let base = dir.path();

        std::fs::create_dir_all(base.join("sub")).unwrap();
        std::fs::write(base.join("sub").join("foo.o"), "binary\n").unwrap();

        std::fs::write(base.join(".gitignore"), "*.o\n").unwrap();
        std::fs::create_dir_all(base.join(".git")).unwrap();

        let mut engine = IgnoreEngine::new(false, &[]);
        engine.push_directory(base);

        let obj_path = base.join("sub").join("foo.o");
        assert!(
            engine.is_ignored(&obj_path, false),
            "foo.o should be ignored by pattern '*.o'"
        );
    }

    /// Literal path patterns without leading `/` should be matched against the
    /// relative path using component-boundary substring matching (ag semantics).
    /// e.g. `tests/edge-cases/large-file/large.txt` in .gitignore should
    /// match the exact file at that path.
    #[test]
    fn test_ag_anchor_semantics_literal_path_pattern() {
        use tempfile::tempdir;

        let dir = tempdir().unwrap();
        let base = dir.path();

        // Create the target file.
        std::fs::create_dir_all(base.join("tests").join("edge-cases").join("large-file")).unwrap();
        std::fs::write(
            base.join("tests")
                .join("edge-cases")
                .join("large-file")
                .join("large.txt"),
            "large content\n",
        )
        .unwrap();

        // Also create a file that should NOT be ignored.
        std::fs::write(
            base.join("tests")
                .join("edge-cases")
                .join("large-file")
                .join("normal.txt"),
            "normal content\n",
        )
        .unwrap();

        // Literal path pattern (no glob chars, contains `/`, no leading `/`).
        std::fs::write(
            base.join(".gitignore"),
            "tests/edge-cases/large-file/large.txt\n",
        )
        .unwrap();
        std::fs::create_dir_all(base.join(".git")).unwrap();

        let mut engine = IgnoreEngine::new(false, &[]);
        engine.push_directory(base);

        // The literal path pattern should match via component-boundary
        // substring matching against the relative path.
        let large_path = base
            .join("tests")
            .join("edge-cases")
            .join("large-file")
            .join("large.txt");
        assert!(
            engine.is_ignored(&large_path, false),
            "large.txt SHOULD be ignored by literal path pattern \
             'tests/edge-cases/large-file/large.txt' (ag semantics: \
             literal patterns use path-substring matching)"
        );

        // A different file should not be ignored.
        let normal_path = base
            .join("tests")
            .join("edge-cases")
            .join("large-file")
            .join("normal.txt");
        assert!(
            !engine.is_ignored(&normal_path, false),
            "normal.txt should NOT be ignored by that pattern"
        );
    }

    /// Test path_component_match helper directly.
    #[test]
    fn test_path_component_match() {
        // Exact match at position 0.
        assert!(path_component_match(
            "tests/edge-cases/large-file/large.txt",
            "tests/edge-cases/large-file/large.txt"
        ));
        // Partial path match at a component boundary.
        assert!(path_component_match(
            "large-file/large.txt",
            "tests/edge-cases/large-file/large.txt"
        ));
        // Filename-only match at component boundary.
        assert!(path_component_match(
            "large.txt",
            "tests/edge-cases/large-file/large.txt"
        ));
        // Should NOT match in the middle of a component.
        assert!(!path_component_match(
            "arge.txt",
            "tests/edge-cases/large-file/large.txt"
        ));
        // Should NOT match partial component prefix.
        assert!(!path_component_match(
            "large-file/larg",
            "tests/edge-cases/large-file/large.txt"
        ));
    }
}
