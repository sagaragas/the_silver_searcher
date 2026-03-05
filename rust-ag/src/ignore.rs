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
    /// Whether this pattern contains a `/` (anchored to the ignore-file's directory).
    anchored: bool,
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
    pub fn push_directory(&mut self, dir: &Path) {
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

            // A pattern is "anchored" if it contains a `/` (other than trailing).
            let anchored = pattern.contains('/');

            rules.push(IgnoreRule {
                pattern,
                negated,
                dir_only,
                anchored,
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
            // Anchored pattern: match against the full relative path.
            gitignore_match(pattern, &path_str)
        } else {
            // Unanchored pattern: match against any path component or the filename.
            // First try matching against the full relative path.
            if gitignore_match(pattern, &path_str) {
                return true;
            }
            // Then try just the filename.
            if let Some(name) = path.file_name() {
                gitignore_match(pattern, &name.to_string_lossy())
            } else {
                false
            }
        }
    }

    /// Check if the ignore engine uses VCS ignores.
    #[allow(dead_code)]
    pub fn uses_vcs_ignores(&self) -> bool {
        self.vcs_ignores_active
    }
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
}
