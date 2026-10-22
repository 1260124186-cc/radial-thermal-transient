# 领域说明与验算

## 物理模型

题目是一条带伴热的输水管径向瞬态导热。管壁连同两层保温材料沿半径拆成 N 个环形控制体，网格边界 radii_m 从内到外严格递增。只算径向温度，忽略轴向、周向变化以及保温层内部的对流和辐射。

## 正确值复算方式

- 热容：第 i 格体积 `pi*(r_{i+1}^2 - r_i^2)*L`，热容 `C_i = rho_i*cp_i*V_i`。
- 格心：`r_mid_i = (r_i + r_{i+1})/2`，层界面落在网格边界上。
- 界面导热：相邻两格在界面串联两个圆柱半格热阻，`R = ln(r_face/r_mid_i)/(2*pi*L*k_i) + ln(r_mid_{i+1}/r_face)/(2*pi*L*k_{i+1})`，导纳 `G = 1/R`。不能把环形格当平板用面积差近似。
- 材料非线性：`k_i = k0_i*(1 + alpha_i*(T_i - 20))`，每个时步用旧格温。
- 内壁：热流密度 `q_in` 转成功率 `Q_in = q_in*2*pi*r_inner*L`。
- 外壁对流：最外层半格热阻与膜阻串联，`G_conv = 1/(ln(r_out/r_mid_last)/(2*pi*L*k_last) + 1/(h*2*pi*r_out*L))`。
- 外壁辐射：`q_rad = epsilon*sigma*A*(T_surface_K^4 - T_ambient_K^4)`，`sigma=5.670374419e-8`，开尔文换算加 273.15；A 是外表面圆柱面积。
- 体积热源：`q_gen*V_i`，可为正、零、负。
- 时间推进：显式欧拉同步更新，`T_i += dt*Q_i/C_i`。稳定上限 `dt <= C_i/(G_left+G_right)`，最外层再加对流导纳和线性化辐射导纳 `4*epsilon*sigma*A*T_surface_K^3`；检查用旧温度的 k。边界热流密度和体积热源不计入。

## 独立验算

tests/test_outputs.py 的 `reference()` 用一套独立控制体代码重新算期望值，不调用待修模块；断言逐条比对温度、累计内壁热量、累计外散热、累计热源、储能和残差，容差 rel=1e-9。残差定义 `stored - inner + outer - generated`，守恒应趋近 0。

## 五个难点

- C1 几何：环形体积和对数半格热阻（geometry.py）。
- C2 材料与工况：随温度更新导热率，左闭右开时段选边界（boundary.py）。
- C3 稳定性与拒收：显式稳定上限，写文件前拒绝非法输入（solver.py）。
- C4 体积热源：热源并入能量平衡并累计，残差含 generated 项（solver.py）。
- C5 外壁辐射：开尔文 T^4 辐射热流，稳定导纳加 4*epsilon*sigma*A*T_k^3（boundary.py）。

example.json 是演示工况，不是现场采集值。
