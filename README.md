# research-area-kml — Codex / Agent Skill

本 Skill 从论文 PDF 或地图提取研究区，逐篇生成 WGS84（EPSG:4326）KML，最终合并为**一个带论文正式标题字段的 Shapefile**。优先数字化明确轮廓；没有明确轮廓时，采用带可靠坐标的相关地图面板完整矩形，标记为 `MAP_FRAME_EXTENT`。

仓库：[hyd1640/research-area-kml](https://github.com/hyd1640/research-area-kml)。可通过 GitHub 的 **Code → Download ZIP** 下载，或克隆仓库：

```bash
git clone https://github.com/hyd1640/research-area-kml.git
```

## 安装

将此目录 `research-area-kml` 放到当前 Codex 项目的 `.agents/skills/`：

```bash
mkdir -p .agents/skills
cp -R research-area-kml .agents/skills/research-area-kml
python -m pip install -r .agents/skills/research-area-kml/requirements.txt
```

也可以安装到用户个人的 `~/.agents/skills/research-area-kml`（依 Agent 支持的技能搜索路径而定）。

Codex 使用示例：

```text
$research-area-kml 请从这些论文的研究区图提取研究区，逐篇输出 WGS84 KML，最终合并为一个带正式论文标题 paper_name 字段的 SHP。
优先查看研究区示意图和经纬网，图件无法有效配准时再查正文经纬度提示。
保留数字化和质量核查依据。没有明确轮廓时，按默认规则采用完整地图面板矩形，并注明“图幅矩形范围”。
```

其他遵循 Agent Skills 标准的 Agent：将本文件夹放到各自 Skills 目录，使其可以读取 `SKILL.md`，并提供本地 Python、图像阅读和文件工具即可。具体安装路径可能不同。

## 本地离线工作流

```bash
# 1. 在论文内寻找研究区图件
python scripts/prepare_pdf.py --pdf "/path/paper.pdf" --find

# 2. 渲染候选研究区页面（PDF 页面从 1 开始）
python scripts/prepare_pdf.py --pdf "/path/paper.pdf" --page 2 --dpi 300 --out /tmp/page2.png

# 3. 裁图、用视觉检查确定真实边界和经纬度图上刻度
#    可用以下辅助页面鼠标逐点描研究区外边界（不是自动识别）
python scripts/make_digitizer_html.py --image "/path/map_crop.png" --out "/tmp/digitize.html"

# 4. 将轮廓 boundary_pixels 或图幅 map_frame_pixels、图上刻度、来源元数据写入 JSON
python scripts/export_kml.py --config /path/config.json --image /path/map_crop.png --outdir /path/kml_result

# 5. 复核 study_area_overlay.png 和 study_area_QA.md

# 6. 从 PDF 首页核对正式标题，整理合并清单；合并所有逐篇 KML
python scripts/merge_kml_to_shp.py --manifest /path/merge_manifest.json --out /path/merged_study_areas.shp
```

主输出：逐篇 `study_area_WGS84_EPSG4326.kml` 和最终合并的 Shapefile 完整 ZIP。辅助：叠加图、来源/核查记录、坐标表和合并属性 CSV。

合并后的 `paper_name` 字段保存从 PDF 首页核对的完整文献标题，**不是 PDF 文件名**。每个面是一条记录，同篇多个分区共享标题；保留 `area_role`、`qa_status` 以区分图幅矩形、辅助覆盖和待复核结果。清单结构及完整字段说明见 [methodology.md](references/methodology.md#kml-合并为一个-shapefile)。

## 示例和验证

提供 `examples/config.synthetic.json` 演示导出，全部坐标与标题均为合成测试数据，不代表真实论文研究区：

```bash
python scripts/export_kml.py --config examples/config.synthetic.json --outdir /tmp/synthetic
```

完整离线合成演示（不代表真实论文）：

```bash
python scripts/export_kml.py --config examples/config.synthetic.json --outdir demo_output
python scripts/merge_kml_to_shp.py --manifest examples/merge.synthetic.json --out demo_output/merged_study_areas.shp
```

支持经纬网、已知 CRS 的投影坐标刻度、多控制点仿射配准，以及有证据约束的低置信度降级方法。配置字段见 `references/methodology.md`。裁图坐标、图像尺寸和图像哈希可保留在配置中，避免换图后误用像素点。真实论文测试产物保留在用户工作目录，不纳入技能包。

图幅降级配置用 `boundary_role=map_frame_extent`、`map_frame_pixels=[left,top,right,bottom]`、`confidence=low`，名称含 `MAP_FRAME_EXTENT`。必须提供地图图像及图上配准，不需要 `--allow-bbox-proxy`。矩形包含图框内的图例、比例尺和黑色背景；原 UAV 覆盖可单独保留为辅助面。

运行本地检查：

```bash
python -m unittest discover -s tests -v
```

## 局限、优劣与结果判断

优点：强制保留图件几何信息、KML 坐标规范正确、可审计图上刻度与像素描边、对无效拓扑/伪精确文本矩形有安全门槛，提供视觉核查图。

局限：不同论文图形和地图投影差异很大，**不可能只用一次通用颜色阈值自动可靠分割所有研究区**。初始数字化/图件判别需具备视觉能力的 Agent 或人工辅助；无法验证的经纬度图件不应输出“精确边界”。经纬度拟合低残差或面积接近不等于位置精度通过校验。
