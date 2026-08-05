# 故事机器（Story Machine）

> 基于 DeterminFlow 的 AI 角色对演写作系统：人物库 → 故事机器（双角色对演）/ 圆桌（多角色对谈）。

## 项目位置

- 项目根目录：**`E:\故事机器`**
- Git 仓库：`https://github.com/xxxnnnhhh/-`（origin，main 分支）
- 服务地址：http://localhost:8020 （端口由 `WEB_PORT` 控制）

## 保存地址（E 盘）

所有数据统一保存在 E 盘：

| 内容 | 位置 |
|---|---|
| 角色 / 人物日志 / 情绪状态 / 会话剧本 | `E:\DeterminFlowData` |
| 运行日志 | `E:\故事机器\logs` |
| 配置 | `E:\故事机器\config` |
| 模型凭据 | `config\models_config.json`（不入 git） |

> 路径在 `.env` 中配置（`DETERMINFLOW_DATA_DIR=E:/DeterminFlowData`），
> 角色与剧本数据不会写进 C 盘。

## 启动方式

```powershell
cd E:\故事机器
.\.venv\Scripts\pythonw.exe run.py
# 或：.\.venv\Scripts\python.exe run.py（前台）
```

启动后打开 http://localhost:8020 ，顶部导航：圆桌 / 故事机器 / 人物库。

## 功能速览

- **人物库**：创建角色——三我占比（本我/自我/超我，各自独立输入框，归一化 100）、
  性格特质、重大事件、硬/软规则；演出结束后自动生成**人物日志**（跨会话记忆），
  下次对演时读回提示词。
- **故事机器**：设定场景，两个角色自动对演（旁白 + 思考/表情/动作/台词四通道），
  支持导演注入、手动控制情绪、导出 Markdown 剧本。
- **圆桌**：多角色讨论，席位可从人物库选角，发言走完整人格流水线。

## 说明

- 运行数据目录（`E:\DeterminFlowData`）由多个项目共用时请勿随意改动。
- 本仓库根目录为 DeterminFlow 上游代码 + 故事机器功能（AGPL-3.0）。

