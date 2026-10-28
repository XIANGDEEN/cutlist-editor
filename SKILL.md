---
name: cutlist-editor
description: 用「剪辑单」（CSV 表格）驱动视频剪辑：用户给素材、入出点与风格，agent 预检、回读、出片、验收。适用于"按我的脚本剪""照这张表剪""精确到 0.1 秒的剪辑""批量出片"，不适用于让 agent 自己挑精彩片段。
license: MIT
---

# 剪辑单剪辑（cutlist-editor）

## 这个技能解决什么

剪辑的决定权在**人**：剪哪段、多长、什么风格，由人写在「剪辑单」里。
agent 的职责是**执行 + 校验 + 报告**，不是当导演。

一句话铁律：**剪辑单是唯一事实源。agent 不自行增删镜头、不自行改入出点。**

## 什么时候用

- 用户有素材 + 明确想剪的段落，要精确执行（入点/出点/速度/转场/字幕）
- 一次要出很多条，靠表格批量而不是靠嘴
- 用户希望"我改表 → 你重出"，而不是"我再跟你描述一遍"

## 什么时候别用

- 用户说"帮我从两小时录像里挑出精彩片段" → 那是**选段**，先产出候选再让用户定稿，不属于本技能
- 用户要成品级调色/特效/合成 → 交给专业 NLE（剪映/达芬奇/PR），本技能只做"按单执行"

## 工作流（五步，不可跳步）

### 1. 收单
让用户提供：全局表 + 镜头表（CSV）。字段见 `references/cutlist-spec.md`。

**缺字段就问，不要猜**。尤其：素材在哪、画幅、BGM。

### 2. 预检（出片前必做）
```bash
python scripts/probe.py <素材目录> --out probe.json
python scripts/check_cutlist.py 剪辑单.csv --probe probe.json
python scripts/preflight.py 剪辑单.csv --probe probe.json --out-dir 成片/
```
`preflight.py` 查环境（ffmpeg 版本与 xfade/ass/zoompan/amix 滤镜、中文字幕字体、磁盘余量）并顺带校验剪辑单；
任何一项 FAIL 就先修环境，别开始渲染。

`check_cutlist.py` 预检必须回答：
- 每个素材存不存在、时长多少（**出点越界 = 直接问用户，不硬剪**）
- 时间码是否可解析、出点是否晚于入点
- 总时长 vs 用户目标时长
- 未知的转场/画面/音效值（会退化成硬切/原样/不配音，必须告知）

预检结果**先给用户看**，有问题就停。

### 3. 回读（最容易救命的一步）
把表格逐行翻译成人话给用户确认：

> 第 1 镜：s1 从 12:30.5 到 12:33.0（2.5 秒），加速 1.25 倍，推近，硬切，字幕「开局第一波」

十条以内全读；超过十条读前三条 + 总时长 + 镜头数，问一句"理解一致吗"。

**回读被否定时，改单不改嘴**：让用户改表，或你改表后再次回读。

### 4. 出片
```bash
python scripts/render.py 剪辑单.csv --out 成片/ --probe probe.json --preview   # 先预览
python scripts/render.py 剪辑单.csv --out 成片/ --probe probe.json             # 再正式
```
产物：`成片/<片名>.mp4` + `成片/report.json`（每镜实际入出点、时长、降级项、放大比例、ffmpeg 能力）。

- 低码率预览给用户看，确认后再出正式版。
- **渲染是原子的**：每镜先写 `clip.part.mp4`，ffmpeg 干净退出才改名成 `clip.mp4`；失败不会留下"看起来能用"的半成品。
- **能力不足就降级不崩**：ffmpeg 没有 `xfade` → 全部转场降为硬切；没有 `fadewhite` → 闪白降为叠化；素材分辨率低于输出 → 标 `upscale` 并写进报告。降级项必须在交付时说出来。

### 4b. 要一份「剪映里能继续编辑」的草稿？
```bash
python scripts/export_jianying_spec.py 剪辑单.csv --project 项目.csv --out spec.json
```
产出 `spec.json`（交给 `jjjane233/jianying-editor-skill-11.5` 的 `jianying.py build`）+ `spec.notes.md`。
本格式表达不了变速/转场/运镜/音效/原声曲线/BGM，这些逐条写进 notes，**不静默丢**。
细节与接线方式见 `references/integration-jianying.md`。

### 5. 验收
按 `references/verify.md` 逐项核对：时长、顺序、音画同步、字幕不越界、无黑帧、无静音陷阱。**没核对的项不许说"完成"。**

## 硬规则

1. 时间码一行只用一种格式：`12:30.5`（分:秒.毫秒）/ `01:02:03.400` / 纯秒 `750.5`
2. 出点必须晚于入点，不做反向推断
3. 空单元格 = 用默认值，**不是**"随便你发挥"
4. 一行一个镜头，**表格行顺序 = 成片顺序**（序号只用于对号）
5. 备注列是给人看的，不直接执行；要执行就把它翻译成参数并回读
6. 不合并单元格、不插合计行
7. 转场列指「本镜切到下一镜」，**最后一镜写转场无效**（会警告，不是静默忽略）

## 常见坑（都是真实踩过的）

- **时间码歧义**：`12:30.5` 必须是 12 分 30.5 秒。曾经用可选分组的正则解析，它把第一个数字贪心当小时，`12:30.5` 变成 12 小时——现在按冒号右对齐分段（`tests/test_skill.py` 有回归）
- **中文字幕**：`drawtext` 在 Windows 上转义地狱，用 ASS 字幕文件（`scripts/render.py` 已内置）
- **变速音画不同步**：视频 `setpts=PTS/N`，音频必须走 `atempo` 链（0.5–2.0 一段，超出要串联）
- **xfade 时长**：叠化会**吃掉**总时长，两镜重叠部分只算一次；算总长时要减
- **xfade 转场名**：`fadewhite` 才是闪白，写 `white` 会报 `const_values array too small`（已修，且运行前会探测 ffmpeg 是否支持）
- **出点越界**：`-ss` 超过源时长会出黑帧，不是报错
- **conform 到统一帧率**：不同素材混剪必须先 `fps=` 统一，否则拼接抽搐

## 参考文件（按需读，别一次全读）

| 文件 | 何时读 |
| --- | --- |
| `references/cutlist-spec.md` | 定义字段、给用户发模板时 |
| `references/style-card.md` | 用户给样片、要抽风格时 |
| `references/ffmpeg-recipes.md` | 手写命令 / 改 render.py 时 |
| `references/verify.md` | 出片前验收 |
| `references/integration-jianying.md` | 要出剪映草稿、或想知道"哪些能自动哪些不能"时 |

## 边界（老实说）

- **本技能不自研剪映草稿格式**：剪映 6.0+ 草稿原生加密，只有官方 DLL 能编解码。需要草稿时用 `export_jianying_spec.py` 导出 `spec.json`，交给 `jjjane233/jianying-editor-skill-11.5`（只验证 11.5.0.14471）；也要接受它的导出仍是人手点
- 不支持"智能抠像/追踪/AI 调色"
- 转场仅支持：硬切 + 叠化 + 闪白（划像会降级为叠化，其余值降级为硬切，都写进报告）
- 音效是**程序化合成**的五个基础音（whoosh/boom/click/pop/riser），不是素材库；要更好的音色就把 wav 放进 `音效目录` 覆盖同名文件
- 不替你判断"好不好看"——验收的最后一步永远是人
