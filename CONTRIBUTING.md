# Contributing to Nota ASR Server / 参与 Nota ASR Server 贡献

Thank you for contributing. Focused bug fixes, API-contract tests, backend
adapters, deployment improvements, and clear documentation are welcome.

感谢你参与贡献。我们欢迎边界清晰的缺陷修复、API 契约测试、模型后端适配、部署
改进和技术文档。

## Before you start / 开始之前

- Search [existing issues](https://github.com/kwp-lab/nota-asr-server/issues).
  Open an issue before a large feature, new model backend, public API change,
  or architectural change so its scope can be agreed first.
- Never commit or attach meeting audio, transcripts, speaker embeddings, model
  weights, API keys, a real `.env`, runtime data, or identifiable logs. Use
  synthetic fixtures and fake model backends for automated tests.
- Read [`AGENTS.md`](AGENTS.md) and the
  [engineering documentation index](docs/README.md) before changing behavior.
- Keep one pull request focused and exclude generated environments, build
  output, models, runtime data, benchmarks, and local reports.

- 请先搜索[现有 Issues](https://github.com/kwp-lab/nota-asr-server/issues)。大型功能、
  新模型后端、公开 API 或架构调整应先创建 Issue，就范围达成一致。
- 不得提交或附带会议录音、转写正文、说话人向量、模型权重、API Key、真实 `.env`、
  运行数据或可识别用户身份的日志。自动化测试必须使用合成数据和假模型后端。
- 修改行为前请阅读 [`AGENTS.md`](AGENTS.md) 和
  [工程文档索引](docs/README.md)。
- 一个 PR 只处理一个主题，不要提交虚拟环境、构建产物、模型、运行数据、基准结果
  或本地报告。

## Compatibility boundaries / 兼容性边界

- Preserve OpenAI multipart compatibility for `/v1/audio/transcriptions`.
- Treat the Nota `verbose_json` response and `/v1/nota` batch protocol as
  versioned public contracts. Do not expose raw model output directly.
- Keep speaker IDs meeting-local and anonymous; the server must not turn them
  into persistent identities.
- Keep model-specific behavior behind adapters so SenseVoice, Paraformer, and
  Fun-ASR-Nano return the normalized public schema.
- A breaking contract change requires explicit agreement, contract tests,
  documentation, an ADR, and the appropriate schema-version change.

- 必须保持 `/v1/audio/transcriptions` 的 OpenAI multipart 兼容性。
- Nota `verbose_json` 响应和 `/v1/nota` 批处理协议属于版本化公开契约；不得把模型
  原始输出直接暴露给客户端。
- Speaker ID 仅在单场会议内有效且保持匿名；服务端不得将其变成持久身份。
- 模型差异应封装在适配器内，SenseVoice、Paraformer 和 Fun-ASR-Nano 都必须返回
  规范化的公开结构。
- 破坏兼容性的契约变化必须事先确认，并同时提供契约测试、文档、ADR 和相应的
  Schema 版本调整。

## Development workflow / 开发流程

1. Fork the repository or create a focused branch from the latest `main`.
2. Use Python 3.10-3.12 and follow the environment instructions in
   [Development](docs/development.md) and the root README.
3. Add tests for behavior changes and update the owning specification. Update
   `CHANGELOG.md` for user-visible or API-visible changes.
4. Run the automated tests:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest
   ```

   Tests must use fake backends and must not download real model checkpoints.
   Dependency changes additionally require the frozen CPU license and package
   checks described in
   [`docs/open-source-compliance.md`](docs/open-source-compliance.md).
5. Open a pull request describing the problem, contract impact, implementation
   choice, test evidence, and operational or compatibility considerations.

1. Fork 仓库，或从最新 `main` 创建一个主题明确的分支。
2. 使用 Python 3.10–3.12，并遵循 [`docs/development.md`](docs/development.md)
   和根 README 的环境配置说明。
3. 行为变化必须补充测试并更新对应技术规范；用户或 API 可见变化还应更新
   `CHANGELOG.md`。
4. 使用上述命令运行自动化测试。测试不得下载真实模型。依赖变化还必须执行
   [`docs/open-source-compliance.md`](docs/open-source-compliance.md) 中的冻结 CPU
   许可证与包内容检查。
5. 创建 PR，说明问题、契约影响、实现选择、测试依据，以及运维或兼容性影响。

Normal pull requests do not need to build a Docker image, run a real model, or
publish a Python package. These are separate operational or release actions.

普通 PR 无需构建 Docker 镜像、运行真实模型或发布 Python 包；这些属于独立的运维
或发布操作。

## License / 许可证

By contributing, you agree that your contribution may be distributed under
the repository's [MIT License](LICENSE). Third-party code, models, and assets
must retain their notices and be reviewed for redistribution compatibility.

提交贡献即表示你同意该贡献可依据本仓库的 [MIT License](LICENSE) 分发。第三方代码、
模型与资源必须保留其声明，并经过再分发兼容性审查。
