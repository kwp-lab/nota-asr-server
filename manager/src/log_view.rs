use std::collections::VecDeque;
use std::fs::{self, File};
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};

const INITIAL_TAIL_BYTES: u64 = 512 * 1024;

pub struct LogView {
    path: PathBuf,
    offset: u64,
    pending: Vec<u8>,
    lines: VecDeque<String>,
    max_lines: usize,
    initialized: bool,
    skip_partial_line: bool,
}

impl LogView {
    pub fn new(path: PathBuf, max_lines: usize) -> Self {
        Self {
            path,
            offset: 0,
            pending: Vec::new(),
            lines: VecDeque::new(),
            max_lines,
            initialized: false,
            skip_partial_line: false,
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn set_path(&mut self, path: PathBuf) {
        if self.path == path {
            return;
        }
        self.path = path;
        self.offset = 0;
        self.pending.clear();
        self.lines.clear();
        self.initialized = false;
        self.skip_partial_line = false;
    }

    pub fn refresh(&mut self) -> Result<bool> {
        let metadata = match fs::metadata(&self.path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(error) => {
                return Err(error)
                    .with_context(|| format!("无法读取日志文件：{}", self.path.display()));
            }
        };
        let length = metadata.len();
        if length < self.offset {
            self.offset = 0;
            self.pending.clear();
            self.lines.clear();
            self.initialized = false;
            self.skip_partial_line = false;
        }

        let mut file = File::open(&self.path)
            .with_context(|| format!("无法打开日志文件：{}", self.path.display()))?;
        if !self.initialized {
            self.offset = length.saturating_sub(INITIAL_TAIL_BYTES);
            self.skip_partial_line = self.offset > 0;
            self.initialized = true;
        }
        if length == self.offset {
            return Ok(false);
        }

        file.seek(SeekFrom::Start(self.offset))?;
        let mut bytes = Vec::with_capacity((length - self.offset).min(INITIAL_TAIL_BYTES) as usize);
        file.read_to_end(&mut bytes)?;
        self.offset = file.stream_position()?;
        if bytes.is_empty() {
            return Ok(false);
        }
        self.pending.extend_from_slice(&bytes);
        self.consume_complete_lines();
        Ok(true)
    }

    pub fn clear_view(&mut self) -> Result<()> {
        self.lines.clear();
        self.pending.clear();
        self.offset = fs::metadata(&self.path)
            .map(|metadata| metadata.len())
            .unwrap_or(0);
        self.initialized = true;
        self.skip_partial_line = false;
        Ok(())
    }

    pub fn lines(&self) -> impl Iterator<Item = &str> {
        self.lines.iter().map(String::as_str)
    }

    pub fn line_count(&self) -> usize {
        self.lines.len()
    }

    fn consume_complete_lines(&mut self) {
        while let Some(newline) = self.pending.iter().position(|byte| *byte == b'\n') {
            let mut raw = self.pending.drain(..=newline).collect::<Vec<_>>();
            while matches!(raw.last(), Some(b'\n' | b'\r')) {
                raw.pop();
            }
            if self.skip_partial_line {
                self.skip_partial_line = false;
                continue;
            }
            self.lines
                .push_back(String::from_utf8_lossy(&raw).into_owned());
            while self.lines.len() > self.max_lines {
                self.lines.pop_front();
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use super::*;
    use uuid::Uuid;

    #[test]
    fn follows_appended_log_lines() {
        let root = std::env::temp_dir().join(format!("nota-log-view-{}", Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("server.log");
        fs::write(&path, "first\n").unwrap();
        let mut view = LogView::new(path.clone(), 10);

        assert!(view.refresh().unwrap());
        assert_eq!(view.lines().collect::<Vec<_>>(), ["first"]);

        let mut writer = fs::OpenOptions::new().append(true).open(&path).unwrap();
        writer.write_all("第二行\n".as_bytes()).unwrap();
        writer.flush().unwrap();
        assert!(view.refresh().unwrap());
        assert_eq!(view.lines().collect::<Vec<_>>(), ["first", "第二行"]);

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn clear_view_keeps_only_future_lines() {
        let root = std::env::temp_dir().join(format!("nota-log-clear-{}", Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("server.log");
        fs::write(&path, "old\n").unwrap();
        let mut view = LogView::new(path.clone(), 10);
        view.refresh().unwrap();
        view.clear_view().unwrap();

        let mut writer = fs::OpenOptions::new().append(true).open(&path).unwrap();
        writer.write_all(b"new\n").unwrap();
        writer.flush().unwrap();
        view.refresh().unwrap();
        assert_eq!(view.lines().collect::<Vec<_>>(), ["new"]);

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn enforces_the_line_limit() {
        let root = std::env::temp_dir().join(format!("nota-log-limit-{}", Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("server.log");
        fs::write(&path, "one\ntwo\nthree\n").unwrap();
        let mut view = LogView::new(path, 2);

        view.refresh().unwrap();
        assert_eq!(view.lines().collect::<Vec<_>>(), ["two", "three"]);

        fs::remove_dir_all(root).unwrap();
    }
}
