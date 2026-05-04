# -*- coding: utf-8 -*-
"""
崩岗风险等级自动评估工具 - ArcGIS Pro (ArcPy)
版本：v2
功能：基于多指标（坡度、规模、发育状态、植被、侵蚀模数及危害距离）自动计算崩岗风险等级。
"""

import arcpy
import os

# ====== 用户配置区 ======
WORKSPACE      = r"D:\Benggang_Risk\RiskData.gdb"
INPUT_FC       = "Benggang_Main"
UNIQUE_FIELD   = "C_name"
RISK_SOURCES = {
    "水系": "Water",
    "道路": "Roads",
    "建设": "Construction",
    "园地": "Garden",
    "耕地": "Farmland",
}
DEM_RASTER      = "DEM_Raster"
EROSION_RASTER  = "Erosion_Raster"
LANDUSE_FC      = "Vegetation"
LANDUSE_VEG_FIELD = "TDLYMC"
AREA_FIELD   = "AREA"
STATE_FIELD  = "LX"
KEEP_TEMP          = False
NEAR_SEARCH_RADIUS = None
# ========================

class BenggangRiskEvaluator:
    def __init__(self):
        arcpy.env.workspace = WORKSPACE
        arcpy.env.overwriteOutput = True
        
        if not WORKSPACE.lower().endswith(".gdb"):
            raise RuntimeError("工作空间必须是 File Geodatabase (.gdb)！")
            
        print("初始化成功，工作空间已锁定。")

    def step0_generate_cname(self):
        """生成唯一标识 C_name"""
        print("执行 Step 0: 生成唯一标识...")
        if len(arcpy.ListFields(INPUT_FC, UNIQUE_FIELD)) == 0:
            arcpy.management.AddField(INPUT_FC, UNIQUE_FIELD, "TEXT", field_length=50)
        # 此处省略具体遍历赋值逻辑...

    def step1_distance_risk(self):
        """危害风险指标计算：5次近邻分析"""
        print("执行 Step 1: 计算危害源距离...")
        # 实际代码会调用 arcpy.analysis.Near 等

    def step2_slope_erosion(self):
        """侵蚀风险指标：坡度与侵蚀模数"""
        print("执行 Step 2: 提取坡度与侵蚀模数...")
        arcpy.env.snapRaster = DEM_RASTER
        # 此处省略 ZonalStatistics 逻辑...

    def step3_vegetation_type(self):
        """提取植被类型"""
        print("执行 Step 3: 空间连接植被类型...")
        # 实际代码会调用 arcpy.analysis.SpatialJoin

    def step4_null_sanitize(self):
        """NULL 清扫，确保数据安全"""
        print("执行 Step 4: 清洗 NULL 数据...")
        # 替换 NULL 值为安全默认值

    def step5_weighted_scoring(self):
        """加权打分与风险定级"""
        print("执行 Step 5: 加权总分与等级评定...")
        # Risk_Total = S_坡度*0.16 + S_规模*0.20 + ... 
        # fxdj 分级：>=7 高风险, >=4 中风险, <4 低风险

    def run(self):
        """编排器"""
        try:
            self.step0_generate_cname()
            self.step1_distance_risk()
            self.step2_slope_erosion()
            self.step3_vegetation_type()
            self.step4_null_sanitize()
            self.step5_weighted_scoring()
            print("评估任务全部完成！")
        except Exception as e:
            print(f"执行出错: {str(e)}")

if __name__ == "__main__":
    evaluator = BenggangRiskEvaluator()
    evaluator.run()