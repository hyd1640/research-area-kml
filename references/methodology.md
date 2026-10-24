# 配置与误差记录

所有数字化坐标以**裁图左上角**为原点；PNG 改 DPI、缩放或裁切后必须重新记录坐标。`image_size` 必须与文件匹配，可加 `image_sha256` 锁定文件。`source` 应记录 PDF 文件、PDF 实际页码（从 1 开始）、图号、渲染 DPI、裁图像素框，批处理建议保存 PDF SHA256。

## 最小配置

```json
{
  "name": "Study area - figure approximation",
  "confidence": "medium",
  "boundary_role": "study_boundary",
  "boundary_complete": true,
  "source": {"pdf": "article.pdf", "pdf_page": 3, "figure": "Fig.2", "paper_title": "从首页核对的文献完整标题", "title_source": {"type": "pdf_title", "page": 1}},
  "datum_note": "WGS84 is stated / datum is assumed and not independently verified",
  "boundary_evidence": "图例明确指认该轮廓，说明排除了哪些相似对象",
  "image_size": [1000, 800],
  "boundary_pixels": [[100,100],[700,150],[800,600],[200,650]],
  "registration": {
    "method": "axis_ticks", "north_up_confirmed": true,
    "x_ticks": [[100,103.5],[800,104]],
    "y_ticks": [[100,33.5],[650,33]]
  },
  "limitations": ["手工数字化近似，未取得作者 GIS 真值"]
}
```

多个独立分区改用 `polygons`：每项含 `name`、`boundary_pixels`，可加 `holes_pixels`（若干独立内环）。不要把分区间的空白连起来。不要同时维护顶层 `boundary_pixels` 和 `polygons`；导出时 `polygons` 优先。

## 配准方法

- `axis_ticks`：`x_ticks` 是 `[像素X, 经度]`，`y_ticks` 是 `[像素Y, 纬度]`。仅用于已目视核对的正北向经纬图。每轴至少两点，额外刻度可检查一致性。角度先转换十进制，例如 `103°40′E=103+40/60`；西经、南纬取负。
- `projected_ticks`：字段同上，但数值为图上投影单位；增加 `map_crs`，例如 `EPSG:32648`。根据坐标轴拟合地图坐标，再由 pyproj 转 EPSG:4326。正北向在此指图面 X/Y 与投影坐标轴平行。
- `affine_gcps`：`gcps` 每项是 `{"id":"ZK01","pixel":[x,y],"lonlat":[lon,lat]}`；至少三个非共线点，可加 `fit_crs` 在适当的局部米制投影拟合。输出训练残差、可计算时的留一残差和凸包外顶点数量。不把这三类指标解释为外部定位精度。
- 可选独立检查点：在以上配准对象增加 `checkpoints`，每项含 `pixel` 和 `lonlat`，且不得重复拟合用的点。结果记录测地距离误差。
- `outline_bbox_fit`：需要 `bounds_lonlat=[W,S,E,N]` 和非空 `extrema_evidence`，说明为何正文范围对应轮廓极值；顶层 `confidence` 必须是 `low`。只对轮廓保持形状的降级定位使用，原地图若是投影图，强制经纬度极值仍可能扭曲位置。
- `text_bbox_proxy`：需要 `bounds_lonlat`；顶层 `boundary_role=bbox_proxy`、`confidence=low`，名称含 `BBOX_PROXY_NOT_BOUNDARY`，命令加 `--allow-bbox-proxy`。它不是实际边界。

## 无明确轮廓时的图幅矩形

默认以带可靠坐标的相关地图面板完整矩形作为工作研究区。选择直接展示研究对象的详细地图；多面板位置图中不把全页或更广的索引地图一起框入。保留面板内的图例、比例尺和无影像区，不挖洞。已有明确轮廓时仍优先数字化原轮廓。

沿用最小配置中的来源、图像信息和图上配准，改为：

```json
{
  "name": "Study area - MAP_FRAME_EXTENT",
  "confidence": "low",
  "boundary_role": "map_frame_extent",
  "boundary_complete": true,
  "map_frame_pixels": [60, 50, 940, 750]
}
```

这是字段替换片段，需补上最小配置中的 `source`、`datum_note`、`boundary_evidence`、`image_size` 和 `registration`；删除 `boundary_pixels` 和 `polygons`。必须提供源图 `--image`，范围必须位于图像内。`registration.method` 只能是 `axis_ticks`、`projected_ticks` 或 `affine_gcps`，不得用正文极值拟合替代图上坐标。无需 `--allow-bbox-proxy`。

导出器按完整矩形生成四个角点，按刻度内插/外推到真正图框，不将范围凑整到最外侧标注值。配准须适合图面；旋转图不能使用正北向轴刻度假设。KML 和 provenance 记录 `boundary_role=map_frame_extent`、`extent_basis=georeferenced_map_frame` 与 low 置信度。这是规则采用的工作研究区，不能称为作者原始边界或精确边界。

## 导出与核查

`export_kml.py` 验证多面与洞拓扑，拒绝自交、重叠、退化或非法经纬度，不调用 `buffer(0)` 等方法悄悄修复。KML 外环逆时针、内环顺时针，环闭合，顺序为 `lon,lat,0`。面积使用 WGS84 椭球测地面积；只有用户明确需要时再额外导出其他 GIS 格式。

`reference_area_km2` 为可选对照值；超过 10% 差异时给出诊断提醒，但不会修改几何。该阈值不是精度验收阈值。多个论文面积定义不一致时分别保存说明；不能把滑坡面积或堰塞湖面积用于强制拟合研究域。

叠加图只检验像素描边是否沿着目标轮廓，不证明坐标变换正确。每份结果均需人工/视觉复核来源、刻度位置和对象语义。未知 datum、分辨率限制、被注记遮挡、裁切边缘、作者推断线和外推区域均写入 limitations。无作者原始边界或独立真值，不报告边界准确率、IoU 或米级定位精度。

## KML 合并为一个 Shapefile

逐篇导出后必须执行本步骤。合并是追加面要素，不做跨论文 dissolve；一个 KML 有三个分区时输出三条记录，各条记录保留同一个文献正式标题。辅助覆盖范围同样收入本批唯一的 SHP，靠 `area_role` 区分；不得重复加入已经汇总过的合集 KML。

清单路径相对于清单 JSON 所在目录：

```json
{
  "sources": [
    {
      "paper_id": "01",
      "kml": "01/result/study_area_WGS84_EPSG4326.kml",
      "paper_title": "从 PDF 首页核对的正式完整标题",
      "title_source": {"type": "pdf_title", "pdf": "input.pdf", "page": 1},
      "doi": "10.xxxx/verified-doi-if-available",
      "qa_status": "approximate"
    }
  ]
}
```

`paper_title` 与 `title_source` 必填；来源类型支持 `pdf_title`、`publisher_title`、`bibliographic_record`。标题优先核对 PDF 首页；同一标题可规范合并换行和断词，保留副标题，不以 PDF 文件名、元数据制作文件名或自拟简称代替。出版商或书目记录应在 `title_source` 留链接/标识。KML 本身有 `paper_title` 时必须与清单一致。

字段如下，均使用不超过 10 个字符的字段名：

| 字段 | 内容 |
|---|---|
| `paper_name` | 论文名：核对后的完整文献标题，UTF-8 字符串 |
| `paper_id` | 稳定论文编号，同篇多个面保持一致 |
| `part_name` | KML 原 Placemark 名称，例如分区名 |
| `area_role` | study_boundary / map_frame_extent / landslide_boundary / coverage_footprint 等 |
| `confidence` | 原 KML 的置信度 |
| `qa_status` | approximate / provisional / auxiliary 等来源状态 |
| `doi` | 已核实 DOI；没有则留空 |
| `kml_file` | 清单中的来源 KML 路径 |
| `area_km2` | 当前面 WGS84 椭球测地面积（km²） |

输出同名 `.shp/.shx/.dbf/.prj/.cpg`，坐标 EPSG:4326、编码 UTF-8，并生成属性 `.csv`、来源/核查 `.json` 和包含全部这些文件的 `.zip`。不要只发送 `.shp`；读取属性需要同目录同名的 DBF 等配套文件。SHP 外环为顺时针、内洞逆时针，与 KML 环方向不同。

脚本在写入前检查字段 UTF-8 字节宽度，`paper_name` 本版设置为 254 字节；超出则拒绝输出并明确报错，不悄悄截断。遇到超长标题应调整为可完整保存的字段方案并复核，不能在合并失败后仍报告成功。字段长度、编码与环方向的格式依据见 [GDAL Shapefile 驱动文档](https://gdal.org/en/stable/drivers/vector/shapefile.html)。
