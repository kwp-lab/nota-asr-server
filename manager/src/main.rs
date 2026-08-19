#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod cli;
mod config;
mod log_view;
mod process;

use std::ffi::OsStr;
use std::fs;
use std::os::windows::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::sync::{Arc, mpsc};
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
use cli::{CliTask, ModelInfo, TaskEvent};
use config::ManagerConfig;
use directories::ProjectDirs;
use eframe::egui;
use log_view::LogView;
use process::{ServerProcess, health_check};
use single_instance::SingleInstance;
use toml_edit::DocumentMut;
use tray_icon::menu::{Menu, MenuEvent, MenuId, MenuItem};
use tray_icon::{Icon, MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};
use windows_sys::Win32::UI::Shell::ShellExecuteW;
use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

const MODELS: [&str; 3] = ["sensevoice", "paraformer", "fun-asr-nano"];
const INSTALLED_MODE_MARKER: &str = ".nota-installed";
const CJK_FONT_NAME: &str = "nota-system-cjk";
const CJK_FONT_CANDIDATES: [&str; 5] = [
    "msyh.ttc",
    "Deng.ttf",
    "simhei.ttf",
    "simsun.ttc",
    "msyhl.ttc",
];
const MANAGER_ICON_32: &[u8] = include_bytes!("../assets/manager-icon-32.rgba");
const MANAGER_ICON_256: &[u8] = include_bytes!("../assets/manager-icon-256.rgba");
const LOG_LINE_LIMIT: usize = 2_000;

struct RuntimePaths {
    root: PathBuf,
    python: PathBuf,
    config: PathBuf,
    executable: PathBuf,
}

struct TrayState {
    _icon: TrayIcon,
    show_id: MenuId,
    exit_id: MenuId,
}

struct NotaManagerApp {
    paths: RuntimePaths,
    config: ManagerConfig,
    port_input: String,
    saved_model_root: PathBuf,
    document: DocumentMut,
    models: Vec<ModelInfo>,
    server: Option<ServerProcess>,
    download: Option<CliTask>,
    download_status: String,
    download_progress: f32,
    migration: Option<mpsc::Receiver<Result<PathBuf, String>>>,
    server_status: String,
    interaction_status: String,
    interaction_status_is_error: bool,
    diagnostic: String,
    nano_acknowledged: bool,
    last_health_check: Instant,
    healthy: bool,
    external_server: bool,
    allow_close: bool,
    first_run: bool,
    tray: TrayState,
    icon_texture: egui::TextureHandle,
    log_view: LogView,
    log_filter: String,
    log_auto_scroll: bool,
    log_hide_health_checks: bool,
    log_error: Option<String>,
    last_log_refresh: Instant,
}

impl NotaManagerApp {
    fn new(paths: RuntimePaths, start_hidden: bool, context: &egui::Context) -> Result<Self> {
        let first_run = ensure_config(&paths)?;
        let (config, document) = ManagerConfig::load(&paths.config)?;
        write_uninstall_metadata(&paths.config, &config)?;
        let port_input = config.port.to_string();
        let saved_model_root = config.model_root.clone();
        let models = cli::list_models(&paths.python, &paths.config).unwrap_or_default();
        let tray = create_tray()?;
        let log_view = LogView::new(server_log_path(&config), LOG_LINE_LIMIT);
        let icon_texture = load_manager_icon_texture(context);
        let mut app = Self {
            paths,
            config,
            port_input,
            saved_model_root,
            document,
            models,
            server: None,
            download: None,
            download_status: String::new(),
            download_progress: 0.0,
            migration: None,
            server_status: "Server 已停止".to_owned(),
            interaction_status: "就绪".to_owned(),
            interaction_status_is_error: false,
            diagnostic: String::new(),
            nano_acknowledged: false,
            last_health_check: Instant::now() - Duration::from_secs(2),
            healthy: false,
            external_server: false,
            allow_close: false,
            first_run,
            tray,
            icon_texture,
            log_view,
            log_filter: String::new(),
            log_auto_scroll: true,
            log_hide_health_checks: true,
            log_error: None,
            last_log_refresh: Instant::now() - Duration::from_secs(1),
        };
        if !app.first_run && app.config.auto_start_server {
            let _ = app.start_server();
        }
        if start_hidden {
            app.set_interaction_status("Manager 已在托盘运行");
        }
        Ok(app)
    }

    fn set_interaction_status(&mut self, message: impl Into<String>) {
        self.interaction_status = message.into();
        self.interaction_status_is_error = false;
    }

    fn set_interaction_error(&mut self, error: impl std::fmt::Display) {
        self.interaction_status = error.to_string();
        self.interaction_status_is_error = true;
    }

    fn refresh_models(&mut self) -> bool {
        match cli::list_models(&self.paths.python, &self.paths.config) {
            Ok(models) => {
                self.models = models;
                true
            }
            Err(error) => {
                self.set_interaction_error(error);
                false
            }
        }
    }

    fn save_config(&mut self) {
        let port = match parse_port(&self.port_input) {
            Ok(port) => port,
            Err(error) => {
                self.set_interaction_error(error);
                return;
            }
        };
        self.config.port = port;
        match self.config.save(&self.paths.config, &mut self.document) {
            Ok(()) => {
                self.saved_model_root = self.config.model_root.clone();
                self.log_view.set_path(server_log_path(&self.config));
                self.first_run = false;
                if let Err(error) = write_uninstall_metadata(&self.paths.config, &self.config) {
                    self.set_interaction_error(error);
                    return;
                }
                if let Err(error) = configure_startup(
                    self.config.start_on_login,
                    &self.paths.executable,
                    &self.paths.config,
                ) {
                    self.set_interaction_error(error);
                } else {
                    self.set_interaction_status("设置已保存；运行中的 Server 需要重启后生效");
                }
            }
            Err(error) => self.set_interaction_error(error),
        }
    }

    fn start_model_migration(&mut self) {
        if self.migration.is_some() {
            self.set_interaction_status("模型迁移已经在进行中");
            return;
        }
        if self.server.is_some() {
            self.set_interaction_status("迁移模型前请先停止 Server");
            return;
        }
        let source = self.saved_model_root.clone();
        let destination = self.config.model_root.clone();
        if source == destination {
            self.set_interaction_status("模型目录没有变化");
            return;
        }
        if !source.is_dir() {
            self.set_interaction_error("原模型目录不存在；请选择“使用新目录”");
            return;
        }
        if destination.exists()
            && destination
                .read_dir()
                .is_ok_and(|mut entries| entries.next().is_some())
        {
            self.set_interaction_error("目标模型目录必须为空，避免覆盖已有文件");
            return;
        }

        let temporary_config = self
            .paths
            .config
            .with_file_name(format!(".model-migration-{}.toml", uuid::Uuid::new_v4()));
        let mut migration_document = self.document.clone();
        let mut migration_config = self.config.clone();
        migration_config.model_root = destination.clone();
        if let Err(error) = migration_config.save(&temporary_config, &mut migration_document) {
            self.set_interaction_error(error);
            return;
        }
        let python = self.paths.python.clone();
        let aliases: Vec<String> = self
            .models
            .iter()
            .filter(|model| model.installed)
            .map(|model| model.alias.clone())
            .collect();
        let (sender, receiver) = mpsc::channel();
        self.migration = Some(receiver);
        self.set_interaction_status("正在迁移并验证模型；原目录会保留");
        thread::spawn(move || {
            let result = migrate_model_directory(
                &source,
                &destination,
                &python,
                &temporary_config,
                &aliases,
            )
            .map_err(|error| error.to_string());
            let _ = fs::remove_file(&temporary_config);
            let _ = sender.send(result.map(|()| destination));
        });
    }

    fn poll_migration(&mut self) {
        let Some(receiver) = &self.migration else {
            return;
        };
        match receiver.try_recv() {
            Ok(Ok(destination)) => {
                self.migration = None;
                self.config.model_root = destination;
                self.save_config();
                self.set_interaction_status("模型迁移及校验完成；原目录仍保留，可确认后手动删除");
                self.refresh_models();
            }
            Ok(Err(error)) => {
                self.migration = None;
                self.config.model_root = self.saved_model_root.clone();
                self.set_interaction_error(format!("模型迁移失败：{error}；原配置和原目录未改变"));
            }
            Err(mpsc::TryRecvError::Empty) => {}
            Err(mpsc::TryRecvError::Disconnected) => {
                self.migration = None;
                self.config.model_root = self.saved_model_root.clone();
                self.set_interaction_error("模型迁移线程异常结束；原配置和原目录未改变");
            }
        }
    }

    fn start_server(&mut self) -> Result<()> {
        if self.server.is_some() {
            return Ok(());
        }
        if health_check(&self.config.host, self.config.port) {
            self.external_server = true;
            self.healthy = true;
            self.server_status = "检测到外部管理的 Nota ASR Server".to_owned();
            bail!("目标端口已有 Nota ASR Server；Manager 不会接管该进程");
        }
        let preload_installed = self
            .models
            .iter()
            .find(|model| model.alias == self.config.preload_model)
            .is_some_and(|model| model.installed);
        if !preload_installed {
            bail!("请先安装预加载模型 {}", self.config.preload_model);
        }
        let log_dir = self.config.data_root.join("logs");
        self.server = Some(ServerProcess::start(
            &self.paths.python,
            &self.paths.config,
            &log_dir,
            &self.config.host,
            self.config.port,
        )?);
        self.server_status = "Server 正在启动".to_owned();
        self.external_server = false;
        Ok(())
    }

    fn stop_server(&mut self) -> Result<()> {
        if let Some(mut server) = self.server.take() {
            server.stop(Duration::from_secs(60))?;
        }
        self.healthy = false;
        self.server_status = "Server 已停止".to_owned();
        Ok(())
    }

    fn restart_server(&mut self) -> Result<()> {
        self.stop_server()?;
        self.start_server()
    }

    fn start_download(&mut self, model: &ModelInfo) {
        if self.download.is_some() {
            self.set_interaction_status("已有模型正在下载");
            return;
        }
        if model.requires_license_acknowledgement && !self.nano_acknowledged {
            self.set_interaction_error("下载 Nano 前必须确认其上游许可证尚未明确声明");
            return;
        }
        match cli::start_model_install(
            self.paths.python.clone(),
            self.paths.config.clone(),
            model.alias.clone(),
            self.nano_acknowledged,
        ) {
            Ok(task) => {
                self.download = Some(task);
                self.download_status = format!("正在安装 {}", model.display_name);
                self.download_progress = 0.0;
                self.set_interaction_status(format!("已开始下载 {}", model.display_name));
            }
            Err(error) => self.set_interaction_error(error),
        }
    }

    fn poll_download(&mut self) {
        let Some(task) = &self.download else {
            return;
        };
        let mut finished = None;
        let mut reported_error = None;
        while let Ok(event) = task.receiver.try_recv() {
            match event {
                TaskEvent::Json(value) => {
                    if let Some(name) = value["event"].as_str() {
                        self.download_status = name.to_owned();
                    }
                    let downloaded = value["downloaded_bytes"].as_u64().unwrap_or(0);
                    let total = value["total_bytes"].as_u64().unwrap_or(0);
                    if total > 0 {
                        self.download_progress =
                            (downloaded as f64 / total as f64).clamp(0.0, 1.0) as f32;
                    }
                    if let Some(error) = value["error"].as_str() {
                        reported_error = Some(error.to_owned());
                    }
                }
                TaskEvent::Finished(result) => finished = Some(result),
            }
        }
        if let Some(error) = reported_error {
            self.set_interaction_error(error);
        }
        if let Some(result) = finished {
            self.download = None;
            match result {
                Ok(()) => {
                    self.download_status = "模型安装完成".to_owned();
                    self.download_progress = 1.0;
                    self.refresh_models();
                    self.set_interaction_status("模型安装完成");
                }
                Err(error) => {
                    self.download_status = "模型安装失败".to_owned();
                    self.set_interaction_error(error);
                }
            }
        }
    }

    fn poll_server(&mut self) {
        if self.last_health_check.elapsed() < Duration::from_secs(1) {
            return;
        }
        self.last_health_check = Instant::now();
        if let Some(server) = &mut self.server {
            match server.try_exit() {
                Ok(Some(code)) => {
                    self.server = None;
                    self.healthy = false;
                    self.server_status = format!("Server 异常退出（代码 {code}）");
                    self.set_interaction_error("Server 意外退出；请查看实时日志或日志目录");
                    return;
                }
                Err(error) => {
                    self.server_status = "Server 状态检查失败".to_owned();
                    self.set_interaction_error(error);
                    return;
                }
                Ok(None) => {}
            }
        }
        self.healthy = health_check(&self.config.host, self.config.port);
        self.external_server = self.healthy && self.server.is_none();
        if self.healthy {
            self.server_status = if self.external_server {
                "检测到外部管理的 Nota ASR Server".to_owned()
            } else {
                "Server 正在运行".to_owned()
            };
        }
    }

    fn poll_log(&mut self) {
        if self.last_log_refresh.elapsed() < Duration::from_millis(200) {
            return;
        }
        self.last_log_refresh = Instant::now();
        match self.log_view.refresh() {
            Ok(_) => self.log_error = None,
            Err(error) => self.log_error = Some(error.to_string()),
        }
    }

    fn reload_config(&mut self) {
        match ManagerConfig::load(&self.paths.config) {
            Ok((config, document)) => {
                self.config = config;
                self.port_input = self.config.port.to_string();
                self.saved_model_root = self.config.model_root.clone();
                self.log_view.set_path(server_log_path(&self.config));
                self.document = document;
                self.refresh_models();
                self.set_interaction_status("已重新加载配置");
            }
            Err(error) => self.set_interaction_error(error),
        }
    }

    fn process_tray(&mut self, ctx: &egui::Context) {
        while let Ok(event) = TrayIconEvent::receiver().try_recv() {
            if matches!(
                event,
                TrayIconEvent::Click {
                    button,
                    button_state,
                    ..
                } if is_window_reveal_click(button, button_state)
            ) {
                ctx.send_viewport_cmd(egui::ViewportCommand::Visible(true));
                ctx.send_viewport_cmd(egui::ViewportCommand::Focus);
            }
        }
        while let Ok(event) = MenuEvent::receiver().try_recv() {
            if event.id == self.tray.show_id {
                ctx.send_viewport_cmd(egui::ViewportCommand::Visible(true));
                ctx.send_viewport_cmd(egui::ViewportCommand::Focus);
            } else if event.id == self.tray.exit_id {
                self.allow_close = true;
                ctx.send_viewport_cmd(egui::ViewportCommand::Close);
            }
        }
    }

    fn show_header(&mut self, ui: &mut egui::Ui) {
        section_frame().show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.add(egui::Image::new((
                    self.icon_texture.id(),
                    egui::vec2(38.0, 38.0),
                )));
                ui.add_space(4.0);
                ui.vertical(|ui| {
                    ui.label(
                        egui::RichText::new("Nota ASR Manager")
                            .size(20.0)
                            .strong()
                            .color(text_primary()),
                    );
                    ui.horizontal(|ui| {
                        ui.colored_label(self.server_status_color(), "●");
                        ui.label(
                            egui::RichText::new(&self.server_status)
                                .size(12.5)
                                .color(text_secondary()),
                        );
                        ui.label(
                            egui::RichText::new(format!(
                                "{}:{}",
                                self.config.host, self.config.port
                            ))
                            .size(12.5)
                            .color(text_muted()),
                        );
                    });
                });
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    let stop_button = if self.server.is_some() {
                        primary_button("停止 Server", 98.0)
                    } else {
                        secondary_button("停止 Server", 98.0)
                    };
                    if ui.add_enabled(self.server.is_some(), stop_button).clicked()
                        && let Err(error) = self.stop_server()
                    {
                        self.server_status = "Server 停止失败".to_owned();
                        self.set_interaction_error(error);
                    }
                    if ui
                        .add_enabled(self.server.is_some(), secondary_button("重启 Server", 98.0))
                        .clicked()
                        && let Err(error) = self.restart_server()
                    {
                        self.server_status = "Server 重启失败".to_owned();
                        self.set_interaction_error(error);
                    }
                    let start_button = if self.server.is_none() && !self.external_server {
                        primary_button("启动 Server", 108.0)
                    } else {
                        secondary_button("启动 Server", 108.0)
                    };
                    if ui
                        .add_enabled(self.server.is_none() && !self.external_server, start_button)
                        .clicked()
                        && let Err(error) = self.start_server()
                    {
                        if !self.external_server {
                            self.server_status = "Server 启动失败".to_owned();
                        }
                        self.set_interaction_error(error);
                    }
                });
            });
        });
    }

    fn show_control_panel(&mut self, ui: &mut egui::Ui) {
        egui::ScrollArea::vertical()
            .id_salt("manager-controls")
            .auto_shrink([false, false])
            .show(ui, |ui| {
                if self.first_run {
                    egui::Frame::new()
                        .fill(egui::Color32::from_rgb(24, 37, 55))
                        .stroke(egui::Stroke::new(1.0, egui::Color32::from_rgb(48, 86, 132)))
                        .corner_radius(8)
                        .inner_margin(12)
                        .show(ui, |ui| {
                            ui.strong("首次设置");
                            ui.label(
                                egui::RichText::new(
                                    "确认数据与模型目录后再下载模型；默认推荐 SenseVoice。",
                                )
                                .color(text_secondary()),
                            );
                        });
                    ui.add_space(10.0);
                }
                self.show_models(ui);
                ui.add_space(10.0);
                self.show_settings(ui);
                if !self.diagnostic.is_empty() {
                    ui.add_space(10.0);
                    section_frame().show(ui, |ui| {
                        egui::CollapsingHeader::new(egui::RichText::new("诊断结果").strong())
                            .default_open(true)
                            .show(ui, |ui| {
                                ui.add(
                                    egui::TextEdit::multiline(&mut self.diagnostic)
                                        .desired_rows(9)
                                        .desired_width(f32::INFINITY)
                                        .code_editor(),
                                );
                            });
                    });
                }
            });
    }

    fn show_settings(&mut self, ui: &mut egui::Ui) {
        section_frame().show(ui, |ui| {
            egui::CollapsingHeader::new(egui::RichText::new("设置").strong())
                .default_open(false)
                .show(ui, |ui| {
                    if self.config.host != "127.0.0.1" {
                        ui.colored_label(
                            warning_color(),
                            "当前地址不是 loopback；Manager 仅推荐本机访问。",
                        );
                    }
                    ui.add_space(4.0);
                    port_row(ui, &mut self.port_input, &mut self.config.port);
                    path_row(ui, "模型目录", &mut self.config.model_root);
                    path_row(ui, "数据目录", &mut self.config.data_root);
                    model_combo(
                        ui,
                        "默认模型",
                        "default-model",
                        &mut self.config.default_model,
                    );
                    model_combo(
                        ui,
                        "预加载模型",
                        "preload-model",
                        &mut self.config.preload_model,
                    );
                    ui.add_space(4.0);
                    ui.horizontal_wrapped(|ui| {
                        ui.checkbox(&mut self.config.start_on_login, "登录后启动 Manager");
                        ui.checkbox(
                            &mut self.config.auto_start_server,
                            "Manager 启动后自动启动 Server",
                        );
                    });
                    ui.add_space(8.0);
                    ui.horizontal_wrapped(|ui| {
                        if self.config.model_root != self.saved_model_root {
                            if ui.button("使用新目录").clicked() {
                                self.save_config();
                                self.refresh_models();
                            }
                            if ui
                                .add_enabled(
                                    self.migration.is_none(),
                                    egui::Button::new("迁移已有模型"),
                                )
                                .clicked()
                            {
                                self.start_model_migration();
                            }
                        } else if ui.add(primary_button("保存设置", 92.0)).clicked() {
                            self.save_config();
                        }
                        if ui.add(secondary_button("打开配置文件", 108.0)).clicked() {
                            match open_in_explorer(&self.paths.config) {
                                Ok(target) => {
                                    self.set_interaction_status(format!(
                                        "已打开配置目录：{}",
                                        target.display()
                                    ));
                                }
                                Err(error) => self.set_interaction_error(error),
                            }
                        }
                        if ui.add(secondary_button("重新加载", 86.0)).clicked() {
                            self.reload_config();
                        }
                        if ui.add(secondary_button("诊断", 70.0)).clicked() {
                            match cli::run_doctor(&self.paths.python, &self.paths.config) {
                                Ok(value) => {
                                    self.diagnostic =
                                        serde_json::to_string_pretty(&value).unwrap_or_default();
                                    self.set_interaction_status("诊断已完成");
                                }
                                Err(error) => {
                                    self.diagnostic = error.to_string();
                                    self.set_interaction_error("诊断未通过；请查看诊断结果");
                                }
                            }
                        }
                    });
                });
        });
    }

    fn show_models(&mut self, ui: &mut egui::Ui) {
        section_frame().show(ui, |ui| {
            let refresh = section_heading(ui, "模型", Some("刷新状态"));
            if refresh && self.refresh_models() {
                self.set_interaction_status("模型状态已刷新");
            }
            ui.add_space(6.0);
            let models = self.models.clone();
            for (index, model) in models.into_iter().enumerate() {
                if index > 0 {
                    ui.separator();
                }
                ui.horizontal(|ui| {
                    ui.colored_label(
                        if model.installed {
                            success_color()
                        } else {
                            text_muted()
                        },
                        "●",
                    );
                    ui.vertical(|ui| {
                        ui.label(egui::RichText::new(&model.display_name).strong());
                        ui.label(
                            egui::RichText::new(format!(
                                "{}  ·  {}  ·  {}",
                                if model.installed {
                                    "已安装"
                                } else {
                                    "未安装"
                                },
                                format_bytes(model.download_bytes),
                                model.license
                            ))
                            .size(11.5)
                            .color(text_muted()),
                        );
                    });
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if model.alias == self.config.preload_model {
                            preload_badge(ui, self.healthy);
                        }
                        if !model.installed
                            && ui
                                .add_enabled(
                                    self.download.is_none()
                                        && self.migration.is_none()
                                        && self.config.model_root == self.saved_model_root,
                                    egui::Button::new("下载"),
                                )
                                .clicked()
                        {
                            self.start_download(&model);
                        }
                    });
                });
                if model.requires_license_acknowledgement && !model.installed {
                    ui.checkbox(
                        &mut self.nano_acknowledged,
                        "我了解该模型的上游许可证目前未明确声明",
                    );
                }
            }
            if self.download.is_some() {
                ui.add_space(8.0);
                ui.add(
                    egui::ProgressBar::new(self.download_progress)
                        .show_percentage()
                        .corner_radius(4),
                );
                ui.horizontal(|ui| {
                    ui.label(
                        egui::RichText::new(&self.download_status)
                            .size(12.0)
                            .color(text_secondary()),
                    );
                    if ui.button("取消下载").clicked()
                        && let Some(task) = &self.download
                    {
                        let _ = task.cancel();
                    }
                });
            }
        });
    }

    fn show_log_panel(&mut self, ui: &mut egui::Ui) {
        section_frame().show(ui, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.label(
                    egui::RichText::new("实时日志")
                        .size(17.0)
                        .strong()
                        .color(text_primary()),
                );
                ui.add_space(10.0);
                ui.add_sized(
                    [210.0, 30.0],
                    egui::TextEdit::singleline(&mut self.log_filter)
                        .hint_text("筛选日志")
                        .vertical_align(egui::Align::Center),
                );
                ui.checkbox(&mut self.log_auto_scroll, "自动滚动");
                ui.checkbox(&mut self.log_hide_health_checks, "隐藏健康检查");
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.button("打开日志目录").clicked() {
                        let log_directory = self.config.data_root.join("logs");
                        match open_in_explorer(&log_directory) {
                            Ok(target) => {
                                self.set_interaction_status(format!(
                                    "已打开日志目录：{}",
                                    target.display()
                                ));
                            }
                            Err(error) => self.set_interaction_error(error),
                        }
                    }
                    if ui.button("清空显示").clicked() {
                        match self.log_view.clear_view() {
                            Ok(()) => {
                                self.set_interaction_status("已清空当前日志显示；日志文件未删除")
                            }
                            Err(error) => {
                                self.log_error = Some(error.to_string());
                                self.set_interaction_error(error);
                            }
                        }
                    }
                });
            });
            ui.add_space(6.0);
            ui.separator();
            let filter = self.log_filter.to_lowercase();
            let lines: Vec<String> = self
                .log_view
                .lines()
                .filter(|line| !self.log_hide_health_checks || !is_health_check_log(line))
                .filter(|line| filter.is_empty() || line.to_lowercase().contains(&filter))
                .map(ToOwned::to_owned)
                .collect();
            // Reserve the panel header, separators, footer metadata, spacing,
            // and frame margins so the global status bar remains pinned below
            // the workspace instead of being pushed beyond the viewport.
            let log_height = (ui.available_height() - 94.0).max(160.0);
            egui::Frame::new()
                .fill(log_background())
                .corner_radius(6)
                .inner_margin(12)
                .show(ui, |ui| {
                    ui.set_min_height(log_height);
                    egui::ScrollArea::both()
                        .id_salt("server-live-log")
                        .auto_shrink([false, false])
                        .stick_to_bottom(self.log_auto_scroll)
                        .max_height(log_height)
                        .show(ui, |ui| {
                            if lines.is_empty() {
                                ui.label(
                                    egui::RichText::new(if self.log_filter.is_empty() {
                                        "尚无日志。启动 Server 后，输出会实时显示在这里。"
                                    } else {
                                        "没有匹配当前筛选条件的日志。"
                                    })
                                    .color(text_muted()),
                                );
                            } else {
                                for line in &lines {
                                    ui.add(
                                        egui::Label::new(
                                            egui::RichText::new(line)
                                                .monospace()
                                                .size(12.5)
                                                .color(log_line_color(line)),
                                        )
                                        .selectable(true)
                                        .extend(),
                                    );
                                }
                            }
                        });
                });
            ui.add_space(6.0);
            ui.horizontal(|ui| {
                if let Some(error) = &self.log_error {
                    ui.colored_label(error_color(), error);
                } else {
                    ui.label(
                        egui::RichText::new(format!(
                            "{} 行  ·  {}",
                            self.log_view.line_count(),
                            self.log_view.path().display()
                        ))
                        .size(11.5)
                        .color(text_muted()),
                    );
                }
            });
        });
    }

    fn show_global_status_bar(&self, ui: &mut egui::Ui) {
        let response = egui::Frame::new()
            .fill(surface_color())
            .inner_margin(egui::Margin::symmetric(12, 5))
            .show(ui, |ui| {
                ui.set_min_width(ui.available_width());
                ui.horizontal_centered(|ui| {
                    ui.spacing_mut().item_spacing.x = 6.0;
                    let indicator_color = if self.interaction_status_is_error {
                        error_color()
                    } else {
                        accent_color()
                    };
                    let (indicator_rect, _) =
                        ui.allocate_exact_size(egui::vec2(8.0, 20.0), egui::Sense::hover());
                    ui.painter()
                        .circle_filled(indicator_rect.center(), 3.0, indicator_color);
                    ui.add(
                        egui::Label::new(
                            egui::RichText::new(&self.interaction_status)
                                .size(11.5)
                                .color(if self.interaction_status_is_error {
                                    error_color()
                                } else {
                                    text_secondary()
                                }),
                        )
                        .truncate(),
                    )
                    .on_hover_text(&self.interaction_status);
                });
            });
        ui.painter().hline(
            response.response.rect.x_range(),
            response.response.rect.top(),
            egui::Stroke::new(1.0, border_color()),
        );
    }

    fn server_status_color(&self) -> egui::Color32 {
        if self.healthy {
            success_color()
        } else if self.external_server {
            warning_color()
        } else {
            text_muted()
        }
    }
}

impl eframe::App for NotaManagerApp {
    fn logic(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.process_tray(ctx);
        self.poll_download();
        self.poll_migration();
        self.poll_server();
        self.poll_log();
        if ctx.input(|input| input.viewport().close_requested()) && !self.allow_close {
            ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
            ctx.send_viewport_cmd(egui::ViewportCommand::Visible(false));
        }
        ctx.request_repaint_after(Duration::from_millis(250));
    }

    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        egui::Frame::central_panel(ui.style())
            .fill(app_background())
            .inner_margin(0)
            .show(ui, |ui| {
                egui::Frame::new()
                    .inner_margin(egui::Margin {
                        left: 12,
                        right: 12,
                        top: 12,
                        bottom: 0,
                    })
                    .show(ui, |ui| {
                        self.show_header(ui);
                        ui.add_space(10.0);
                        let workspace_height = (ui.available_height() - 40.0).max(320.0);
                        let left_width = (ui.available_width() * 0.34).clamp(340.0, 410.0);
                        ui.horizontal_top(|ui| {
                            ui.allocate_ui_with_layout(
                                egui::vec2(left_width, workspace_height),
                                egui::Layout::top_down(egui::Align::Min),
                                |ui| self.show_control_panel(ui),
                            );
                            ui.add_space(10.0);
                            ui.allocate_ui_with_layout(
                                egui::vec2(ui.available_width(), workspace_height),
                                egui::Layout::top_down(egui::Align::Min),
                                |ui| self.show_log_panel(ui),
                            );
                        });
                    });
                self.show_global_status_bar(ui);
            });
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        let _ = self.stop_server();
    }
}

fn main() -> eframe::Result {
    if let Some(config) = delete_user_data_request() {
        std::process::exit(match delete_user_data(&config) {
            Ok(()) => 0,
            Err(error) => {
                eprintln!("{error:#}");
                2
            }
        });
    }
    let instance = SingleInstance::new("kwp-lab.NotaASRManager").expect("无法创建单实例锁");
    if !instance.is_single() {
        return Ok(());
    }
    let (paths, start_hidden) = runtime_paths().expect("无法确定 Runtime 路径");
    let _ = ManagerConfig::load(&paths.config)
        .and_then(|(config, _)| write_uninstall_metadata(&paths.config, &config));
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Nota ASR Manager")
            .with_inner_size([1180.0, 980.0])
            .with_min_inner_size([980.0, 720.0])
            .with_icon(manager_icon_data_256())
            .with_visible(!start_hidden),
        ..Default::default()
    };
    eframe::run_native(
        "Nota ASR Manager",
        options,
        Box::new(move |creation| {
            let font_error = install_system_cjk_font(&creation.egui_ctx).err();
            configure_manager_style(&creation.egui_ctx);
            let mut app = NotaManagerApp::new(paths, start_hidden, &creation.egui_ctx)
                .expect("Manager 初始化失败");
            if let Some(error) = font_error {
                app.set_interaction_error(format!(
                    "Chinese UI font unavailable; install Windows Simplified Chinese supplemental fonts: {error:#}"
                ));
            }
            Ok(Box::new(app))
        }),
    )
}

fn manager_icon_data_256() -> egui::IconData {
    debug_assert_eq!(MANAGER_ICON_256.len(), 256 * 256 * 4);
    egui::IconData {
        rgba: MANAGER_ICON_256.to_vec(),
        width: 256,
        height: 256,
    }
}

fn load_manager_icon_texture(context: &egui::Context) -> egui::TextureHandle {
    let image = egui::ColorImage::from_rgba_unmultiplied([256, 256], MANAGER_ICON_256);
    context.load_texture("nota-manager-icon", image, egui::TextureOptions::LINEAR)
}

fn configure_manager_style(context: &egui::Context) {
    context.set_theme(egui::Theme::Dark);
    let mut style = (*context.style_of(egui::Theme::Dark)).clone();
    style.spacing.item_spacing = egui::vec2(8.0, 7.0);
    style.spacing.button_padding = egui::vec2(12.0, 7.0);
    style.spacing.interact_size.y = 30.0;
    style.visuals = egui::Visuals::dark();
    style.visuals.panel_fill = app_background();
    style.visuals.window_fill = surface_color();
    style.visuals.extreme_bg_color = log_background();
    style.visuals.faint_bg_color = egui::Color32::from_rgb(31, 31, 33);
    style.visuals.selection.bg_fill = accent_color();
    style.visuals.selection.stroke = egui::Stroke::new(1.0, egui::Color32::WHITE);
    style.visuals.widgets.noninteractive.bg_fill = surface_color();
    style.visuals.widgets.noninteractive.fg_stroke = egui::Stroke::new(1.0, text_secondary());
    style.visuals.widgets.inactive.bg_fill = egui::Color32::from_rgb(44, 44, 47);
    style.visuals.widgets.inactive.weak_bg_fill = egui::Color32::from_rgb(44, 44, 47);
    style.visuals.widgets.inactive.fg_stroke = egui::Stroke::new(1.0, text_primary());
    style.visuals.widgets.hovered.bg_fill = egui::Color32::from_rgb(55, 55, 59);
    style.visuals.widgets.hovered.weak_bg_fill = egui::Color32::from_rgb(55, 55, 59);
    style.visuals.widgets.active.bg_fill = egui::Color32::from_rgb(65, 65, 70);
    style.visuals.widgets.open.bg_fill = egui::Color32::from_rgb(48, 48, 52);
    style.visuals.widgets.noninteractive.corner_radius = 6.into();
    style.visuals.widgets.inactive.corner_radius = 6.into();
    style.visuals.widgets.hovered.corner_radius = 6.into();
    style.visuals.widgets.active.corner_radius = 6.into();
    style.visuals.widgets.open.corner_radius = 6.into();
    style.text_styles.insert(
        egui::TextStyle::Heading,
        egui::FontId::new(20.0, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Body,
        egui::FontId::new(13.5, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Button,
        egui::FontId::new(13.0, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Small,
        egui::FontId::new(11.5, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Monospace,
        egui::FontId::new(12.5, egui::FontFamily::Monospace),
    );
    context.set_style_of(egui::Theme::Dark, style);
}

fn app_background() -> egui::Color32 {
    egui::Color32::from_rgb(23, 23, 23)
}

fn surface_color() -> egui::Color32 {
    egui::Color32::from_rgb(29, 29, 31)
}

fn log_background() -> egui::Color32 {
    egui::Color32::from_rgb(17, 17, 18)
}

fn border_color() -> egui::Color32 {
    egui::Color32::from_rgb(58, 58, 62)
}

fn text_primary() -> egui::Color32 {
    egui::Color32::from_rgb(243, 243, 244)
}

fn text_secondary() -> egui::Color32 {
    egui::Color32::from_rgb(190, 190, 195)
}

fn text_muted() -> egui::Color32 {
    egui::Color32::from_rgb(132, 132, 139)
}

fn accent_color() -> egui::Color32 {
    egui::Color32::from_rgb(36, 107, 230)
}

fn success_color() -> egui::Color32 {
    egui::Color32::from_rgb(92, 199, 103)
}

fn warning_color() -> egui::Color32 {
    egui::Color32::from_rgb(229, 176, 62)
}

fn error_color() -> egui::Color32 {
    egui::Color32::from_rgb(238, 92, 92)
}

fn section_frame() -> egui::Frame {
    egui::Frame::new()
        .fill(surface_color())
        .stroke(egui::Stroke::new(1.0, border_color()))
        .corner_radius(8)
        .inner_margin(12)
}

fn primary_button(text: &str, width: f32) -> egui::Button<'_> {
    egui::Button::new(
        egui::RichText::new(text)
            .strong()
            .color(egui::Color32::WHITE),
    )
    .fill(accent_color())
    .corner_radius(6)
    .min_size(egui::vec2(width, 32.0))
}

fn secondary_button(text: &str, width: f32) -> egui::Button<'_> {
    egui::Button::new(egui::RichText::new(text).color(text_primary()))
        .corner_radius(6)
        .min_size(egui::vec2(width, 32.0))
}

fn section_heading(ui: &mut egui::Ui, title: &str, action: Option<&str>) -> bool {
    let mut clicked = false;
    ui.horizontal(|ui| {
        ui.label(
            egui::RichText::new(title)
                .size(15.5)
                .strong()
                .color(text_primary()),
        );
        if let Some(action) = action {
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                clicked = ui.add(secondary_button(action, 82.0)).clicked();
            });
        }
    });
    clicked
}

fn preload_badge(ui: &mut egui::Ui, loaded: bool) {
    let (label, fill, text) = if loaded {
        (
            "已预加载",
            egui::Color32::from_rgb(24, 61, 42),
            success_color(),
        )
    } else {
        (
            "预加载",
            egui::Color32::from_rgb(32, 43, 58),
            egui::Color32::from_rgb(139, 185, 255),
        )
    };
    egui::Frame::new()
        .fill(fill)
        .corner_radius(5)
        .inner_margin(egui::Margin::symmetric(8, 4))
        .show(ui, |ui| {
            ui.label(egui::RichText::new(label).size(11.5).strong().color(text));
        });
}

fn model_combo(ui: &mut egui::Ui, label: &str, id: &str, selected: &mut String) {
    ui.horizontal(|ui| {
        ui.label(egui::RichText::new(label).color(text_secondary()));
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            egui::ComboBox::from_id_salt(id)
                .selected_text(selected.as_str())
                .width(156.0)
                .show_ui(ui, |ui| {
                    for model in MODELS {
                        ui.selectable_value(selected, model.to_owned(), model);
                    }
                });
        });
    });
}

fn server_log_path(config: &ManagerConfig) -> PathBuf {
    config.data_root.join("logs/server.log")
}

fn log_line_color(line: &str) -> egui::Color32 {
    let uppercase = line.to_ascii_uppercase();
    if uppercase.contains("ERROR") || uppercase.contains("CRITICAL") {
        error_color()
    } else if uppercase.contains("WARN") {
        warning_color()
    } else if uppercase.contains("DEBUG") {
        text_muted()
    } else {
        egui::Color32::from_rgb(202, 205, 210)
    }
}

fn is_health_check_log(line: &str) -> bool {
    line.contains("GET /health HTTP/") || line.contains("[GET] /health")
}

fn install_system_cjk_font(context: &egui::Context) -> Result<PathBuf> {
    let font_path = system_cjk_font_path()
        .context("Windows 字体目录中未找到受支持的中文字体；请安装 Windows 简体中文补充字体")?;
    let font_bytes = fs::read(&font_path)
        .with_context(|| format!("无法读取 Windows 中文字体：{}", font_path.display()))?;
    let mut fonts = egui::FontDefinitions::default();
    fonts.font_data.insert(
        CJK_FONT_NAME.to_owned(),
        Arc::new(egui::FontData::from_owned(font_bytes)),
    );
    for family in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] {
        fonts
            .families
            .entry(family)
            .or_default()
            .push(CJK_FONT_NAME.to_owned());
    }
    context.set_fonts(fonts);
    Ok(font_path)
}

fn system_cjk_font_path() -> Option<PathBuf> {
    let windows_directory = std::env::var_os("WINDIR").map(PathBuf::from)?;
    select_cjk_font(&windows_directory.join("Fonts"))
}

fn select_cjk_font(font_directory: &Path) -> Option<PathBuf> {
    CJK_FONT_CANDIDATES
        .iter()
        .map(|filename| font_directory.join(filename))
        .find(|path| path.is_file())
}

fn runtime_paths() -> Result<(RuntimePaths, bool)> {
    let executable = std::env::current_exe()?;
    let root = executable
        .parent()
        .context("Manager 可执行文件没有父目录")?
        .to_path_buf();
    let python = root.join("runtime/python/python.exe");
    if !python.is_file() {
        bail!("找不到 Runtime Python：{}", python.display());
    }
    let mut config_override = None;
    let mut start_hidden = false;
    let mut args = std::env::args().skip(1);
    while let Some(argument) = args.next() {
        match argument.as_str() {
            "--config" => {
                config_override = Some(PathBuf::from(args.next().context("--config 缺少路径")?))
            }
            "--hidden" => start_hidden = true,
            _ => {}
        }
    }
    let appdata = std::env::var_os("APPDATA");
    let config = match config_override {
        Some(path) => path,
        None => default_config_path(&root, appdata.as_deref())?,
    };
    Ok((
        RuntimePaths {
            root,
            python,
            config,
            executable,
        },
        start_hidden,
    ))
}

fn default_config_path(root: &Path, appdata: Option<&OsStr>) -> Result<PathBuf> {
    if root.join(INSTALLED_MODE_MARKER).is_file() {
        let appdata = appdata.context("安装版 Manager 无法确定 APPDATA")?;
        return Ok(PathBuf::from(appdata).join("NotaASR/server.toml"));
    }
    Ok(root.join("config/server.toml"))
}

fn ensure_config(paths: &RuntimePaths) -> Result<bool> {
    if paths.config.is_file() {
        return Ok(false);
    }
    let template = paths.root.join("resources/server.example.toml");
    let parent = paths.config.parent().context("配置文件没有父目录")?;
    fs::create_dir_all(parent)?;
    fs::copy(&template, &paths.config)
        .with_context(|| format!("无法从 {} 创建配置", template.display()))?;
    let project = ProjectDirs::from("org", "kwp-lab", "NotaASR").context("无法确定用户数据目录")?;
    let (mut config, mut document) = ManagerConfig::load(&paths.config)?;
    config.model_root = project.data_local_dir().join("models");
    config.data_root = project.data_local_dir().join("data");
    config.save(&paths.config, &mut document)?;
    Ok(true)
}

fn migrate_model_directory(
    source: &Path,
    destination: &Path,
    python: &Path,
    temporary_config: &Path,
    installed_aliases: &[String],
) -> Result<()> {
    let parent = destination.parent().context("目标模型目录没有父目录")?;
    fs::create_dir_all(parent)?;
    let staging = parent.join(format!(".nota-model-migration-{}", uuid::Uuid::new_v4()));
    copy_directory(source, &staging)?;
    if destination.exists() {
        fs::remove_dir(destination).context("目标模型目录不是空目录")?;
    }
    fs::rename(&staging, destination)?;
    for alias in installed_aliases {
        cli::verify_model(python, temporary_config, alias)?;
    }
    Ok(())
}

fn copy_directory(source: &Path, destination: &Path) -> Result<()> {
    fs::create_dir_all(destination)?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let target = destination.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_directory(&entry.path(), &target)?;
        } else {
            fs::copy(entry.path(), target)?;
        }
    }
    Ok(())
}

fn create_tray() -> Result<TrayState> {
    let show = MenuItem::new("打开 Nota ASR Manager", true, None);
    let exit = MenuItem::new("退出", true, None);
    let menu = Menu::with_items(&[&show, &exit])?;
    debug_assert_eq!(MANAGER_ICON_32.len(), 32 * 32 * 4);
    let icon = Icon::from_rgba(MANAGER_ICON_32.to_vec(), 32, 32)?;
    let tray = TrayIconBuilder::new()
        .with_tooltip("Nota ASR Manager")
        .with_icon(icon)
        .with_menu(Box::new(menu))
        .with_menu_on_left_click(false)
        .with_menu_on_right_click(true)
        .build()?;
    Ok(TrayState {
        _icon: tray,
        show_id: show.id().clone(),
        exit_id: exit.id().clone(),
    })
}

fn is_window_reveal_click(button: MouseButton, button_state: MouseButtonState) -> bool {
    button == MouseButton::Left && button_state == MouseButtonState::Up
}

fn path_row(ui: &mut egui::Ui, label: &str, path: &mut PathBuf) {
    ui.horizontal(|ui| {
        ui.allocate_ui_with_layout(
            egui::vec2(72.0, 28.0),
            egui::Layout::left_to_right(egui::Align::Center),
            |ui| {
                ui.label(egui::RichText::new(label).size(11.5).color(text_muted()));
            },
        );
        let mut text = path.to_string_lossy().replace('/', "\\");
        if ui
            .add_sized(
                [ui.available_width() - 58.0, 28.0],
                egui::TextEdit::singleline(&mut text).vertical_align(egui::Align::Center),
            )
            .changed()
        {
            *path = PathBuf::from(text);
        }
        if ui.button("浏览").clicked()
            && let Some(selected) = rfd::FileDialog::new().set_directory(&*path).pick_folder()
        {
            *path = selected;
        }
    });
}

fn port_row(ui: &mut egui::Ui, port_input: &mut String, port: &mut u16) {
    ui.horizontal(|ui| {
        ui.allocate_ui_with_layout(
            egui::vec2(72.0, 28.0),
            egui::Layout::left_to_right(egui::Align::Center),
            |ui| {
                ui.label(egui::RichText::new("端口").size(11.5).color(text_muted()));
            },
        );
        let parsed = parse_port(port_input);
        let text_color = if parsed.is_ok() {
            text_primary()
        } else {
            error_color()
        };
        if ui
            .add_sized(
                [112.0, 28.0],
                egui::TextEdit::singleline(port_input)
                    .text_color(text_color)
                    .vertical_align(egui::Align::Center),
            )
            .changed()
            && let Ok(value) = parse_port(port_input)
        {
            *port = value;
        }
    });
}

fn parse_port(value: &str) -> Result<u16> {
    let port = value
        .trim()
        .parse::<u16>()
        .context("端口必须是 1-65535 之间的整数")?;
    if port == 0 {
        bail!("端口必须是 1-65535 之间的整数");
    }
    Ok(port)
}

fn open_in_explorer(path: &Path) -> Result<PathBuf> {
    let target = prepare_explorer_target(path)?;
    let operation: Vec<u16> = OsStr::new("open").encode_wide().chain(Some(0)).collect();
    let target_wide: Vec<u16> = target.as_os_str().encode_wide().chain(Some(0)).collect();
    let result = unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            operation.as_ptr(),
            target_wide.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            SW_SHOWNORMAL,
        )
    };
    if result as isize <= 32 {
        bail!(
            "无法打开目录：{}（ShellExecuteW={result:?}）",
            target.display()
        );
    }
    Ok(target)
}

fn prepare_explorer_target(path: &Path) -> Result<PathBuf> {
    let requested = if path.is_file() {
        path.parent().unwrap_or(path).to_path_buf()
    } else {
        path.to_path_buf()
    };
    fs::create_dir_all(&requested)
        .with_context(|| format!("无法创建目录：{}", requested.display()))?;
    let canonical = fs::canonicalize(&requested)
        .with_context(|| format!("无法解析目录：{}", requested.display()))?;
    Ok(strip_verbatim_prefix(canonical))
}

fn strip_verbatim_prefix(path: PathBuf) -> PathBuf {
    let display = path.to_string_lossy();
    if let Some(rest) = display.strip_prefix(r"\\?\UNC\") {
        PathBuf::from(format!(r"\\{rest}"))
    } else if let Some(rest) = display.strip_prefix(r"\\?\") {
        PathBuf::from(rest)
    } else {
        path
    }
}

fn configure_startup(enabled: bool, executable: &Path, config: &Path) -> Result<()> {
    let appdata = std::env::var_os("APPDATA").context("APPDATA 未定义")?;
    let startup = PathBuf::from(appdata).join("Microsoft/Windows/Start Menu/Programs/Startup");
    fs::create_dir_all(&startup)?;
    let command = startup.join("Nota ASR Manager.cmd");
    if enabled {
        fs::write(
            command,
            format!(
                "@echo off\r\nstart \"\" \"{}\" --config \"{}\" --hidden\r\n",
                executable.display(),
                config.display()
            ),
        )?;
    } else if command.exists() {
        fs::remove_file(command)?;
    }
    Ok(())
}

fn format_bytes(bytes: u64) -> String {
    if bytes >= 1024 * 1024 * 1024 {
        format!("{:.2} GiB", bytes as f64 / (1024.0 * 1024.0 * 1024.0))
    } else {
        format!("{:.0} MiB", bytes as f64 / (1024.0 * 1024.0))
    }
}

fn write_uninstall_metadata(config_path: &Path, config: &ManagerConfig) -> Result<()> {
    let parent = config_path.parent().context("配置文件没有父目录")?;
    fs::create_dir_all(parent)?;
    let content = format!(
        "[Paths]\r\nModelsRoot={}\r\nDataRoot={}\r\n",
        config.model_root.display(),
        config.data_root.display()
    );
    fs::write(parent.join("uninstall-paths.ini"), content)?;
    Ok(())
}

fn delete_user_data_request() -> Option<PathBuf> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let index = arguments
        .iter()
        .position(|value| value == "--delete-user-data")?;
    let config_index = arguments.iter().position(|value| value == "--config")?;
    if index >= arguments.len() || config_index + 1 >= arguments.len() {
        return None;
    }
    Some(PathBuf::from(&arguments[config_index + 1]))
}

fn delete_user_data(config_path: &Path) -> Result<()> {
    let (config, _) = ManagerConfig::load(config_path)?;
    let executable = std::env::current_exe()?;
    let forbidden = [
        std::env::var_os("USERPROFILE").map(PathBuf::from),
        std::env::var_os("APPDATA").map(PathBuf::from),
        std::env::var_os("LOCALAPPDATA").map(PathBuf::from),
        executable.parent().map(Path::to_path_buf),
    ];
    let mut paths = vec![config.model_root, config.data_root];
    if let Some(parent) = config_path.parent() {
        paths.push(parent.to_path_buf());
    }
    paths.sort_by_key(|path| std::cmp::Reverse(path.components().count()));
    paths.dedup();
    for path in paths {
        let absolute = if path.is_absolute() {
            path
        } else {
            std::env::current_dir()?.join(path)
        };
        if absolute.parent().is_none()
            || forbidden
                .iter()
                .flatten()
                .any(|protected| absolute == *protected)
        {
            bail!("拒绝删除不安全的数据目录：{}", absolute.display());
        }
        if absolute.exists() {
            fs::remove_dir_all(&absolute)
                .with_context(|| format!("无法删除数据目录：{}", absolute.display()))?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cjk_font_selection_prefers_microsoft_yahei() {
        let root = std::env::temp_dir().join(format!("nota-fonts-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("Deng.ttf"), b"fallback").unwrap();
        fs::write(root.join("msyh.ttc"), b"preferred").unwrap();

        assert_eq!(select_cjk_font(&root), Some(root.join("msyh.ttc")));

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn identifies_repetitive_health_probe_logs() {
        assert!(is_health_check_log(
            "INFO: 127.0.0.1:50000 - \"GET /health HTTP/1.1\" 200 OK"
        ));
        assert!(!is_health_check_log(
            "INFO: 127.0.0.1:50000 - \"POST /v1/audio/transcriptions HTTP/1.1\" 200 OK"
        ));
    }

    #[test]
    fn parses_only_valid_tcp_ports() {
        assert_eq!(parse_port("8010").unwrap(), 8010);
        assert!(parse_port("0").is_err());
        assert!(parse_port("65536").is_err());
        assert!(parse_port("not-a-port").is_err());
    }

    #[test]
    fn tray_reveals_window_only_on_completed_left_click() {
        assert!(is_window_reveal_click(
            MouseButton::Left,
            MouseButtonState::Up
        ));
        assert!(!is_window_reveal_click(
            MouseButton::Left,
            MouseButtonState::Down
        ));
        assert!(!is_window_reveal_click(
            MouseButton::Right,
            MouseButtonState::Up
        ));
    }

    #[test]
    fn explorer_target_creates_and_normalizes_the_exact_log_directory() {
        let root = std::env::temp_dir().join(format!("nota-logs-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("config")).unwrap();
        let requested = root.join("config/../data/logs");

        let target = prepare_explorer_target(&requested).unwrap();
        let expected = strip_verbatim_prefix(fs::canonicalize(root.join("data/logs")).unwrap());

        assert_eq!(target, expected);
        assert!(target.is_dir());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn recursive_copy_preserves_nested_model_files() {
        let root = std::env::temp_dir().join(format!("nota-copy-{}", uuid::Uuid::new_v4()));
        let source = root.join("source");
        let destination = root.join("destination");
        fs::create_dir_all(source.join("component/revision")).unwrap();
        fs::write(source.join("component/revision/model.pt"), b"weights").unwrap();

        copy_directory(&source, &destination).unwrap();

        assert_eq!(
            fs::read(destination.join("component/revision/model.pt")).unwrap(),
            b"weights"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn portable_runtime_uses_its_own_config() {
        let root = std::env::temp_dir().join(format!("nota-portable-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();

        let config =
            default_config_path(&root, Some(OsStr::new(r"C:\Users\test\AppData\Roaming"))).unwrap();

        assert_eq!(config, root.join("config/server.toml"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn installed_runtime_uses_appdata_config() {
        let root = std::env::temp_dir().join(format!("nota-installed-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join(INSTALLED_MODE_MARKER), b"installed\n").unwrap();

        let config =
            default_config_path(&root, Some(OsStr::new(r"C:\Users\test\AppData\Roaming"))).unwrap();

        assert_eq!(
            config,
            PathBuf::from(r"C:\Users\test\AppData\Roaming")
                .join("NotaASR")
                .join("server.toml")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn installed_runtime_requires_appdata() {
        let root = std::env::temp_dir().join(format!("nota-installed-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join(INSTALLED_MODE_MARKER), b"installed\n").unwrap();

        assert!(default_config_path(&root, None).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
