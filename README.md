# model-switch

一个纯本地 Python CLI。它只做两件事：

1. 从一个聚合后端获取模型列表；
2. 一键切换 Claude Code / Codex / Pi 的当前模型。

支持 Python 3.8+（Ubuntu 20.04 系统自带的 3.8 即可直接运行；解析 `config.toml` 时会自动用到 `tomli` backport，随包安装）。

兼容环境为 Ubuntu 20.04 / 22.04 / 24.04（对应系统自带 Python 3.8 / 3.10 / 3.12）。代码层面已做降级适配：`tomllib` 在 3.11 以下回退到 `tomli`、`importlib.resources` 兼容不同版本、`argparse.BooleanOptionalAction` 在 3.9 以下回退为手动实现，四套系统均应开箱即用。

同时支持 Windows 10 / 11（Python 3.8+）：上下键菜单改用 `msvcrt` 读键、npm 安装的 `claude.cmd` / `codex.cmd` 自动经 `cmd.exe` 启动、没有软链权限时目录退回 junction。细节见「Windows 适配」。

## 安装

开发模式安装（推荐，源码修改后立即生效）：

```bash
cd /path/to/model-switch
python3 -m pip install -e . --break-system-packages
```

这种模式主要注册入口和源码路径映射。

Windows 上改用 `py` 启动器，且不需要 `--break-system-packages`：

```powershell
cd C:\path\to\model-switch
py -m pip install -e .
```

详见「Windows 适配」。

如果希望把包完整安装到：

```text
~/.local/lib/python3.12/site-packages
```

使用常规安装：

```bash
cd /path/to/model-switch
python3 -m pip install --upgrade . --break-system-packages
```

不带 `--user` 时 pip 会自动选择位置：普通用户的 `site-packages` 不可写，pip 会打印 `Defaulting to user installation because normal site-packages is not writeable`，装到 `~/.local`；以 root 或 sudo 运行时则装到系统目录。所以这里不用写 `--user`，命令本身就能自适应。

关于 `--break-system-packages`：Debian/Ubuntu 上的 pip 受 PEP 668 保护，默认拒绝安装，不加这个参数会直接报 `error: externally-managed-environment`（`--user` 也一样失败）。它只关闭「禁止装到系统 Python」这一项检查，不改安装位置——装到哪里仍由上面的规则决定。

安装后可用 `ms` 或 `model-switch` 命令，命令入口通常在：

```text
~/.local/bin
```

### PATH 排查

Linux / macOS 用 `which ms`，Windows 用 `where ms`。如果找不到命令，说明安装目录不在 `PATH` 里。Linux 下临时生效：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

永久生效，追加到 `~/.bashrc`：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

PATH 修好之前，也可以用模块方式启动（不依赖 PATH）：

```bash
python3 -m model_switch --help
```

Windows 上对应的安装目录通常是 `%APPDATA%\Python\Python3xx\Scripts` 或 `%LOCALAPPDATA%\Programs\Python\Python3xx\Scripts`（以 `where python` 实际路径为准），模块方式启动用：

```powershell
py -m model_switch --help
```

### 安装到系统目录

默认安装只影响当前用户。如果希望所有用户都能用，用 `sudo` 运行同样的命令：

```bash
cd /path/to/model-switch
sudo python3 -m pip install --upgrade . --break-system-packages
```

此时装到：

```text
/usr/local/lib/python3.12/dist-packages/model_switch
/usr/local/bin/ms
/usr/local/bin/model-switch
```

`/usr/local/bin` 本来就在 `PATH` 里，不需要额外配置。

注意不要在 root 下用 `-e`：editable 安装会把 `/usr/local` 里的入口指向你的源码目录，源码一旦移动或非 root 用户无法读取，系统级的 `ms` 就会失效。开发用 `-e` 装给自己，需要全局可用时用普通安装。

## 卸载

卸载 Python 包和命令入口：

```bash
python3 -m pip uninstall model-switch
```

如果当初是装到系统目录的，卸载也要加 `sudo`：

```bash
sudo python3 -m pip uninstall model-switch
```

Windows 上直接执行 `py -m pip uninstall model-switch` 即可。

如果在项目目录里，可以顺带删除本地的打包元数据：

```bash
rm -rf model_switch.egg-info/
```

如需彻底清理 `ms` 保存的后端配置、模型列表，以及隔离的 Claude/Codex/Pi 配置，可删除：

```bash
rm -rf ~/.model-switch
```

Windows（PowerShell）：

```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\.model-switch"
```

注意：这会删除本地模型数据和模型切换配置，不会修改原生 `~/.claude`、`~/.codex` 和 `~/.pi` 配置目录。

## Windows 适配

Windows 10 / 11 与 Linux 共用同一套代码和隔离目录结构（`%USERPROFILE%\.model-switch`），平台差异集中处理在 `model_switch/compat.py` 和各 agent 适配器里：

- **交互选择**：`ms use` 的上下键菜单在 Windows 上用 `msvcrt` 读取按键（`termios` / 管道 `select` 只在 POSIX 可用），并会尝试为旧版 `conhost` 打开 ANSI（VT）处理；Windows Terminal 无需额外设置。Ctrl+C 按取消处理。
- **启动 agent**：npm 全局安装的 `claude` / `codex` 实际是 `.cmd` 包装，`CreateProcess` 不能直接执行，`ms` 会通过 `cmd.exe /d /c call ...` 启动；原生 `.exe` 安装包不受影响。用 `MODEL_SWITCH_CLAUDE_BIN` 等环境变量指定可执行文件时，同样支持完整路径。
- **资源链接**：隔离目录需要引用原生目录里的 `projects`、`plugins`、`skills`、`themes` 等资源。Windows 普通用户未开启「开发者模式」时无法创建软链，目录会自动退回 junction（无需管理员权限），单个文件（如 `auth.json`）退回复制。
- **配置文件替换**：Windows 上目标文件可能正被运行中的 agent 打开，`ms` 写入时会短暂重试 `os.replace`，避免偶发的 `PermissionError`。
- **编辑器**：`ms model edit` 在 Windows 上默认用 `notepad`；设置了 `EDITOR` 时按 Windows 命令行规则拆分，支持 `"C:\Program Files\...\code.exe" -w` 这类写法，也支持 `.cmd` 包装。
- **状态栏**：Claude Code 的 `statusLine` 命令按平台规则加引号；Windows 上路径转正斜杠并加双引号，Git Bash / cmd 都能执行。状态栏脚本的 stdin/stdout 固定 UTF-8，中文路径不会乱码。
- **输出编码**：控制台重定向到文件/管道时，`✔`、`⚠` 等符号无法用本地代码页表示会自动替换，不会因为编码错误中断命令。

核对共享指令注入时，PowerShell 可用：

```powershell
Get-FileHash model_switch\AGENTS.md,
  "$env:USERPROFILE\.model-switch\claude\CLAUDE.md",
  "$env:USERPROFILE\.model-switch\codex\AGENTS.md",
  "$env:USERPROFILE\.model-switch\pi\agent\AGENTS.md" -Algorithm SHA256
```

## 配置聚合后端

```bash
ms config \
  --base-url https://your-aggregator.example.com \
  --api-key sk-xxx
```

如果后端是 OpenAI 兼容接口，`base_url` 可以写成根地址；工具会自动请求：

```text
{base_url}/v1/models
```

## 获取模型

```bash
ms fetch
```

模型保存在：

```text
~/.model-switch/models.json
```

后端不再返回的模型默认会保留，并标记为 `enabled: false` + `stale`，避免后端临时抖动把本地记录和手工修改一起抹掉。这类模型不会出现在 `ms use` 和 agent 的模型选择里。如果后端之后又重新返回它，标记会被清除、自动恢复启用。

确实要删除这些失效模型时用 `-p/--prune`：

```bash
ms fetch --prune
```

`-f/--force` 不保留本地任何模型信息，用后端响应重建。

查看本地模型：

```bash
ms models          # Status 列显示 on / off / stale
```

切换模型见下一节。

## 一键切换模型

交互式界面：

```bash
ms use
```

界面里先用 ↑/↓ 移动，enter 确认；All agents 会同时选中 Claude Code、Codex 和 Pi。

也可以直接指定模型，跳过交互，一次切换全部 agent：

```bash
ms use 7            # 切到 ms models 里的第 7 个（对应 #N 列）
ms use kimi-k3      # 按模型 id 切换
```

序号是 1-based，与 `ms models` 输出的 `#` 列一致。指定的序号越界或模型 id 不存在时会直接报错退出，不会修改任何 agent 配置：

```text
序号超出范围：99（当前共 11 个模型）
未找到模型：nope-not-real；用 ms models 查看本地模型列表
```

这种用法不会先刷新模型列表，序号以你当前 `ms models` 看到的结果为准；需要先同步后端时，先运行 `ms fetch`。

切换时会写这些文件：

### Claude Code

注入文件放在：

```text
~/.model-switch/claude/settings.json
~/.model-switch/claude/.claude.json
```

`ms claude` 启动时会通过以下方式生效：

```text
CLAUDE_CONFIG_DIR=~/.model-switch/claude
claude --settings ~/.model-switch/claude/settings.json
```

### Codex

注入文件放在：

```text
~/.model-switch/codex/config.toml
~/.model-switch/codex/models.json
```

`ms codex` 启动时会通过以下方式生效：

```text
CODEX_HOME=~/.model-switch/codex
```

### Pi Agent

注入文件放在：

```text
~/.model-switch/pi/agent/models.json
~/.model-switch/pi/agent/settings.json
```

`ms pi` 启动时会通过以下方式生效：

```text
PI_CODING_AGENT_DIR=~/.model-switch/pi/agent
```

`models.json` 里只声明一个 `model-switch` provider，模型按自身 `supported_apis` 挑一个 pi 支持的接口，优先级为 `responses → chat → claude_native`（依次对应 pi 的 `openai-responses`、`openai-completions`、`anthropic-messages`）；名称含 `claude` 且支持 Anthropic Messages 的模型会优先使用 `anthropic-messages`，并在模型级别覆盖 `api`、`baseUrl` 与 `compat`：两个 OpenAI 接口固定声明 `sendSessionAffinityHeaders` 与 `sessionAffinityFormat: "openai"`，Anthropic Messages 只声明 `sendSessionAffinityHeaders`。密钥通过 `MODEL_SWITCH_API_KEY` 环境变量在请求时解析，不落盘到 `models.json`。

思考档位：模型未声明 `reasoning_levels` 时按 `low/medium/high` 处理，`settings.json` 的默认档位取 `high`；把某个模型的 `reasoning_levels` 设为空数组即可关闭该模型的思考。`off` 始终保留，可以在 pi 里临时关掉思考。

隔离目录与原生的 `~/.pi/agent` 只共享资源、不共享状态：`extensions`、`skills`、`prompts`、`themes`、`tools`、`bin`、`npm`、`git`、`auth.json` 会自动软链接过去，而 `settings.json`、`models.json`、`sessions` 各自独立。原生 `~/.claude/settings.json`、`~/.codex/config.toml` 和 `~/.pi/agent/models.json` 都不会被修改。

## 共享指令注入（AGENTS.md）

`model_switch/AGENTS.md` 是各 agent 共享指令的唯一真源，随包一起分发（该文件必须存在，否则注入会静默跳过）。

每次运行 `ms` 的任何子命令都会把它同步到每个 agent 的隔离目录：

```text
~/.model-switch/claude/CLAUDE.md         Claude Code
~/.model-switch/codex/AGENTS.md          Codex
~/.model-switch/pi/agent/AGENTS.md       Pi
```

- Claude Code 只认 `CLAUDE.md`，不读 `AGENTS.md`，所以它的文件名与另外两个不同。
- 这些文件是**生成物**：同名文件（包括指向别处的软链）会被直接覆写，要改内容请改真源，然后运行任意 `ms` 命令。
- 内容与真源一致时跳过写入，重复运行不会反复改动 mtime。
- 注入与模型选择无关，所以 `ms status` 这类命令也会完成同步；原生 `~/.claude`、`~/.codex`、`~/.pi` 不受影响。

核对是否生效：

```bash
md5sum model_switch/AGENTS.md \
  ~/.model-switch/claude/CLAUDE.md \
  ~/.model-switch/codex/AGENTS.md \
  ~/.model-switch/pi/agent/AGENTS.md
```

四份 md5 应完全一致。

## 自动化与权限参数

`ms claude` 会像 `sc` 一样自动注入隔离运行所需的参数和环境变量：

- Claude Code 启动参数：
  - `--dangerously-skip-permissions`
- Claude Code 隔离配置：
  - `skipDangerousModePermissionPrompt: true`
  - `showThinkingSummaries: true`
  - `alwaysThinkingEnabled: true`
  - `effortLevel: high`（若模型支持）
  - `CLAUDE_CODE_SANDBOXED=1`
  - `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`
  - `CLAUDE_CODE_ATTRIBUTION_HEADER=0`（不发送归属头）
- Codex 隔离配置：
  - `sandbox_mode = "danger-full-access"`
  - `approval_policy = "never"`
  - TUI 状态栏显示模型、目录、剩余上下文和上下文窗口总大小
- Pi 隔离配置：
  - `defaultProjectTrust: "always"`（不再询问项目信任）
  - `defaultProvider` / `defaultModel` 指向当前选择的模型
  - `defaultThinkingLevel: high`（若模型支持）
  - `PI_SKIP_VERSION_CHECK=1`、`PI_TELEMETRY=0`

Claude 的管理子命令（例如 `config`、`doctor`、`mcp`）不会自动追加 `--dangerously-skip-permissions`。如果以 root 运行，也会像 `sc` 一样跳过该启动参数。

需要传参给原工具时使用：

```bash
ms claude -- --help
ms codex -- --help
ms pi -- --help
```

## 本地模型能力修改

## 扩展新 Agent

Agent 相关逻辑已统一为适配器接口。当前适配器注册在：

```text
model_switch/agents/registry.py
```

新增 Agent 时，创建一个新的适配器类并实现：

```python
class ExampleAdapter(AgentAdapter):
    id = "example"
    label = "Example Agent"
    required_api = "responses"
    endpoint = "/v1/responses"
    default_binary = "example"
    binary_env = "MODEL_SWITCH_EXAMPLE_BIN"
    instructions_dir = EXAMPLE_HOME          # 隔离目录（在 storage.py 里定义）
    instructions_name = "AGENTS.md"          # 该 agent 默认读取的全局指令文件名

    def switch(self, config, model, model_ids): ...
    def launch(self, config, model, passthrough_args): ...
```

然后把实例加入 `registry.py` 的 `_AGENTS` 即可：

```python
_AGENTS = {
    adapter.id: adapter
    for adapter in (ClaudeAdapter(), CodexAdapter(), PiAdapter(), ExampleAdapter())
}
```

加入后，`ms use`、`ms status` 和 `ms example` 会自动出现，共享指令也会注入到它的隔离目录，不需要再修改 UI 或 CLI 主流程。

顶层 `ms --help` 里所有 agent 命令折叠成一条（形如 `claude|codex|pi`），新增 agent 只会加长这一条，不会让菜单越列越长。

## 恢复会话

可以直接使用：

```bash
ms claude resume <session-id>
ms codex resume <session-id>
ms pi resume <session-id>
```

不需要通过 `--` 透传。省略 `<session-id>` 时，会使用原工具自己的会话选择器：

```bash
ms claude resume
ms codex resume
ms pi resume
```

Pi 没有 `resume` 子命令，`ms pi resume` 会被翻译成 `pi --resume`（选择器）或 `pi --session <session-id>`。

Pi 的会话存放在隔离目录里（`~/.model-switch/pi/agent/sessions`），与原生的 `pi` 会话互不影响。
