use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, mpsc};
use std::thread;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use serde::Deserialize;
use serde_json::Value;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;

#[derive(Clone, Debug, Deserialize)]
pub struct ModelInfo {
    pub alias: String,
    pub display_name: String,
    pub installed: bool,
    pub download_bytes: u64,
    pub license: String,
    pub requires_license_acknowledgement: bool,
}

#[derive(Debug)]
pub enum TaskEvent {
    Json(Value),
    Finished(Result<(), String>),
}

pub struct CliTask {
    pub child: Arc<Mutex<Child>>,
    pub receiver: mpsc::Receiver<TaskEvent>,
}

impl CliTask {
    pub fn cancel(&self) -> Result<()> {
        self.child.lock().expect("CLI child lock poisoned").kill()?;
        Ok(())
    }
}

pub fn list_models(python: &Path, config: &Path) -> Result<Vec<ModelInfo>> {
    let mut command = base_command(python);
    command.args(["-m", "nota_asr_server.cli", "models", "list", "--config"]);
    command.arg(config).args(["--output", "json"]);
    let output = command.output().context("无法执行模型列表命令")?;
    if !output.status.success() {
        bail!(
            "模型列表命令失败：{}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
    let value = parse_json_response(&output.stdout).context("模型列表响应无效")?;
    serde_json::from_value(value["models"].clone()).context("模型列表字段无效")
}

pub fn run_doctor(python: &Path, config: &Path) -> Result<Value> {
    let mut command = base_command(python);
    command.args(["-m", "nota_asr_server.cli", "doctor", "--config"]);
    command.arg(config).args(["--output", "json"]);
    let output = command.output().context("无法执行诊断命令")?;
    let value = parse_json_response(&output.stdout).context("诊断响应无效")?;
    Ok(value)
}

pub fn verify_model(python: &Path, config: &Path, alias: &str) -> Result<Value> {
    let mut command = base_command(python);
    command.args([
        "-m",
        "nota_asr_server.cli",
        "models",
        "verify",
        alias,
        "--config",
    ]);
    command.arg(config).args(["--output", "json"]);
    let output = command.output().context("无法执行模型验证命令")?;
    let value = parse_json_response(&output.stdout).context("模型验证响应无效")?;
    if !output.status.success() || !value["installed"].as_bool().unwrap_or(false) {
        bail!("模型 {alias} 验证失败");
    }
    Ok(value)
}

pub fn start_model_install(
    python: PathBuf,
    config: PathBuf,
    alias: String,
    accept_undeclared: bool,
) -> Result<CliTask> {
    let mut command = base_command(&python);
    command.args([
        "-m",
        "nota_asr_server.cli",
        "models",
        "install",
        &alias,
        "--config",
    ]);
    command.arg(config).args(["--events", "jsonl"]);
    if accept_undeclared {
        command.arg("--accept-undeclared-license");
    }
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn().context("无法启动模型下载")?;
    let stdout = child.stdout.take().context("无法读取模型下载输出")?;
    let stderr = child.stderr.take().context("无法读取模型下载错误输出")?;
    let child = Arc::new(Mutex::new(child));
    let wait_child = Arc::clone(&child);
    let stderr_text = Arc::new(Mutex::new(String::new()));
    let stderr_capture = Arc::clone(&stderr_text);
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            let mut text = stderr_capture.lock().expect("CLI stderr lock poisoned");
            text.push_str(&line);
            text.push('\n');
            if text.len() > 16 * 1024 {
                let split = text.len() - 16 * 1024;
                text.drain(..split);
            }
        }
    });
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            match line {
                Ok(line) => match parse_event_line(&line) {
                    Ok(value) => {
                        let _ = sender.send(TaskEvent::Json(value));
                    }
                    Err(error) => {
                        let _ = sender.send(TaskEvent::Finished(Err(format!(
                            "模型下载输出无效：{error}"
                        ))));
                        return;
                    }
                },
                Err(error) => {
                    let _ = sender.send(TaskEvent::Finished(Err(error.to_string())));
                    return;
                }
            }
        }
        let status = loop {
            let result = wait_child
                .lock()
                .expect("CLI child lock poisoned")
                .try_wait();
            match result {
                Ok(Some(status)) => break Ok(status),
                Ok(None) => thread::sleep(Duration::from_millis(100)),
                Err(error) => break Err(error.to_string()),
            }
        };
        let result = status.and_then(|status| {
            if status.success() {
                Ok(())
            } else {
                let detail = stderr_text
                    .lock()
                    .expect("CLI stderr lock poisoned")
                    .trim()
                    .to_owned();
                if detail.is_empty() {
                    Err(format!("模型下载进程退出：{status}"))
                } else {
                    Err(format!("模型下载进程退出：{status}；{detail}"))
                }
            }
        });
        let _ = sender.send(TaskEvent::Finished(result));
    });
    Ok(CliTask { child, receiver })
}

fn base_command(python: &Path) -> Command {
    let mut command = Command::new(python);
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    command
}

fn parse_json_response(bytes: &[u8]) -> Result<Value> {
    let value: Value = serde_json::from_slice(bytes)?;
    require_schema_version(&value)?;
    Ok(value)
}

fn parse_event_line(line: &str) -> Result<Value> {
    let value: Value = serde_json::from_str(line)?;
    require_schema_version(&value)?;
    Ok(value)
}

fn require_schema_version(value: &Value) -> Result<()> {
    if value.get("schema_version").and_then(Value::as_u64) != Some(1) {
        bail!("不支持的 CLI JSON schema_version");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jsonl_parser_accepts_schema_one() {
        let value = parse_event_line(r#"{"schema_version":1,"event":"progress"}"#).unwrap();
        assert_eq!(value["event"], "progress");
    }

    #[test]
    fn jsonl_parser_rejects_missing_or_future_schema() {
        assert!(parse_event_line(r#"{"event":"progress"}"#).is_err());
        assert!(parse_event_line(r#"{"schema_version":2}"#).is_err());
    }

    #[cfg(windows)]
    #[test]
    fn cancellation_terminates_the_cli_child() {
        let child = Command::new("cmd.exe")
            .args(["/C", "ping -n 30 127.0.0.1 >nul"])
            .spawn()
            .unwrap();
        let child = Arc::new(Mutex::new(child));
        let (_sender, receiver) = mpsc::channel();
        let task = CliTask {
            child: Arc::clone(&child),
            receiver,
        };

        task.cancel().unwrap();
        let status = child.lock().unwrap().wait().unwrap();
        assert!(!status.success());
    }
}
