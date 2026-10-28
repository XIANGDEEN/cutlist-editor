# ffmpeg 命令模板（手写时抄这里）

> `scripts/render.py` 内部就是这些命令的组合。手改/嵌进别的流程时照抄，别凭记忆。

## 1. 把一镜 conform 成统一规格

```bash
ffmpeg -y -ss 12:30.5 -t 2.5 -i s1.mp4 \
  -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30" \
  -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 128k -movflags +faststart shot01.mp4
```

- `-ss` 放在 `-i` **前**（快速 seek，代价是可能偏几帧；要求精确就放后面 + `-accurate_seek`）
- `force_original_aspect_ratio=decrease` + `pad` = 留白不裁切；要填满就换 `increase` + `crop`

## 2. 变速（视频 + 音频必须成对）

```bash
# 加速 1.25
-vf "setpts=PTS/1.25" -af "atempo=1.25"

# 慢放 0.5
-vf "setpts=PTS/0.5"  -af "atempo=0.5"

# 4 倍加速：atempo 单段上限 2.0，要串联
-vf "setpts=PTS/4" -af "atempo=2.0,atempo=2.0"
```

**只改 setpts 不改 atempo = 音画不同步**，这是最常见的事故。

## 3. 推近 / 拉远（zoompan）

```bash
# 推近：1.0 → 1.15，d=1 表示每帧算一次
-vf "zoompan=z='min(1+0.0012*on,1.15)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30"

# 拉远：1.15 → 1.0
-vf "zoompan=z='max(1.15-0.0012*on,1.0)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30"
```

注意：`zoompan` 对 4K 源很吃内存；`s=` 必须写目标尺寸，否则按输入尺寸出图。

## 4. 中文字幕（用 ASS，不用 drawtext）

```bash
-vf "ass=cap.ass"          # ffmpeg 的 cwd 设在字幕同目录，用裸文件名，避免 Windows 的 C: 冒号
```

ASS 头必须写 `PlayResX/PlayResY`，否则字号会随分辨率乱飘。描边用 `Outline` + `OutlineColour`。

## 5. 硬切拼接（最快，不重编码）

```bash
# list.txt 里每行 file 'shot01.mp4'
ffmpeg -y -f concat -safe 0 -i list.txt -c copy out.mp4
```

前提：所有片段**编码参数完全一致**（同分辨率/帧率/像素格式/音轨参数），否则会花屏或音画漂移。

## 6. 叠化 / 闪白（xfade 链）

```bash
ffmpeg -y -i a.mp4 -i b.mp4 -filter_complex \
 "[0][1]xfade=transition=fade:duration=0.3:offset=2.2[v]; \
  [0][1]acrossfade=d=0.3:c1=tri:c2=tri[a]" \
 -map "[v]" -map "[a]" -c:v libx264 -crf 20 out.mp4
```

- `offset` = 前一段时长 − 叠化时长
- **叠化会让总时长变短**：3 段各 2 秒、叠化 0.3，总长 = 2+2+2−0.3−0.3 = 5.4 秒
- 闪白：`transition=white`；划像：`transition=wipeleft`

## 7. BGM 混音（原声为主，BGM 垫底）

```bash
ffmpeg -y -i clip.mp4 -i bgm.mp3 -filter_complex \
 "[1:a]volume=0.6,aloop=loop=-1:size=2e9[bg]; \
  [0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]" \
 -map 0:v -map "[a]" -c:v copy -c:a aac out.mp4
```

要"原声一响 BGM 就退"需要 `sidechaincompress`，v1 不做，靠用户手调音量。

## 8. 抽封面

```bash
ffmpeg -y -ss 1.0 -i clip.mp4 -frames:v 1 -q:v 3 cover.jpg
```

## 9. 自检

```bash
ffprobe -v error -show_entries format=duration:stream=width,height,r_frame_rate,codec_type -of json out.mp4
ffmpeg -i out.mp4 -vf blackdetect=d=0.1:pix_th=0.10 -an -f null - 2>&1 | grep blackdetect
ffmpeg -i out.mp4 -af silencedetect=n=-40dB:d=1 -f null - 2>&1 | grep silence
```
