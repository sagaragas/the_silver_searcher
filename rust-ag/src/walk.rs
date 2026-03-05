/// Directory walker for rust-ag.
///
/// Implements recursive file discovery that mirrors `ag`'s traversal behavior:
/// - Respects ignore-file hierarchy (.gitignore, .ignore, --ignore)
/// - Skips hidden files/directories by default (unless `--hidden`)
/// - Skips VCS directories (.git, .hg, .svn)
/// - Supports depth limiting (`--depth`)
/// - Supports non-recursive mode (`-n`)
/// - Supports `--one-device` to avoid crossing filesystem boundaries
/// - Handles broken symlinks gracefully with error messages
use std::fs;
use std::path::{Path, PathBuf};

use crate::ignore::IgnoreEngine;
use crate::opts::Opts;

/// Known VCS directories that are always skipped during traversal.
const VCS_DIRS: &[&str] = &[".git", ".hg", ".svn"];

/// Walk the given paths and return a sorted list of files to search.
///
/// Files are returned in sorted order (matching `ag --workers=1` output
/// determinism requirements for parity testing).
pub fn walk_paths(opts: &Opts) -> Vec<PathBuf> {
    let mut files = Vec::new();

    for path_str in &opts.paths {
        let path = Path::new(path_str);
        if path.is_file() {
            // Single file — always include.
            files.push(path.to_path_buf());
        } else if path.is_dir() {
            // Capture root device ID for --one-device.
            let root_dev = if opts.one_device {
                get_device_id(path)
            } else {
                None
            };

            let mut engine = IgnoreEngine::new(
                opts.skip_vcs_ignores || opts.unrestricted,
                &opts.ignore_patterns,
            );
            walk_dir(path, path, opts, &mut engine, 0, root_dev, &mut files);
        } else {
            // Non-existent or special path — will be reported as an error
            // by the caller.
            eprintln!("ERR: unable to open {path_str}: No such file or directory");
        }
    }

    // Sort for deterministic output (matches ag --workers=1 behavior).
    files.sort();
    files
}

/// Get the device ID for a path (Unix only).
#[cfg(unix)]
fn get_device_id(path: &Path) -> Option<u64> {
    use std::os::unix::fs::MetadataExt;
    fs::metadata(path).ok().map(|m| m.dev())
}

/// Get the device ID for a path (non-Unix stub).
#[cfg(not(unix))]
fn get_device_id(_path: &Path) -> Option<u64> {
    None
}

/// Recursively walk a directory.
fn walk_dir(
    dir: &Path,
    _root: &Path,
    opts: &Opts,
    engine: &mut IgnoreEngine,
    depth: usize,
    root_dev: Option<u64>,
    out: &mut Vec<PathBuf>,
) {
    // Load ignore files for this directory.
    engine.push_directory(dir);

    // Read directory entries.
    let mut entries: Vec<fs::DirEntry> = match fs::read_dir(dir) {
        Ok(rd) => rd.filter_map(|e| e.ok()).collect(),
        Err(e) => {
            eprintln!("ERR: unable to open directory {}: {e}", dir.display());
            engine.pop_directory();
            return;
        }
    };

    // Sort entries for deterministic traversal order.
    entries.sort_by_key(|e| e.file_name());

    for entry in entries {
        let path = entry.path();
        let file_name = match entry.file_name().to_str() {
            Some(s) => s.to_string(),
            None => continue,
        };

        let is_symlink = entry.file_type().map(|ft| ft.is_symlink()).unwrap_or(false);

        // Handle broken symlinks: if the path doesn't exist (dangling symlink),
        // report an error matching ag's behavior and skip.
        if is_symlink && !path.exists() {
            if opts.follow_symlinks {
                eprintln!("ERR: Skipping {}: Error fstat()ing file.", path.display());
            }
            continue;
        }

        let is_dir = path.is_dir();

        // Skip VCS directories always.
        if is_dir && VCS_DIRS.contains(&file_name.as_str()) {
            continue;
        }

        // Skip hidden files/directories unless --hidden or --unrestricted.
        if file_name.starts_with('.') && !opts.hidden && !opts.unrestricted {
            continue;
        }

        // Skip symlinks unless --follow.
        // ag skips both file and directory symlinks by default;
        // only -f / --follow enables traversal through symlinks.
        if is_symlink && !opts.follow_symlinks {
            continue;
        }

        // One-device check: skip entries on a different filesystem device.
        if let Some(dev) = root_dev {
            if let Some(entry_dev) = get_device_id(&path) {
                if entry_dev != dev {
                    continue;
                }
            }
        }

        // Check ignore rules (unless --unrestricted).
        if !opts.unrestricted && engine.is_ignored(&path, is_dir) {
            continue;
        }

        if is_dir {
            // Check recursion settings using the authoritative "last wins" mode.
            if opts.recurse_mode == crate::opts::RecurseMode::NoRecurse {
                continue;
            }
            if depth >= opts.max_depth {
                continue;
            }
            walk_dir(&path, _root, opts, engine, depth + 1, root_dev, out);
        } else {
            // Don't filter out binary files in the walker; let search_file
            // handle binary detection so it can report "Binary file X matches."
            // The only remaining walker-level filter is for performance when
            // not in binary-search mode—skip files detected as binary to
            // avoid reading their full content for nothing.
            if !opts.search_binary && !opts.unrestricted && is_likely_binary(&path) {
                continue;
            }

            out.push(path);
        }
    }

    // Pop directory-scoped ignore rules to prevent leakage into siblings.
    engine.pop_directory();
}

/// Simple binary file detection.
///
/// Reads the first few KB and checks for null bytes,
/// matching `ag`'s behavior of skipping binary files by default.
fn is_likely_binary(path: &Path) -> bool {
    let data = match fs::read(path) {
        Ok(d) => d,
        Err(_) => return false,
    };

    // Check first 512 bytes for null bytes.
    let check_len = data.len().min(512);
    data[..check_len].contains(&0)
}
