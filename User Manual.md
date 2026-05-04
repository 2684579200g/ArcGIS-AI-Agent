# 崩岗风险等级自动评估

基于 ArcGIS Pro (ArcPy) 的崩岗灾害风险等级自动评估工具。对崩岗图斑进行多因子加权打分，输出高/中/低三级风险等级。

## 环境要求

| 项目 | 要求 |
|------|------|
| ArcGIS Pro | 3.x |
| 扩展模块 | **Spatial Analyst** (必须激活) |
| Python | ArcGIS Pro 自带解释器 `arcgispro-py3` |
| 数据格式 | **File Geodatabase** (.gdb) — 不支持 shapefile |

### Python 解释器路径

```
C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe
```

## 快速开始

### 1. 准备数据

在 `D:\Benggang_Risk\RiskData.gdb` 中放入以下数据，**图层名必须一字不差**：

| 图层角色 | GDB 中名称 | 类型 | 必需字段 |
|----------|-----------|------|---------|
| 主图斑 | `Benggang_Main` | 多边形 | `AREA` (面积), `LX` (发育状态) |
| 水系 | `Water` | 线/面 | — |
| 道路 | `Roads` | 线/面 | — |
| 建设用地 | `Construction` | 面 | — |
| 园地 | `Garden` | 面 | — |
| 耕地 | `Farmland` | 面 | — |
| DEM 栅格 | `DEM_Raster` | 栅格 | — |
| 侵蚀模数栅格 | `Erosion_Raster` | 栅格 | — |
| 植被/土地利用 | `Vegetation` | 面 | `TDLYMC` (植被类型) |

> **注意**：`LX` 字段取值需为 `"稳定"` 或 `"活跃"` (或其他非稳定值)。主图斑无需事先建唯一标识字段，脚本自动生成 `C_name`。

### 2. 修改配置

编辑 `run_risk.py` 顶部的**用户配置区**：

```python
WORKSPACE = r"D:\Benggang_Risk\RiskData.gdb"  # GDB 路径
INPUT_FC = "Benggang_Main"                      # 主图斑名称
# ... 其余按需修改
```

### 3. 执行

```bash
# 关闭 ArcGIS Pro (防止 GDB 锁定)
"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" run_risk.py
```

### 4. 验证

在 ArcGIS Pro 中打开 `Benggang_Main` 属性表，逐项核对：

- [ ] `C_name` — BG_1, BG_2, BG_3... 无重复无空
- [ ] `D__水系_` ~ `D__耕地_` — 5 个距离字段，数值合理
- [ ] `坡度` — 0~90 之间
- [ ] `QSZS` — 侵蚀模数，≥0
- [ ] `TDLYMC` — 植被类型文本
- [ ] `S_坡度` ~ `S_发育` — 10 个得分字段，值限 1/2/3/4/5
- [ ] `Risk_Total` — DOUBLE，约 2.0~10.0
- [ ] `fxdj` — 高/中/低风险

## 评估流程

| 步骤 | 方法 | 输出 |
|------|------|------|
| Step 0 | 生成唯一标识 | `C_name` = BG_1, BG_2... |
| Step 1 | 5 次 Near Analysis | `D__水系_`, `D__道路_`, `D__建设_`, `D__园地_`, `D__耕地_` |
| Step 2 | DEM→Slope + ZonalStatistics | `坡度`, `QSZS` (侵蚀模数) |
| Step 3 | Spatial Join 获取植被类型 | `TDLYMC` |
| Step 4 | NULL 清扫 → 安全默认值 | 所有源字段无 NULL |
| Step 5 | 10 项打分 + 加权 + 定级 | `S_*`, `Risk_Total`, `fxdj` |

## 打分规则

### 指标评分表

| 指标 | 得分字段 | 1 分 | 2 分 | 3 分 | 4 分 | 5 分 |
|------|---------|------|------|------|------|------|
| 坡度 | S_坡度 | ≤5 | ≤10 | ≤15 | ≤20 | >20 |
| 侵蚀模数 | S_侵蚀 | <2500 | <5000 | <8000 | <15000 | ≥15000 |
| 距离水系 | S_水系 | ≥500m | ≥300m | ≥150m | ≥10m | <10m |
| 距离建设 | S_建设 | ≥500m | ≥300m | ≥150m | ≥10m | <10m |
| 距离道路 | S_道路 | ≥500m | ≥300m | ≥150m | ≥10m | <10m |
| 距离园地 | S_园地 | ≥500m | ≥300m | ≥150m | ≥10m | <10m |
| 距离耕地 | S_耕地 | ≥500m | ≥300m | ≥150m | ≥10m | <10m |
| 植被 | S_植被 | 含乔木 | 含灌木 | 含疏林 | 含草 | 其他 |
| 规模 AREA | S_规模 | <1000m² | <3000m² | <5000m² | <10000m² | ≥10000m² |
| 发育状态 LX | S_发育 | — | 含"稳定" | — | — | 含"活跃" |

### 加权公式

```
Risk_Total = S_坡度×0.16 + S_规模×0.20 + S_发育×0.17 + S_植被×0.17 + S_侵蚀×0.20
           + S_水系×0.22 + S_建设×0.24 + S_道路×0.22 + S_耕地×0.22 + S_园地×0.20
```

### 风险等级

| 等级 | 条件 | 建议符号色 |
|------|------|----------|
| 🔴 高风险 | Risk_Total ≥ 7.0 | 红色 |
| 🟡 中风险 | Risk_Total ≥ 4.0 | 黄色 |
| 🟢 低风险 | Risk_Total < 4.0 | 绿色 |

## 容错说明

| 场景 | 处理方式 |
|------|---------|
| 某风险源图层缺失 | 警告 + 跳过，距离字段 NULL → step4 赋 5000 |
| 图斑无匹配植被 | TDLYMC = NULL → step4 赋 "无植被" → step5 打 5 分 |
| 图斑超出栅格范围 | ZonalStatistics 返回 NULL → step4 赋 0 |
| 字段已存在 (重跑) | try/except 跳过 AddField |
| GDB 被 ArcGIS Pro 锁定 | 提示关闭 ArcGIS Pro 后重试 |
| Spatial Analyst 不可用 | 立即终止，提示激活扩展模块 |

## 性能设计

- 中间栅格/表均写入 `in_memory`，避免 GDB schema lock，运算快 10 倍以上
- Spatial Join 精确字段映射（仅保留 C_name + TDLYMC），主表保持清爽
- `C_name` 显式指定 TEXT(50)，防止编号截断
- 微小图斑保护：`snapRaster` + `cellSize = "MINOF"` 确保栅格捕获

## 项目结构

```
D:\Benggang_Risk\
├── RiskData.gdb\          # 数据 GDB
├── run_risk.py            # 主脚本
├── run_risk.log           # 运行日志 (自动生成)
└── README.md              # 本文档
```

## 许可证

MIT License
