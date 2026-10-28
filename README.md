# cutlist-editor

**用一张表格剪片。** 人负责决定剪哪段、怎么剪，agent 负责精确执行、校验、出片。

An agent skill that turns a **cut list** (a CSV shot table) into a finished video: no
auto-highlight guessing, no "AI decides for you" — you write the shots, it renders them.

```bash
python scripts/probe.py D:\game\session --out probe.json
python scripts/preflight.py 镜头表.csv --project 项目.csv --probe probe.json
python scripts/check_cutlist.py 镜头表.csv --project 项目.csv --probe probe.json
python scripts/render.py 镜头表.csv --project 项目.csv --probe probe.json --out out/
# 可选：导出一份剪映能继续编辑的草稿规格
python scripts/export_jianying_spec.py 镜头表.csv --project 项目.csv --out spec.json
```

## 为什么是"表格驱动"

自动剪辑工具替你决定剪什么，出片十有八九不是你想要的。
真正的剪辑师不会这样干活：**导演给镜头表，剪辑师负责落地**。

所以这个技能把决策权完全交回给你：

| 你 | agent |
| --- | --- |
| 写剪辑单（哪条素材、入点出点、速度、转场、字幕） | 预检素材、回读确认、渲染、验收、出报告 |
| 给风格样片 | 从样片抽参数、填风格卡给你确认 |
| 说哪里不对 | 改单重跑，不辩解 |

## 安装

**没有第三方依赖**，只需要 Python 3.9+ 和 PATH 上的 `ffmpeg` / `ffprobe`。

作为 agent skill 使用，把整个目录放进你的技能根目录即可：

| agent | 落点 |
| --- | --- |
| DeepSeek Harness | `<项目>/.dsh/skills/cutlist-editor/` 或 `~/.agents/skills/cutlist-editor/` |
| Claude Code | `~/.claude/skills/cutlist-editor/` 或 `<项目>/.claude/skills/` |
| 其他 agent | 支持 `SKILL.md` 约定的框架，放进其 skills 目录 |

`SKILL.md` 是 agent 的入口（工作流、硬规则、常见坑），`references/` 是它只在需要时才读的细节。

## 剪辑单长什么样

`镜头表.csv` —— 一行一个镜头，行顺序就是成片顺序：

```csv
序号,素材,入点,出点,时长,速度,画面,转场,字幕,字幕样式,声音,备注
1,01.mp4,0:12.5,0:15.0,,1.25,推近,硬切,开局第一波,预设,原声,从进房开始剪
2,01.mp4,0:48.0,0:52.4,,0.5,局部放大:中,闪白 0.15,三杀,强调,原声,慢放，保留播报音
3,02.mp4,0:08.0,0:11.5,,1.0,原样,叠化 0.3,残局翻盘,预设,压低,结尾，BGM 收一下
```

`项目.csv` —— 全局设置：

```csv
字段,值
片名,集锦-01
画幅,竖屏
帧率,30
素材文件夹,D:\game\2026-10-28
BGM 文件,D:\game\bgm\bgm01.mp3
BGM 音量,0.5
原声处理,保留
字幕字体,微软雅黑
```

完整字段、允许值、校验规则见 [`references/cutlist-spec.md`](references/cutlist-spec.md)。

## 支持的能力

| 能力 | 状态 |
| --- | --- |
| 精确入出点（0.1 秒）、跨素材拼接 | ✅ |
| 变速（0.25–4×，音轨同步 `atempo`） | ✅ |
| 竖屏留白 / 横屏 / 方形 | ✅ |
| 推近、拉远（`zoompan` 动画） | ✅ |
| 局部放大（左/中/右静态裁切） | ✅ |
| 转场：硬切、叠化、闪白、划像 | ✅ |
| 中文字幕（ASS + 描边，三种字号） | ✅ |
| BGM 混音、原声保留/静音/压低 | ✅ |
| 音效（`呼呼/重击/咔/弹出/上升`，缺文件自动合成后混入） | ✅ |
| 环境预检（ffmpeg 滤镜 / 中文字体 / 磁盘 / 剪辑单） | ✅ |
| 原子出片（先写 `.part`，成功才改名，不留半成品） | ✅ |
| 能力不足自动降级（无 xfade → 硬切；无 fadewhite → 叠化；源分辨率低 → 标 `upscale`） | ✅ |
| 逐镜报告 `report.json`（计划 vs 实际、降级项、放大比例、ffmpeg 能力） | ✅ |
| 导出剪映草稿规格 `spec.json`（交给 11.5 适配工具写草稿） | ⚠️ 需对方工具，且损失变速/转场/运镜/音效 |
| 智能抠像、主体追踪、AI 调色 | ❌ |
| 自己写剪映草稿（6.0+ 原生加密，只有官方 DLL 能编解码） | ❌ 不碰 |
| 自动决定剪哪段 | ❌（这是设计取舍，不是缺陷） |

降级行为**一律写进报告**，不静默糊弄：`抖动` 降级为原样，未知转场降级为硬切。

## 目录

```text
SKILL.md                     agent 入口：工作流 / 硬规则 / 常见坑
references/
  cutlist-spec.md            字段与允许值、校验规则
  style-card.md              从样片抽风格的八维方法
  ffmpeg-recipes.md          命令模板（变速/推镜/字幕/叠化/混音）
  verify.md                  出片验收清单
  integration-jianying.md    剪映 11.5 的模式拆解 + 草稿接线（我们抄了什么、没抄什么）
scripts/
  probe.py                   扫素材，出 probe.json
  preflight.py               环境自检（ffmpeg 滤镜/字体/磁盘/剪辑单）
  check_cutlist.py           解析 + 校验 + 生成时间线
  render.py                  逐镜渲染 → 拼接/叠化 → 混音 → report.json
  gen_sfx.py                 程序化合成基础音效（缺哪个造哪个）
  export_jianying_spec.py    剪辑单 → 剪映 11.5 分支可用的 spec.json
tests/
  test_skill.py              纯 stdlib 自测（解析/校验/导出，不需要 ffmpeg）
examples/
  项目.example.csv
  镜头表.example.csv
```

## 出片流程

```text
probe      →  probe.json        素材时长/分辨率/有无音轨
preflight  →  环境 + 剪辑单      滤镜/字体/磁盘/表结构，一次查完
check      →  校验表 + 时间线    出点越界、速度越界、未知值都会报
render     →  _work/shotNN/     每镜一个 intermediate（先写 .part，成功才改名）
           →  _work/joined.mp4  全硬切走 concat -c copy（快），有转场走 xfade（重编码）
           →  out/<片名>.mp4    混 BGM 之后的成片
           →  out/report.json   逐镜 planned vs actual、降级项、放大比例、ffmpeg 能力
```

## Windows 注意

控制台默认代码页不是 UTF-8，中文输出会乱码或直接抛 `UnicodeEncodeError`：

```powershell
chcp 65001
```

脚本已把 stdout/stderr 重设为 UTF-8，但**终端本身**仍要切到 65001 才能正确显示。

## 换一台电脑要做什么

ffmpeg 直出路线**零配置**，不碰剪映、不碰任何 DLL：

```bash
python scripts/preflight.py 镜头表.csv --project 项目.csv
```

它会把"这台机器能不能出片"一次查完（Python / ffmpeg / 四个滤镜 / 中文字体 / 磁盘 / 剪辑单）。
最后一行 `剪映草稿路线（可选）` 是**参考信息，不参与出片判定**——只有你还想让产物变成剪映草稿时才需要它。

真要走草稿路线，它耦合的是**版本 + 安装路径**两件事，不是"每台机器都得改代码"：

| 条件 | 说明 | 不满足时 |
|---|---|---|
| 剪映版本 = `11.5.0.14471` | 草稿编解码 ABI 随版本走，只验证过这一个构建 | 要么装该版本，要么继续 ffmpeg 直出 |
| DLL 在 `%LOCALAPPDATA%\JianyingPro\Apps\11.5.0.14471\videoeditor.dll` | 第三方工具写死了这个路径，没有环境变量开关 | 建一条 junction 即可，不必改它的代码 |

```powershell
mklink /J "%LOCALAPPDATA%\JianyingPro\Apps\11.5.0.14471" "E:\JianyingPro\11.5.0.14471"
```

**不要**把 `videoeditor.dll` 单独复制出来：它靠同目录的依赖 DLL 加载，单拷一个大概率 `WinDLL` 失败。

## 自测

```bash
python -m unittest discover -s tests -v      # 23 个用例，不需要 ffmpeg
python tools/make_selftest.py                # 造一个能真跑的 _selftest/（合成素材 + 剪辑单）
python scripts/preflight.py    _selftest/镜头表.csv --project _selftest/项目.csv
python scripts/check_cutlist.py _selftest/镜头表.csv --project _selftest/项目.csv
python scripts/render.py       _selftest/镜头表.csv --project _selftest/项目.csv --out _selftest/out --preview
```

`examples/` 是**模板**，素材路径是虚构的，直接跑会（正确地）报"素材不存在"——要真跑就用 `make_selftest.py`。
`--dry-run` 只打印 ffmpeg 命令，不执行——审阅用。
自测里那条 `12:30.5` 的回归用例是真实事故：早先用可选分组的正则，把 12 分读成了 12 小时。

## 已知限制

- 叠化会**吃掉**总时长（两镜重叠只算一次），`report.json` 的 `planned_total` 已扣除
- 混剪不同帧率素材前会统一 `fps`，但极其卡顿的源可能出现轻微顿感
- 局部放大是**静态裁切**：竖屏从横屏素材里切一条，画质损失明显，慎用
- xfade 路径全片重编码，长片较慢；全硬切走 `-c copy` 秒出
- 剪映草稿只做 `spec.json` 交接，且只对 `11.5.0.14471` 那套工具成立；它升级/剪映升级都可能失效
- 音效是合成的五个基础音，不是素材库；要好音色就把 wav 丢进 `音效目录` 同名覆盖

## License

MIT
