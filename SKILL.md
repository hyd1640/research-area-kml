---
name: research-area-kml
description: 从论文 PDF 或地图提取研究区，导出 WGS84 KML 并合并为带论文正式标题字段的 Shapefile；优先数字化明确轮廓，无明确轮廓时采用带可靠坐标的地图面板完整矩形。适用于论文研究区提取、地图数字化配准与 KML 合并；不虚构精确边界。
---

# Paper study-area map → WGS84 KML

## 目标与不可违背的规则

从用户提供的 PDF / 地图照片 / 图件，**优先利用研究区范围示意图的轮廓**制作 KML 面矢量。**没有明确研究区轮廓时，默认优先选择带经纬度等可靠坐标的相关地图面板，以其完整矩形范围作为工作研究区**，标记为“图幅矩形范围 / MAP_FRAME_EXTENT”。这是已约定的降级规则，无须再询问是否使用地图框。图件无法提供可配准轮廓或地图范围时，再查正文经纬度等辅助信息。各类结果须如实标注来源。

**逐篇输出 KML，并在批次结束后将本批逐篇 KML 合并为一个 Shapefile 数据集**。两者坐标均为 WGS84（EPSG:4326）；KML 坐标顺序为 lon, lat, altitude，不写入米制坐标。Shapefile 必须有 `paper_name`（论文名）字段，值为文献正式标题；不能用 PDF 文件名、文件 stem、图件标题或论文简称代替。

**不得虚构边界精度。** 如果没有足够几何或地理配准证据，明确说明无法可靠提取；可以在已知经纬度范围时制作**标记为矩形代理/仅定位用途**的 KML，而不是假装得到真实边界。

## 操作顺序（必须依次判断）

1. **检索论文与选图。** 检查所有标题或图注包含 `Study area`, `Location`, `Research area`, `Geographic`, `研究区`, `位置`, `地理位置` 的图；优先 Fig. 1 但不预设页码。通过 `scripts/prepare_pdf.py --find` 辅助查找，检查实际渲染页面。如果定位图没有刻度、边界被裁掉或被符号遮挡，继续检查后续 DEM、滑坡清单和易发性图中是否重复绘出同一边界，并用图例核对其身份。PDF 原生矢量路径和嵌入的 GIS 附件可优先调查，但不能假定 PDF 路径自带坐标系。

   同时从 PDF 首页可见标题核对文献正式名称，保存 `source.paper_title`、`source.title_source`，有 DOI 时一并记录。PDF 元数据仅作候选，它可能是制作软件文件名或截断标题；不能单独作为核对证据。首页无法辨认时，可用 DOI 对应的出版商或可靠书目记录核实。未确认标题时明确记录待补，不用文件名兜底冒充论文名。
2. **识别轮廓或采用图幅范围。** 有明确研究区轮廓时保留折点、曲线、内洞和多块分区，不用矩形替代。无明确轮廓时，优先选择直接展示研究对象且带可靠坐标的详细地图；以**地图面板内的完整矩形框**为工作研究区。多面板图分别判断，不取整张 PDF 页、整组插图或更宽泛的位置索引图。图例、比例尺和黑色无影像区若位于面板内，均保留在矩形中，不挖洞。影像覆盖外缘可作为辅助结果保留。若已知轮廓仅在当前图被裁切，先查其他图件补全。
3. **先在图上找配准证据。** 优先图中的经纬网刻度、网格交点；其次可核验的控制点坐标，包括表格中有坐标、图上能确认位置的钻孔等；再考虑地理配准的原始影像/已知 GIS 数据。记录 **像素坐标和经纬度对照关系**。米制 Easting/Northing 刻度也可用，但必须先确认原 CRS，使用 `projected_ticks` 转为 WGS84；不能把米数直接写成经纬度。地图是倾斜、透视、非北向时，不要直接假设 X 对应经度、Y 对应纬度；使用多个非共线地面控制点（GCP）或专业 GIS 配准。
4. **图件信息不足时再查正文。** 查找“Study area”段落、Figure caption、补充材料，经纬度范围、行政区、面积、研究区边界构建方法。优先用正文经纬度范围对图上已描绘轮廓做位置/尺度辅助约束；**只有有证据表明文字范围恰为轮廓极值**才允许执行 `outline_bbox_fit`，并明确低置信度。禁止将文字范围直接当成逐点边界。
5. **数字化与配准。** 把明确轮廓描为像素折点；图幅范围则记录 `boundary_role=map_frame_extent`、`map_frame_pixels=[left,top,right,bottom]`、`confidence=low`，名称含 `MAP_FRAME_EXTENT`，不要再填 `boundary_pixels` 或 `polygons`。按 [references/methodology.md](references/methodology.md) 编写配置；[合成示例](examples/config.synthetic.json) 仅供离线演示。选用 `axis_ticks`、`projected_ticks` 或 `affine_gcps` 配准。图幅范围必须基于图上配准，不能用正文极值的 `outline_bbox_fit` 代替；后者仅用于有明确轮廓且满足极值证据条件的降级定位。运行 `scripts/export_kml.py`。
6. **质量门槛和复核。** 检查 PNG 叠加图：明确轮廓是否贴合外缘、图幅降级范围是否覆盖完整地图面板、经纬度刻度是否对应。颜色分割只能辅助已确认的图面对象，河流、断层和注记可把分割轮廓引入内部；发现后重新描边。检查 KML 经度纬度范围、环闭合、拓扑有效性、WGS84 测地面积以及正文给出的面积（若有）。区分研究域面积、滑坡总面积、受影响面积与堰塞湖面积。**面积接近不代表几何精度足够**；文字、图件和面积冲突时保留差异并降级，不靠缩放、凸包或缓冲补齐。对原图不可辨的部分注明估计，不自动平滑虚构折点。
7. **交付与证据。** 优先给 `study_area_WGS84_EPSG4326.kml`，并保留 `study_area_overlay.png`、`study_area_provenance.json`、`study_area_QA.md`。解释来源页码、图号、所用控制点、是否仅近似、哪些信息来自正文。用户明确“只要 KML”时仍可将 QA 作为内部记录，而不是附带多余投影文件。
8. **合并为一个 SHP。** 对本批成功导出的逐篇 KML 建立清单，运行 `scripts/merge_kml_to_shp.py`。按面追加记录，不跨论文融合几何；同篇多分区重复保留相同正式标题。辅助覆盖面也进入同一 SHP，保留 `area_role=coverage_footprint`；图文冲突结果用 `qa_status=provisional` 标注。只列逐篇源文件，不把它们的 KML 合集重复加入。回读检查要素数、标题、UTF-8、几何和 EPSG:4326，再交付 `.shp/.shx/.dbf/.prj/.cpg` 的完整 ZIP，另附属性 CSV 和来源清单。字段及清单见 [合并配置](references/methodology.md#kml-合并为一个-shapefile)。

### 分支判定（高到低）

| 级别 | 条件 | 产物与如实标注 |
|---|---|---|
| A | 作者提供原始带 CRS 的研究区几何 | 使用原数据转为 WGS84 KML；核查来源和 CRS |
| B | 可明确识别图上边界，且有可信图上控制点/经纬网 | 图上数字化 KML，`figure_digitized`、注明近似 |
| M | 无明确研究区轮廓，但相关地图面板有可靠经纬网或其他配准依据 | 默认输出完整图幅矩形，`map_frame_extent`、`confidence=low`、名称含 `MAP_FRAME_EXTENT`；说明选图理由 |
| C | 有可识别边界但只有正文整体经纬度范围，且有依据认定范围对应轮廓极值 | 使用 `outline_bbox_fit`，标明 `low` 置信度和强假设 |
| D | 边界不可识别，仅有文字经纬度范围 | **仅可制作经纬度矩形代理**：使用 `--allow-bbox-proxy`，名称含 `BBOX_PROXY_NOT_BOUNDARY`，绝不能叫“精确研究区边界” |
| E | 无法确认边界，也没有可用配准依据 | 不输出伪造坐标的 KML；要求原始 GIS / 高清地图 / 至少 3 个可信控制点 |

证据等级和可用状态应分开记录。B 级图件也可能与正文矛盾，只能交付待复核结果。M 类是按本技能规则采用的工作研究区，不代表作者明确划出的边界。图中仅有 UAV / 影像覆盖轮廓时，优先检查是否可用完整地图面板走 M 类，并可额外交付 `boundary_role=coverage_footprint`，名称含 `NOT_CONFIRMED_STUDY_BOUNDARY`。仅有滑坡点、震中或等震线时，不用凸包、缓冲或等震线替代研究区；地图面板有可用坐标时仍可走 M 类。单滑坡论文可交付 `landslide_boundary`；原图推断线段仍须注明。

## 安装与命令

在 Skill 根目录执行：

```bash
python -m pip install -r requirements.txt
python scripts/prepare_pdf.py --pdf /path/article.pdf --find
python scripts/prepare_pdf.py --pdf /path/article.pdf --page 2 --dpi 300 --out /tmp/page2.png
# 检查渲染图，裁出真正地图面板；将边界折点和刻度填入 JSON
# 可选：生成离线点击描边页面，在浏览器中打开并导出 boundary_pixels
python scripts/make_digitizer_html.py --image /path/map_crop.png --out /tmp/digitize.html
python scripts/export_kml.py --config /path/config.json --image /path/map_crop.png --outdir /path/output
python scripts/merge_kml_to_shp.py --manifest /path/merge_manifest.json --out /path/output/merged_study_areas.shp
```

- 裁图可用 `prepare_pdf.py --crop-pixels X0 Y0 X1 Y1`；裁图以后 **所有像素坐标都以裁图左上角为原点**。
- 无明确轮廓且地图有可用坐标时，使用 `map_frame_extent`，须提供 `--image`，无需 `--allow-bbox-proxy`。角点按刻度换算，不把范围凑整到最外侧标注值。
- 图幅无法配准、仅剩正文经纬范围时，才使用 `text_bbox_proxy` 和 `--allow-bbox-proxy`；它与图幅矩形降级结果不同。
- 没有图片时，已知真实 GIS 边界可直接用 GIS 软件转 KML；本脚本主攻**图件数字化**，不是万能自动图像分割器。

## 重要限制和失败处理

- 文献中的 `115°09′E–116°14′E` 是**范围**而不是形状。论文面积可用于检查，不可凭面积拟合/修补多边形。
- 视觉描图的最小空间分辨率受原始图像、缩放、线宽、像素选点、配准残差和地图投影影响。仅根据两个 X 刻度和两个 Y 刻度拟合出的零残差是数学必然，**不能充当独立精度检验**。
- GCP 留一验证只衡量控制点内部一致性；记录边界顶点是否落在控制点凸包外。大量外推时不能用中央控制点的小残差宣称整条边界具有同等精度。未知基准必须写入 `datum_note`。
- 地图上的经纬网刻度可能来自非等经纬间距的投影，若出现扭曲或旋转，禁用 `axis_ticks`。复杂投影优先使用 GDAL/QGIS 地理配准。
- `EPSG:3857` 的面积不保真；面积核查使用 WGS84 椭球测地面积或恰当的等积投影。
- 文献地图或其图像属于来源材料，不把原图夹带进可再分发 Skill 模板；用户自行提供地图。

配置字段、配准方法和复核指标见 [references/methodology.md](references/methodology.md)。本技能的核心工具可运行 `python -m unittest discover -s tests -v` 验证；真实论文的图件与测试产物放在用户工作目录，不夹带进可再分发技能包。
