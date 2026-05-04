# -*- coding: utf-8 -*-
"""
崩岗风险等级自动评估 — ArcGIS Pro (ArcPy) 完整实现
================================================================
版本: v2
适用范围: ArcGIS Pro 3.x + Spatial Analyst 扩展模块
AI 技术顾问: Claude + Gemini 联合审核

使用方法:
  1. 关闭 ArcGIS Pro
  2. 修改下方「用户配置区」参数
  3. 用 ArcGIS Pro 专属 Python 解释器运行:
     "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" run_risk.py
"""

# ============================================================================
# 用户配置区 (你只需修改这里)
# ============================================================================
WORKSPACE = r"D:\Benggang_Risk\RiskData.gdb"

# 主图斑 (崩岗多边形, 需要有 AREA, LX 字段)
INPUT_FC = "Benggang_Main"

# 唯一标识字段 (脚本自动创建, C_name 填入 BG_1, BG_2...)
UNIQUE_FIELD = "C_name"

# 风险源图层映射 {中文标签: GDB 图层名}
RISK_SOURCES = {
    "水系": "Water",
    "道路": "Roads",
    "建设": "Construction",
    "园地": "Garden",
    "耕地": "Farmland",
}

# 栅格数据
DEM_RASTER = "DEM_Raster"
EROSION_RASTER = "Erosion_Raster"

# 植被/土地利用 (面, 需有 TDLYMC 字段)
LANDUSE_FC = "Vegetation"
LANDUSE_VEG_FIELD = "TDLYMC"

# 主图斑字段名
AREA_FIELD = "AREA"
STATE_FIELD = "LX"

# 容错
KEEP_TEMP = False           # True: 保留中间表/栅格; False: 用完即删
NEAR_SEARCH_RADIUS = None   # None = 不限制搜索半径, 或指定数值(米)

# ============================================================================
# 以下为核心代码, 一般无需修改
# ============================================================================

import arcpy
import os
import sys
import logging
from collections import OrderedDict

# 距离字段名映射 {中文标签: "D__<中文>_"}
DIST_FIELD_MAP = OrderedDict([
    ("水系", "D__水系_"),
    ("道路", "D__道路_"),
    ("建设", "D__建设_"),
    ("园地", "D__园地_"),
    ("耕地", "D__耕地_"),
])

# 打分字段名
SCORE_FIELDS = OrderedDict([
    ("坡度",  "S_坡度"),
    ("侵蚀",  "S_侵蚀"),
    ("水系",  "S_水系"),
    ("建设",  "S_建设"),
    ("道路",  "S_道路"),
    ("园地",  "S_园地"),
    ("耕地",  "S_耕地"),
    ("植被",  "S_植被"),
    ("规模",  "S_规模"),
    ("发育",  "S_发育"),
])

# 加权权重
WEIGHTS = {
    "S_坡度": 0.16, "S_规模": 0.20, "S_发育": 0.17, "S_植被": 0.17, "S_侵蚀": 0.20,
    "S_水系": 0.22, "S_建设": 0.24, "S_道路": 0.22, "S_耕地": 0.22, "S_园地": 0.20,
}

TOTAL_FIELD = "Risk_Total"
RISK_LEVEL_FIELD = "fxdj"

# NULL 默认值
NULL_DEFAULTS = {
    "D__水系_": 5000, "D__道路_": 5000, "D__建设_": 5000,
    "D__园地_": 5000, "D__耕地_": 5000,
    "坡度": 0, "QSZS": 0, "TDLYMC": "无植被",
    "AREA": 0, "LX": "活跃型",
}

# 临时数据清单 (in_memory 路径)
TEMP_SLOPE_RASTER = r"in_memory\slope_temp"
TEMP_SLOPE_ZONAL = r"in_memory\slope_zonal"
TEMP_EROSION_ZONAL = r"in_memory\erosion_zonal"
TEMP_VEG_JOIN = r"in_memory\veg_spatial_join"


def _setup_logging():
    """配置日志: 同时输出到控制台和文件."""
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_risk.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


logger = _setup_logging()


class BenggangRiskEvaluator:
    """崩岗风险等级自动评估器.

    6 步流程:
      step0: 生成唯一标识 C_name
      step1: 距离分析 (5 次 Near)
      step2: 坡度 + 侵蚀模数提取
      step3: 植被类型关联
      step4: NULL 清扫
      step5: 打分 + 加权 + 等级判定
    """

    def __init__(self):
        self.workspace = WORKSPACE
        self.input_fc_name = INPUT_FC
        self.input_fc = os.path.join(self.workspace, self.input_fc_name)
        self.cname_field = UNIQUE_FIELD
        self.area_field = AREA_FIELD
        self.state_field = STATE_FIELD
        self.dem_raster = os.path.join(self.workspace, DEM_RASTER)
        self.erosion_raster = os.path.join(self.workspace, EROSION_RASTER)
        self.landuse_fc = os.path.join(self.workspace, LANDUSE_FC)
        self.veg_field = LANDUSE_VEG_FIELD
        self.temp_items = []

        self._check_license()
        self._validate_workspace()
        self._set_environment()

        logger.info("初始化完成 — 工作空间: %s", self.workspace)
        logger.info("主图斑: %s (%d 条记录)", self.input_fc_name, self._count_rows(self.input_fc))

    # ---- 辅助方法 -----------------------------------------------------------

    def _check_license(self):
        """检查 Spatial Analyst 许可."""
        if arcpy.CheckExtension("Spatial") == "Available":
            arcpy.CheckOutExtension("Spatial")
            logger.info("Spatial Analyst 扩展模块已激活")
        else:
            raise RuntimeError("Spatial Analyst 扩展模块不可用! 请在 ArcGIS Pro 中激活后重试。")

    def _validate_workspace(self):
        """强制 GDB 环境 + GDB 存在性校验."""
        if not os.path.isdir(self.workspace):
            raise RuntimeError(f"工作空间不存在: {self.workspace}")
        if not self.workspace.lower().endswith(".gdb"):
            raise RuntimeError(
                "工作空间必须是 File Geodatabase (.gdb)!\n"
                f"当前设置: {self.workspace}\n"
                "原因: shapefile 字段名限制 10 字节, D__建设_ 和 Risk_Total 会超限。"
            )
        arcpy.env.workspace = self.workspace
        if not arcpy.Exists(self.input_fc_name):
            raise RuntimeError(f"主图斑 {self.input_fc_name} 不存在于 {self.workspace}")

    def _set_environment(self):
        """设置栅格处理环境 (防崩溃机制 2)."""
        arcpy.env.overwriteOutput = True
        arcpy.env.outputCoordinateSystem = arcpy.Describe(self.input_fc).spatialReference
        if arcpy.Exists(self.dem_raster):
            arcpy.env.snapRaster = self.dem_raster
        arcpy.env.cellSize = "MINOF"

    @staticmethod
    def _count_rows(fc):
        return int(arcpy.management.GetCount(fc).getOutput(0))

    @staticmethod
    def _ensure_field(fc, field_name, field_type, **kwargs):
        """安全添加字段, 已存在则跳过."""
        fields = [f.name for f in arcpy.ListFields(fc)]
        if field_name in fields:
            logger.info("  字段 %s 已存在, 跳过 AddField", field_name)
            return
        arcpy.management.AddField(fc, field_name, field_type, **kwargs)
        logger.info("  + 新增字段: %s (%s)", field_name, field_type)

    def _add_temp(self, path):
        """登记临时数据, 用于 _cleanup()."""
        self.temp_items.append(path)

    def _cleanup(self):
        """删除所有临时数据."""
        for path in self.temp_items:
            try:
                if arcpy.Exists(path):
                    arcpy.management.Delete(path)
                    logger.info("  清理临时数据: %s", path)
            except Exception as e:
                logger.warning("  清理失败 (%s): %s", path, e)
        self.temp_items.clear()

    # ---- Step 0: 生成唯一标识 ------------------------------------------------

    def step0_generate_cname(self):
        """创建 C_name 字段, 填入 BG_1, BG_2, BG_3..."""
        logger.info("=" * 60)
        logger.info("Step 0: 生成唯一标识 C_name")
        self._ensure_field(self.input_fc, self.cname_field, "TEXT", field_length=50)

        counter = 0
        with arcpy.da.UpdateCursor(self.input_fc, [self.cname_field]) as cursor:
            for row in cursor:
                counter += 1
                row[0] = f"BG_{counter}"
                cursor.updateRow(row)
        logger.info("  完成: 共生成 %d 个标识 (%s ~ %s)", counter, "BG_1", f"BG_{counter}")

    # ---- Step 1: 距离分析 ----------------------------------------------------

    def step1_distance_risk(self):
        """5 次 Near Analysis, 计算主图斑距各风险源的距离."""
        logger.info("=" * 60)
        logger.info("Step 1: 距离分析 (5 次 Near Analysis)")

        for label, source_name in RISK_SOURCES.items():
            source_fc = os.path.join(self.workspace, source_name)
            dist_field = DIST_FIELD_MAP[label]

            if not arcpy.Exists(source_fc):
                logger.warning("  [%s] 风险源 %s 缺失 — 跳过, 距离字段保持 NULL (后续 step4 赋 5000)", label, source_name)
                self._ensure_field(self.input_fc, dist_field, "DOUBLE")
                continue

            self._ensure_field(self.input_fc, dist_field, "DOUBLE")
            logger.info("  计算距离: %s (%s) → %s", label, source_name, dist_field)
            arcpy.analysis.Near(
                in_features=self.input_fc,
                near_features=source_fc,
                search_radius=NEAR_SEARCH_RADIUS,
            )
            # 重命名默认的 NEAR_DIST 为目标字段名
            near_fid_field = "NEAR_FID"
            fields_to_clean = []
            if "NEAR_DIST" in [f.name for f in arcpy.ListFields(self.input_fc)]:
                arcpy.management.CalculateField(
                    self.input_fc, dist_field, "!NEAR_DIST!", "PYTHON3"
                )
                fields_to_clean.extend(["NEAR_DIST", "NEAR_FID", "NEAR_FC", "NEAR_X", "NEAR_Y", "NEAR_ANGLE"])
            # 清理 Near 默认输出字段
            for fname in fields_to_clean:
                try:
                    if fname in [f.name for f in arcpy.ListFields(self.input_fc)]:
                        arcpy.management.DeleteField(self.input_fc, fname)
                except Exception:
                    pass

        logger.info("  距离分析完成: %d 个字段已填充", len(RISK_SOURCES))

    # ---- Step 2: 坡度 + 侵蚀模数 --------------------------------------------

    def step2_slope_erosion(self):
        """DEM → Slope 栅格 → 分区统计均值 → 回写到主图斑."""
        logger.info("=" * 60)
        logger.info("Step 2: 坡度 + 侵蚀模数提取")

        # --- 2a: 计算坡度栅格 ---
        logger.info("  2a: 生成坡度栅格 (in_memory)")
        if not arcpy.Exists(self.dem_raster):
            logger.warning("  DEM 栅格 %s 缺失 — 坡度/侵蚀字段设为 NULL", DEM_RASTER)
            self._ensure_field(self.input_fc, "坡度", "DOUBLE")
            self._ensure_field(self.input_fc, "QSZS", "DOUBLE")
            return

        arcpy.ddd.Slope(self.dem_raster, TEMP_SLOPE_RASTER, "DEGREE")
        self._add_temp(TEMP_SLOPE_RASTER)
        logger.info("  坡度栅格已生成: %s", TEMP_SLOPE_RASTER)

        # --- 2b: 分区统计 (坡度均值) ---
        logger.info("  2b: 分区统计 — 坡度均值")
        slope_table = arcpy.sa.ZonalStatisticsAsTable(
            self.input_fc, self.cname_field, TEMP_SLOPE_RASTER, TEMP_SLOPE_ZONAL, "DATA"
        )
        self._add_temp(TEMP_SLOPE_ZONAL)
        # ROWID 字段由 GP 工具自动生成; if VALUE_1 = statistics type code
        mean_fields = [f.name for f in arcpy.ListFields(TEMP_SLOPE_ZONAL)]
        mean_field = "MEAN" if "MEAN" in mean_fields else mean_fields[-1]

        self._ensure_field(self.input_fc, "坡度", "DOUBLE")
        arcpy.management.JoinField(
            self.input_fc, self.cname_field, TEMP_SLOPE_ZONAL, self.cname_field, [mean_field]
        )
        fields = [f.name for f in arcpy.ListFields(self.input_fc)]
        rename_map = {}  # JoinField may append _1 suffix
        arcpy.management.CalculateField(self.input_fc, "坡度", f"!{mean_field}!", "PYTHON3")
        # 清理 Join 带入的冗余字段
        for f in arcpy.ListFields(self.input_fc):
            if f.name.startswith(mean_field):
                try:
                    arcpy.management.DeleteField(self.input_fc, f.name)
                except Exception:
                    pass

        # --- 2c: 分区统计 (侵蚀模数均值) ---
        if arcpy.Exists(self.erosion_raster):
            logger.info("  2c: 分区统计 — 侵蚀模数")
            arcpy.sa.ZonalStatisticsAsTable(
                self.input_fc, self.cname_field, self.erosion_raster, TEMP_EROSION_ZONAL, "DATA"
            )
            self._add_temp(TEMP_EROSION_ZONAL)
            self._ensure_field(self.input_fc, "QSZS", "DOUBLE")
            mean_fields2 = [f.name for f in arcpy.ListFields(TEMP_EROSION_ZONAL)]
            mean_field2 = "MEAN" if "MEAN" in mean_fields2 else mean_fields2[-1]
            arcpy.management.JoinField(
                self.input_fc, self.cname_field, TEMP_EROSION_ZONAL, self.cname_field, [mean_field2]
            )
            arcpy.management.CalculateField(self.input_fc, "QSZS", f"!{mean_field2}!", "PYTHON3")
            for f in arcpy.ListFields(self.input_fc):
                if f.name.startswith(mean_field2):
                    try:
                        arcpy.management.DeleteField(self.input_fc, f.name)
                    except Exception:
                        pass
        else:
            logger.warning("  侵蚀栅格 %s 缺失 — QSZS 字段设为 NULL", EROSION_RASTER)
            self._ensure_field(self.input_fc, "QSZS", "DOUBLE")

        logger.info("  坡度 + 侵蚀模数提取完成")

    # ---- Step 3: 植被类型关联 ------------------------------------------------

    def step3_vegetation_type(self):
        """Spatial Join 获取植被类型, FieldMappings 仅保留 TDLYMC."""
        logger.info("=" * 60)
        logger.info("Step 3: 植被类型关联 (Spatial Join)")

        if not arcpy.Exists(self.landuse_fc):
            logger.warning("  植被图层 %s 缺失 — TDLYMC 字段保持 NULL", LANDUSE_FC)
            self._ensure_field(self.input_fc, self.veg_field, "TEXT", field_length=50)
            return

        # 构建 FieldMappings: 仅保留主图斑的 C_name + 植被图层的 TDLYMC
        field_mappings = arcpy.FieldMappings()
        # 添加主图斑的 C_name
        fm_cname = arcpy.FieldMap()
        fm_cname.addInputField(self.input_fc, self.cname_field)
        field_mappings.addFieldMap(fm_cname)
        # 添加植被图层的 TDLYMC
        fm_veg = arcpy.FieldMap()
        fm_veg.addInputField(self.landuse_fc, self.veg_field)
        output_field = fm_veg.outputField
        output_field.name = self.veg_field
        fm_veg.outputField = output_field
        field_mappings.addFieldMap(fm_veg)

        logger.info("  执行 Spatial Join (仅保留 %s, %s)...", self.cname_field, self.veg_field)
        arcpy.analysis.SpatialJoin(
            target_features=self.input_fc,
            join_features=self.landuse_fc,
            out_feature_class=TEMP_VEG_JOIN,
            join_operation="JOIN_ONE_TO_ONE",
            join_type="KEEP_ALL",
            field_mapping=field_mappings,
            match_option="INTERSECT",
        )
        self._add_temp(TEMP_VEG_JOIN)

        # 将 TDLYMC 回写到主图斑
        self._ensure_field(self.input_fc, self.veg_field, "TEXT", field_length=50)
        arcpy.management.JoinField(
            self.input_fc, self.cname_field, TEMP_VEG_JOIN, self.cname_field, [self.veg_field]
        )
        logger.info("  植被类型关联完成")

    # ---- Step 4: NULL 清扫 ---------------------------------------------------

    def step4_null_sanitize(self):
        """遍历所有源字段, NULL → 安全默认值."""
        logger.info("=" * 60)
        logger.info("Step 4: NULL 清扫")

        # 动态构建 NULL 映射: 距离字段从 DIST_FIELD_MAP 取
        null_map = {}
        for label, dist_field in DIST_FIELD_MAP.items():
            null_map[dist_field] = NULL_DEFAULTS[dist_field]
        null_map["坡度"] = NULL_DEFAULTS["坡度"]
        null_map["QSZS"] = NULL_DEFAULTS["QSZS"]
        null_map[self.veg_field] = NULL_DEFAULTS["TDLYMC"]
        null_map[self.area_field] = NULL_DEFAULTS["AREA"]
        null_map[self.state_field] = NULL_DEFAULTS["LX"]

        # 收集实际存在的字段
        existing_fields = {f.name for f in arcpy.ListFields(self.input_fc)}
        fields_to_fix = [fn for fn in null_map if fn in existing_fields]
        if not fields_to_fix:
            logger.info("  无需清扫 (无目标字段)")
            return

        logger.info("  将检查 %d 个字段的 NULL 值...", len(fields_to_fix))
        fixed_count = 0
        for field_name in fields_to_fix:
            default_val = null_map[field_name]
            with arcpy.da.UpdateCursor(self.input_fc, [field_name]) as cursor:
                for row in cursor:
                    if row[0] is None:
                        row[0] = default_val
                        cursor.updateRow(row)
                        fixed_count += 1
            logger.info("  %s: NULL → %s", field_name, repr(default_val))

        logger.info("  NULL 清扫完成, 共修复 %d 个值", fixed_count)

    # ---- Step 5: 加权打分 ----------------------------------------------------

    def step5_weighted_scoring(self):
        """10 项指标打分 + 加权总分 + fxdj 风险等级."""
        logger.info("=" * 60)
        logger.info("Step 5: 加权打分 + 风险等级判定")

        # 5a: 创建打分字段
        logger.info("  5a: 创建 10 个打分字段...")
        for label, sf in SCORE_FIELDS.items():
            self._ensure_field(self.input_fc, sf, "SHORT")
        self._ensure_field(self.input_fc, TOTAL_FIELD, "DOUBLE")
        self._ensure_field(self.input_fc, RISK_LEVEL_FIELD, "TEXT", field_length=10)

        # 5b: 逐行打分
        logger.info("  5b: 逐行计算得分与加权总分...")

        dist_fields = [DIST_FIELD_MAP[label] for label in RISK_SOURCES]
        # 每个风险源对应距离字段列表 (顺序与 RISK_SOURCES 一致)
        score_labels = ["S_坡度", "S_侵蚀", "S_水系", "S_建设", "S_道路", "S_园地", "S_耕地", "S_植被", "S_规模", "S_发育"]

        input_fields = [
            "坡度", "QSZS",
            DIST_FIELD_MAP.get("水系", "D__水系_"),
            DIST_FIELD_MAP.get("建设", "D__建设_"),
            DIST_FIELD_MAP.get("道路", "D__道路_"),
            DIST_FIELD_MAP.get("园地", "D__园地_"),
            DIST_FIELD_MAP.get("耕地", "D__耕地_"),
            self.veg_field, self.area_field, self.state_field,
        ]
        all_fields = input_fields + score_labels + [TOTAL_FIELD, RISK_LEVEL_FIELD]

        with arcpy.da.UpdateCursor(self.input_fc, all_fields) as cursor:
            for row in cursor:
                slope_val = row[0] if row[0] is not None else 0
                erosion_val = row[1] if row[1] is not None else 0
                d_water = row[2] if row[2] is not None else 5000
                d_build = row[3] if row[3] is not None else 5000
                d_road = row[4] if row[4] is not None else 5000
                d_garden = row[5] if row[5] is not None else 5000
                d_farm = row[6] if row[6] is not None else 5000
                veg_val = str(row[7]) if row[7] is not None else "无植被"
                area_val = row[8] if row[8] is not None else 0
                state_val = str(row[9]) if row[9] is not None else "活跃型"

                # ---- 坡度得分 ----
                if slope_val <= 5:
                    s_slope = 1
                elif slope_val <= 10:
                    s_slope = 2
                elif slope_val <= 15:
                    s_slope = 3
                elif slope_val <= 20:
                    s_slope = 4
                else:
                    s_slope = 5

                # ---- 侵蚀得分 ----
                if erosion_val < 2500:
                    s_erosion = 1
                elif erosion_val < 5000:
                    s_erosion = 2
                elif erosion_val < 8000:
                    s_erosion = 3
                elif erosion_val < 15000:
                    s_erosion = 4
                else:
                    s_erosion = 5

                # ---- 距离得分函数 (5 个风险源通用) ----
                def score_distance(dist):
                    if dist >= 500:
                        return 1
                    elif dist >= 300:
                        return 2
                    elif dist >= 150:
                        return 3
                    elif dist >= 10:
                        return 4
                    else:
                        return 5

                s_water = score_distance(d_water)
                s_build = score_distance(d_build)
                s_road = score_distance(d_road)
                s_garden = score_distance(d_garden)
                s_farm = score_distance(d_farm)

                # ---- 植被得分 ----
                if "乔木" in veg_val:
                    s_veg = 1
                elif "灌木" in veg_val:
                    s_veg = 2
                elif "疏林" in veg_val:
                    s_veg = 3
                elif "草" in veg_val:
                    s_veg = 4
                else:
                    s_veg = 5

                # ---- 规模得分 ----
                if area_val < 1000:
                    s_area = 1
                elif area_val < 3000:
                    s_area = 2
                elif area_val < 5000:
                    s_area = 3
                elif area_val < 10000:
                    s_area = 4
                else:
                    s_area = 5

                # ---- 发育状态得分 (机制 4: 极简状态打分) ----
                if "稳定" in state_val:
                    s_state = 2
                else:
                    s_state = 5

                # 写入得分字段
                scores = [s_slope, s_erosion, s_water, s_build, s_road,
                          s_garden, s_farm, s_veg, s_area, s_state]
                for j, score in enumerate(scores):
                    row[10 + j] = score

                # ---- 加权总分 ----
                risk_total = (
                    s_slope * WEIGHTS["S_坡度"] +
                    s_erosion * WEIGHTS["S_侵蚀"] +
                    s_water * WEIGHTS["S_水系"] +
                    s_build * WEIGHTS["S_建设"] +
                    s_road * WEIGHTS["S_道路"] +
                    s_garden * WEIGHTS["S_园地"] +
                    s_farm * WEIGHTS["S_耕地"] +
                    s_veg * WEIGHTS["S_植被"] +
                    s_area * WEIGHTS["S_规模"] +
                    s_state * WEIGHTS["S_发育"]
                )
                row[20] = round(risk_total, 4)

                # ---- 风险等级 ----
                if risk_total >= 7.0:
                    row[21] = "高风险"
                elif risk_total >= 4.0:
                    row[21] = "中风险"
                else:
                    row[21] = "低风险"

                cursor.updateRow(row)

        logger.info("  打分完成: 共处理 %d 条记录", self._count_rows(self.input_fc))

        # 统计
        stats = {"高风险": 0, "中风险": 0, "低风险": 0}
        with arcpy.da.SearchCursor(self.input_fc, [RISK_LEVEL_FIELD]) as cursor:
            for row in cursor:
                if row[0] in stats:
                    stats[row[0]] += 1
        logger.info("  风险等级分布: 高风险=%d, 中风险=%d, 低风险=%d",
                    stats["高风险"], stats["中风险"], stats["低风险"])

    # ---- 编排器 --------------------------------------------------------------

    def run(self):
        """依次执行 step0~5, 完成后清理."""
        start_time = __import__("time").time()
        logger.info("=" * 60)
        logger.info("崩岗风险等级自动评估 — 开始执行")
        logger.info("=" * 60)

        try:
            self.step0_generate_cname()
            self.step1_distance_risk()
            self.step2_slope_erosion()
            self.step3_vegetation_type()
            self.step4_null_sanitize()
            self.step5_weighted_scoring()

            if not KEEP_TEMP:
                self._cleanup()

            elapsed = __import__("time").time() - start_time
            logger.info("=" * 60)
            logger.info("执行完成! 耗时 %.1f 秒", elapsed)
            logger.info("输出图层: %s", self.input_fc)
            logger.info("请在 ArcGIS Pro 中打开属性表验证以下字段:")
            logger.info("  C_name, D__水系_~D__耕地_, 坡度, QSZS, %s", self.veg_field)
            logger.info("  S_坡度~S_发育, Risk_Total, fxdj")
            logger.info("=" * 60)

        except Exception:
            logger.exception("执行失败!")
            if not KEEP_TEMP:
                self._cleanup()
            raise


# ============================================================================
# 入口
# ============================================================================
if __name__ == "__main__":
    evaluator = BenggangRiskEvaluator()
    evaluator.run()
