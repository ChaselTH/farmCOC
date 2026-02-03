# farmCOC

基于 macOS 的自动化脚本：通过识别特定像素颜色与 OCR 读取百分比，自动执行点击流程。核心配置集中在 `config.yaml`，需要根据你的屏幕坐标进行修改。

## 环境要求
- macOS（使用 `screencapture`、Quartz/Vision）
- Python 3
- 依赖：`pynput`、`Pillow`、`pyyaml`
- 命令行工具：`cliclick`（用于模拟点击）

## 安装依赖
```bash
pip install pynput pillow pyyaml
brew install cliclick
```

## 使用方法
1. **修改配置坐标（最重要）**：打开 `config.yaml`，将 `click_regions`、`detect_points`、`detect_regions` 中的坐标改成你屏幕上对应元素的位置。
2. 运行脚本：
   ```bash
   python main.py
   ```
3. 运行中按 `ESC` 可停止。

## 配置说明（config.yaml）
所有坐标均为**屏幕坐标**，以像素为单位。

### screen
- `scale`: 缩放倍数。若你使用不同分辨率或缩放，可整体放大/缩小所有坐标。
- `random_click.margin`: 随机点击时，离区域边缘的最小距离（避免点到边框）。
- `random_click.seed`: 固定随机种子（可复现随机点击轨迹），`null` 为随机。

### timing
点击间隔与轮询间隔的随机范围，以及等待超时等控制参数。

### click_regions（主要修改）
每个点击区域由两个点 `p1`/`p2` 构成矩形区域，脚本会在矩形内随机点一下：
- `start` / `fight`: 进入战斗相关按钮
- `select_1` ~ `select_5`: 选择按钮
- `place_1` ~ `place_8`: 放置位置
- `cancel` / `confirm` / `back`: 取消流程相关按钮

### detect_points
用于识别“在主页/在战斗界面”的像素点位置。

### detect_points_expected_color
与 `detect_points` 对应的目标颜色（RGB）。

### detect_regions
用于 OCR 识别百分比的区域矩形，`percent` 需覆盖百分比数字显示区域。

## 坐标如何测量
建议用截图工具或取色工具获取坐标与颜色。你也可以用系统截图（如 `screencapture`）配合图像工具查看像素坐标。
