# 支持集合与矩范围实现交接说明

本说明面向后续维护者，解释 V2 两个新入口如何把「完整支持集合生产」与
「同一集合上的逐项矩范围消费」联动起来，以及集合、身份与数值边界之间的不变量。
公开业务口径以 SUPPORT.md 为准；本文件只描述实现组织与核账方式。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `batch_analysis/support.py` | `drop` 校验、全局极值枚举、单调分段上的完整支持集合求解与发布前数值闸门 |
| `batch_analysis/rational_moments.py` | 用精确 Fraction 系数把每个均值/协方差条目构造成 τ 的有理函数，并枚举其 Sturm 认证的内部驻点 |
| `predictions/ranges.py` | 在同一支持集合上收集全部候选 τ，逐条目取最小/最大值，并与未改动的 V1 条件化路径交叉核验 |
| `results/support_codec.py` / `results/support_prediction_codec.py` | 两类新成果的 JSON 持久化、自校验解码与只读拷贝 |
| `results/schema.py`、`results/database.py` | 四张新表、原子发布、`fail_next_publication("support"/"support_prediction")` 一次性夹具 |
| `application/analysis.py` | `support_batch`、`predict_support` 业务编排与 CLI 子命令 |
| `application/results.py` | 四类成果统一只读入口，解码不触发任何计算 |
| `support_audit.py` | 独立业务核账（独立 REML、独立 Fraction 高斯矩、回滚/更正/重开） |

## 支持集合为什么是完整的（不是网格）

1. 得分分子是 `stationary.py` 已有的精确 Fraction 多项式，且 A(τ) 在 τ≥0
   严格为正，所以似然在正半轴的全部驻点就是该多项式经 Sturm 计数隔离的全部根，
   没有其它临界点。
2. 以 0 与全部驻点为分界，似然在每段上严格单调。每段上的超水平集
   `{ell_R ≥ M−drop}` 只能是空集、单点或一个闭区间；水平穿越用括号二分收敛，
   不做网格或端点试算。
3. 尾段（最后一个驻点之后）似然单调趋于 −∞，先倍增找到水平下方的点再二分，
   因此分量端点始终有限；找不到有限穿越点时拒绝发布。
4. 分段只在共享驻点确实属于 S 时合并；真实空隙保留，亚公共精度的窄空隙直接
   抛 `NumericalError`，绝不把两段糊成外包区间。
5. `drop=0` 直接返回全部全局最大点（允许并列），不沿用 V1 选最小 τ 的规则。

## 矩范围为什么覆盖内部极值

- 由 Woodbury 恒等式，每个均值、完整协方差条目都是 τ 的有理函数，分母仅含
  `(τ+d_b)` 因子，在 τ≥0 严格为正，无非负奇点。构造细节与恒等式见
  `rational_moments.py` 模块文档。
- 光滑有理函数在闭区间上的极值只可能在分量端点或导数分子的非负根处。
  导数分子是精确 Fraction 多项式，沿用同一套 Sturm 隔离枚举全部内部根，
  因此候选 τ 集合对每个条目都是完备的。
- 所有条目共用同一个 S、同一批候选 τ；范围是逐条目 min/max，代码从不把不同
  条目的端点拼成联合分布，也不对 τ 做积分。
- 每个候选 τ 上，有理函数结果与原 V1 `predict_joint_levels` 条件化结果逐格
  比对（常规量级绝对差闸门，超大量级相对差闸门），不一致即拒绝发布。

## 身份与冻结不变量

- `support_batch` 只消费已发布 fit 的完整冻结队列（解码 fit 负载重建
  `LikelihoodProblem`），不读当前测量；support 负载内嵌 snapshot 与 provenance，
  解码时重新核对。
- support 的父只能是 fit；support_prediction 的父只能是与该 support 绑定的
  fit。类型不符抛 `ValueError`，身份未知抛 `ResultNotFound`。
- 新成果写入独立四张表，外键固定 `support_id → fit_id → cohort_id`。
  更正、撤回、重开或修改返回容器都不影响旧成果；`read_result` 只解码负载，
  已用 `sys.setprofile` 核验不会调用任何拟合/预测/支持求解函数。
- 请求规则（≤8 项、已有/新标记、重复身份共享同一随机批次、空请求合法）
  完全复用 `predictions/identities.py` 与 `requests.py`。

## 数值边界与拒绝发布

- 分量端点内部以 80 位 Decimal 二分至相对 1e-25（触零段绝对 1e-18 地板），
  公共 double 在可分辨 1e-7 间距的量级内强制绝对误差 ≤1e-7；量级超过 double
  能表达该绝对间距时，只在溢出/非有限或相对精度失效时拒绝。
- 矩端点常规量级强制绝对误差 ≤1e-8；超大量级采用相对闸门，非有限即拒绝。
- 任何无法保证完整性或精度的情形（驻点隔离预算、二分预算、不可分辨窄空隙、
  尾段无有限穿越、非有限输出）统一抛原 `NumericalError`，事务回滚，不发布猜测。

## 运行入口

- `python3.11 -B -m unittest discover -s tests -v`：全部原 V1 回归（未改动）。
- `python3.11 -B support_checks.py reference`：有限夹具参照。
- `python3.11 -B support_checks.py verify`：原回归 + 参照 + V2 联合业务核验。
- `python3.11 -B support_examples.py`：两段集合、内部均值极值、重复新身份、
  更正后重开读取的真实演示（自建临时数据库并清理）。
- `python3.11 -B support_audit.py`：独立核账，覆盖闭分量/真实空隙/水平端点/
  内部矩包含/逐项语义/零下降退化/失败回滚重试/更正不变性/重开只读。
- CLI 另增 `support FIT_ID DROP` 与 `support-predict SUPPORT_ID REQUESTS.json`，
  错误仍输出 JSON 并以退出码 2 结束。
