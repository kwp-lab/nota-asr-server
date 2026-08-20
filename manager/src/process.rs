use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
use uuid::Uuid;

#[cfg(windows)]
use std::os::windows::io::AsRawHandle;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
#[cfg(windows)]
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
    SetInformationJobObject,
};
#[cfg(windows)]
use windows_sys::Win32::System::Threading::{CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW};

pub struct ServerProcess {
    child: Child,
    #[cfg(windows)]
    job: HANDLE,
    token: String,
    host: String,
    port: u16,
}

impl ServerProcess {
    pub fn start(
        python: &Path,
        config: &Path,
        log_dir: &Path,
        host: &str,
        port: u16,
    ) -> Result<Self> {
        fs::create_dir_all(log_dir)?;
        let log_path = log_dir.join("server.log");
        rotate_logs(&log_path, 5 * 1024 * 1024, 3)?;
        let stdout = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)?;
        let stderr = stdout.try_clone()?;
        let token = Uuid::new_v4().to_string();
        let mut command = Command::new(python);
        command
            .args(["-m", "nota_asr_server.cli", "serve", "--config"])
            .arg(config)
            .env("NOTA_MANAGER_TOKEN", &token)
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr));
        #[cfg(windows)]
        command.creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP);
        let mut child = command.spawn().context("无法启动 Nota ASR Server")?;
        #[cfg(windows)]
        let job = match assign_kill_on_close_job(&child) {
            Ok(job) => job,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        Ok(Self {
            child,
            #[cfg(windows)]
            job,
            token,
            host: host.to_owned(),
            port,
        })
    }

    pub fn try_exit(&mut self) -> Result<Option<i32>> {
        Ok(self
            .child
            .try_wait()?
            .map(|status| status.code().unwrap_or(-1)))
    }

    pub fn stop(&mut self, timeout: Duration) -> Result<()> {
        let _ = request_shutdown(&self.host, self.port, &self.token);
        let started = Instant::now();
        while started.elapsed() < timeout {
            if self.child.try_wait()?.is_some() {
                return Ok(());
            }
            thread::sleep(Duration::from_millis(100));
        }
        self.child.kill()?;
        let _ = self.child.wait();
        Ok(())
    }
}

impl Drop for ServerProcess {
    fn drop(&mut self) {
        let _ = self.stop(Duration::from_secs(2));
        #[cfg(windows)]
        unsafe {
            if !self.job.is_null() {
                CloseHandle(self.job);
            }
        }
    }
}

pub fn health_check(host: &str, port: u16) -> bool {
    let host = if matches!(host, "0.0.0.0" | "::") {
        "127.0.0.1"
    } else {
        host
    };
    let Ok(address) = (host, port)
        .to_socket_addrs()
        .ok()
        .and_then(|mut a| a.next())
        .ok_or(())
    else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(
            format!("GET /health HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n").as_bytes(),
        )
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok()
        && response.starts_with("HTTP/1.1 200")
        && response.contains("nota-asr-server")
}

fn request_shutdown(host: &str, port: u16, token: &str) -> Result<()> {
    let host = if matches!(host, "0.0.0.0" | "::") {
        "127.0.0.1"
    } else {
        host
    };
    let mut stream = TcpStream::connect((host, port)).context("Server 未监听")?;
    stream.write_all(
        format!(
            "POST /internal/manager/shutdown HTTP/1.1\r\nHost: {host}\r\nX-Nota-Manager-Token: {token}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        )
        .as_bytes(),
    )?;
    Ok(())
}

fn rotate_logs(path: &Path, max_bytes: u64, copies: usize) -> Result<()> {
    if path.metadata().map(|metadata| metadata.len()).unwrap_or(0) < max_bytes {
        return Ok(());
    }
    for index in (1..=copies).rev() {
        let source = if index == 1 {
            path.to_path_buf()
        } else {
            numbered_log(path, index - 1)
        };
        let destination = numbered_log(path, index);
        if destination.exists() {
            fs::remove_file(&destination)?;
        }
        if source.exists() {
            fs::rename(source, destination)?;
        }
    }
    Ok(())
}

fn numbered_log(path: &Path, index: usize) -> PathBuf {
    PathBuf::from(format!("{}.{}", path.display(), index))
}

#[cfg(windows)]
fn assign_kill_on_close_job(child: &Child) -> Result<HANDLE> {
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            bail!("无法创建 Windows Job Object");
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let configured = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const _,
            std::mem::size_of_val(&info) as u32,
        );
        let assigned = AssignProcessToJobObject(job, child.as_raw_handle() as HANDLE);
        if configured == 0 || assigned == 0 {
            CloseHandle(job);
            bail!("无法将 Server 加入 Windows Job Object");
        }
        Ok(job)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rotates_bounded_log_files() {
        let root = std::env::temp_dir().join(format!("nota-logs-{}", Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let log = root.join("server.log");
        fs::write(&log, b"123456").unwrap();
        rotate_logs(&log, 4, 2).unwrap();
        assert!(root.join("server.log.1").is_file());
        assert!(!log.exists());
        fs::remove_dir_all(root).unwrap();
    }
}
