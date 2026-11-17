# 澄川环境实验室重复测量分析

Python 3.11标准库与SQLite实现的浓度分析链。技术员提交仪器记录，分析员冻结当天复测队列，质控人员读取已有及待测批次真实水平的联合成果。系统报告数值与来源，由质控人员解释结果。

从项目根目录运行：

```sh
python3.11 -B -m unittest discover -s tests -v
python3.11 -B -m application.analysis --db demo-day.sqlite demo --sample sample_day.json
```

演示要求数据库路径尚不存在；已有路径会被拒绝。可为下一次演示选择另一个新路径。正常打开数据库只检查版本并补齐缺失结构，不导入样例、不重置数据。显式重送样例遵守修订语义，保留用户更高修订。命令与预期数值见RUN_MANIFEST.json、NUMERICAL_CASES.json。

一天的工作：

1. 仪器输出测量ID、批次ID、正整数修订、浓度、单位及已知测量方差。
2. 技术员提交整批记录，统一到mg/L；方差按单位因子的平方换算。
3. 技术员更正、撤回或恢复记录；最高修订生效，同版异内容整批拒绝。
4. 分析员按有序测量ID冻结完整行和来源修订，之后的更正仅用于新队列。
5. 分析员对固定队列拟合批次方差，比较所有正驻点与零边界并保存限制似然及均值状态。
6. 质控人员提交有序已有／新批次请求，得到真实水平的完整联合均值和协方差。
7. 实验室补交更正，旧队列和已发布成果仍保持原始绑定。
8. 质控人员关闭重开后读取旧成果；读取不执行统计拟合或预测，返回对象可独立修改。

## 公开Python API

```python
from results.database import Database, database_session
from application.measurements import apply_measurements
from application.cohorts import freeze_cohort
from application.analysis import fit_batch, predict_batches
from application.results import read_result

db = Database("laboratory.sqlite")
try:
    with database_session(db):
        apply_measurements([
            {"measurement_id": "a", "revision": 1, "batch_id": "A",
             "value": 1, "variance": 1, "unit": "mg/L"},
            {"measurement_id": "b", "revision": 1, "batch_id": "B",
             "value": 3, "variance": 1, "unit": "mg/L"}])
        cohort = freeze_cohort(["a", "b"])
        fit = fit_batch(cohort["cohort_id"])
        prediction = predict_batches(fit["result_id"], [
            {"batch_id": "A", "existing": True},
            {"batch_id": "X", "existing": False},
            {"batch_id": "X", "existing": False}])
        saved = read_result(prediction["result_id"])
finally:
    db.close()
```

撤回输入为仅含measurement_id、revision、withdrawn=true的对象，需要该身份的较早来源。恢复使用更高版本的完整正常记录。读数、方差接纳JSON数值或有限十进制字符串，拒绝布尔值；空值不插补。身份区分大小写，不去前缀，不按行位置解释批次。

API返回普通字典。接纳返回逐项disposition（accepted、stale或replay）及最终current_revision；freeze返回cohort_id和有序来源摘要；fit返回result_id、tau、log_likelihood、mean、mean_variance、完整snapshot及provenance；predict返回result_id、fit_id、requests、means及covariance。read_result返回对应的固定成果。空预测请求合法，仍须消费有效拟合。

CLI同样提供apply INPUT.json、freeze IDS.json、fit COHORT_ID、predict FIT_ID REQUESTS.json和read RESULT_ID；都使用前置参数--db PATH。错误输出JSON error并退出2。API业务错误分类及统计口径见BUSINESS_CONTRACT.md。

平衡样例三批次各两次复测：A=[1,2]、B=[4,5]、C=[7,8]，行方差均为1。拟合tau=8.5、均值4.5、均值方差3；两个相同新批次真实水平的协方差11.5，两个不同新批次的协方差3。demo先断言真实计算值，再输出POINTWISE_SCENARIO JSON，并验证来源更正及重开后旧成果相等。

存储提交失败夹具为db.fail_next_publication("fit")或("prediction")：下一次相应发布写入成果头后，会触发SQLite CHECK约束失败。整个业务事务回滚，夹具一次性消费，允许稳定重试。它不替换统计函数，也不返回常量成果。请在专用测试数据库使用。

全部原回归保存在六个tests/test_*.py。数值核账包含平衡手算、零方差、精确有理潜在高斯精度逆矩阵、独立70位Decimal Gauss-Jordan限制似然，以及多驻点的独立得分二分。数据库测试覆盖冲突、撤回恢复、冻结来源、失败发布、初始化、返回对象隔离及磁盘重开。运行环境需允许测试创建自己的临时目录。

## 批次方差支持区域扩展（V2）

`application.analysis`另提供`support_batch(fit_id, drop)`与`predict_support(support_id, requests)`，业务口径见SUPPORT.md，实现交接与不变量见SUPPORT_HANDOFF.md。前者基于完整冻结队列求S={τ≥0:ell_R(τ)≥全局最大值−drop}的全部闭连通分量（保留真实空隙、零下降保留全部最大点、拒绝外包区间）；后者在同一S上对至多8项请求报告逐项均值与完整协方差的最小/最大值，覆盖经Sturm枚举认证的内部极值，不把逐项极值拼成联合分布。数值正确性无法保证时抛原`NumericalError`且不发布。两类新成果独立持久化，支持`db.fail_next_publication("support")`与`("support_prediction")`的一次性失败夹具；读取仍统一走`read_result`且不重算。CLI新增`support FIT_ID DROP`与`support-predict SUPPORT_ID REQUESTS.json`。

新增核验：`python3.11 -B support_checks.py verify`（原回归+有限参照+V2联合核验）、`python3.11 -B support_examples.py`（两段支持、内部极值、重复身份、更正重开演示）、`python3.11 -B support_audit.py`（独立业务核账）。
