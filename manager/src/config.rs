use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use atomic_write_file::AtomicWriteFile;
use toml_edit::{DocumentMut, value};

#[derive(Clone, Debug, PartialEq)]
pub struct ManagerConfig {
    pub host: String,
    pub port: u16,
    pub model_root: PathBuf,
    pub data_root: PathBuf,
    pub default_model: String,
    pub preload_model: String,
    pub start_on_login: bool,
    pub auto_start_server: bool,
}

impl ManagerConfig {
    pub fn load(path: &Path) -> Result<(Self, DocumentMut)> {
        let text = fs::read_to_string(path)
            .with_context(|| format!("无法读取配置文件：{}", path.display()))?;
        let document = text
            .parse::<DocumentMut>()
            .context("server.toml 格式无效")?;
        if document["schema_version"].as_integer() != Some(1) {
            bail!("仅支持 schema_version = 1");
        }
        let base = path.parent().unwrap_or_else(|| Path::new("."));
        let host = required_string(&document, "server", "host")?;
        let port_value = document["server"]["port"]
            .as_integer()
            .context("server.port 必须是整数")?;
        let port = u16::try_from(port_value).context("server.port 必须在 1-65535 之间")?;
        if port == 0 {
            bail!("server.port 必须在 1-65535 之间");
        }
        let model_root = resolve_path(base, &required_string(&document, "models", "root")?);
        let data_root = resolve_path(base, &required_string(&document, "storage", "data_root")?);
        let default_model = required_string(&document, "models", "default")?;
        let preload_model = required_string(&document, "models", "preload")?;
        let start_on_login = optional_bool(&document, "manager", "start_on_login");
        let auto_start_server = optional_bool(&document, "manager", "auto_start_server");
        Ok((
            Self {
                host,
                port,
                model_root,
                data_root,
                default_model,
                preload_model,
                start_on_login,
                auto_start_server,
            },
            document,
        ))
    }

    pub fn save(&self, path: &Path, document: &mut DocumentMut) -> Result<()> {
        if self.port == 0 {
            bail!("端口必须在 1-65535 之间");
        }
        document["server"]["host"] = value(&self.host);
        document["server"]["port"] = value(i64::from(self.port));
        document["models"]["root"] = value(path_text_for_config(path, &self.model_root));
        document["models"]["default"] = value(&self.default_model);
        document["models"]["preload"] = value(&self.preload_model);
        document["storage"]["data_root"] = value(path_text_for_config(path, &self.data_root));
        document["manager"]["start_on_login"] = value(self.start_on_login);
        document["manager"]["auto_start_server"] = value(self.auto_start_server);

        let parent = path.parent().context("配置文件没有父目录")?;
        fs::create_dir_all(parent)?;
        if path.exists() {
            fs::copy(path, path.with_extension("toml.backup"))?;
        }
        let mut writer = AtomicWriteFile::options()
            .open(path)
            .with_context(|| format!("无法写入配置文件：{}", path.display()))?;
        writer.write_all(document.to_string().as_bytes())?;
        writer.commit()?;
        Ok(())
    }
}

fn required_string(document: &DocumentMut, section: &str, key: &str) -> Result<String> {
    document[section][key]
        .as_str()
        .map(ToOwned::to_owned)
        .with_context(|| format!("{section}.{key} 必须是字符串"))
}

fn optional_bool(document: &DocumentMut, section: &str, key: &str) -> bool {
    document
        .get(section)
        .and_then(|table| table.get(key))
        .and_then(toml_edit::Item::as_bool)
        .unwrap_or(false)
}

fn resolve_path(base: &Path, raw: &str) -> PathBuf {
    let value = PathBuf::from(raw);
    let resolved = if value.is_absolute() {
        value
    } else {
        base.join(value)
    };
    normalize_lexically(&resolved)
}

fn normalize_lexically(path: &Path) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                normalized.pop();
            }
            _ => normalized.push(component.as_os_str()),
        }
    }
    normalized
}

fn path_text(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

fn path_text_for_config(config_path: &Path, target: &Path) -> String {
    let target = normalize_lexically(target);
    let Some(config_directory) = config_path.parent() else {
        return path_text(&target);
    };

    // A portable Runtime keeps its TOML in <runtime>/config/server.toml.
    // Keep directories owned by that Runtime relative so extracting or moving
    // the complete one-folder does not invalidate a setting after it is saved.
    // Installer/user-selected directories live elsewhere and remain absolute.
    let is_runtime_config = config_directory
        .file_name()
        .is_some_and(|name| name.to_string_lossy().eq_ignore_ascii_case("config"));
    if is_runtime_config
        && let Some(runtime_root) = config_directory.parent()
        && let Ok(suffix) = target.strip_prefix(normalize_lexically(runtime_root))
    {
        return path_text(&Path::new("..").join(suffix));
    }

    path_text(&target)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> &'static str {
        "schema_version = 1\n\
         # keep me\n\
         [server]\n\
         host = '127.0.0.1'\n\
         port = 8010\n\
         [models]\n\
         root = '../models'\n\
         default = 'sensevoice'\n\
         preload = 'sensevoice'\n\
         [storage]\n\
         data_root = '../data'\n"
    }

    #[test]
    fn round_trip_preserves_unknown_content() {
        let root = std::env::temp_dir().join(format!("nota-manager-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("config")).unwrap();
        let path = root.join("config/server.toml");
        fs::write(&path, sample()).unwrap();
        let (mut config, mut document) = ManagerConfig::load(&path).unwrap();
        config.port = 8123;
        config.save(&path, &mut document).unwrap();
        let saved = fs::read_to_string(&path).unwrap();
        assert!(saved.contains("# keep me"));
        assert!(saved.contains("port = 8123"));
        assert!(saved.contains("root = \"../models\""));
        assert!(saved.contains("data_root = \"../data\""));
        assert!(path.with_extension("toml.backup").is_file());

        let (reloaded, _) = ManagerConfig::load(&path).unwrap();
        assert_eq!(reloaded.model_root, root.join("models"));
        assert_eq!(reloaded.data_root, root.join("data"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn external_paths_remain_absolute_when_portable_config_is_saved() {
        let root = std::env::temp_dir().join(format!("nota-portable-{}", uuid::Uuid::new_v4()));
        let external = std::env::temp_dir().join(format!("nota-external-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("config")).unwrap();
        let path = root.join("config/server.toml");
        fs::write(&path, sample()).unwrap();
        let (mut config, mut document) = ManagerConfig::load(&path).unwrap();
        config.model_root = external.join("models");
        config.data_root = external.join("data");

        config.save(&path, &mut document).unwrap();

        let saved = fs::read_to_string(&path).unwrap();
        assert!(saved.contains(&format!(
            "root = \"{}\"",
            path_text(&external.join("models"))
        )));
        assert!(saved.contains(&format!(
            "data_root = \"{}\"",
            path_text(&external.join("data"))
        )));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn relative_model_and_data_paths_are_lexically_normalized() {
        let root = std::env::temp_dir().join(format!("nota-paths-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("config")).unwrap();
        let path = root.join("config/server.toml");
        fs::write(&path, sample()).unwrap();

        let (config, _) = ManagerConfig::load(&path).unwrap();

        assert_eq!(config.model_root, root.join("models"));
        assert_eq!(config.data_root, root.join("data"));
        fs::remove_dir_all(root).unwrap();
    }
}
