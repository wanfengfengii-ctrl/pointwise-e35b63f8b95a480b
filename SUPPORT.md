# 批次方差支持区域与联合真实水平范围

本扩展接在README.md和BUSINESS_CONTRACT.md的正常重复测量闭环后。
现有测量修订、完整队列冻结、限制似然全局点拟合、固定参数联合预测和固定成果读取均保持。
本题尚未实现以下两个新入口；support_examples.py给出有限输入和演示，
support_checks.py是公开回归，不是集合求解器或完整性证明。

## 业务口径

在application.analysis中提供support_batch(fit_id, drop)和
predict_support(support_id, requests)，继续使用database_session绑定数据库。
两个入口均返回普通字典，成功后可用application.results.read_result(result_id)固定读取。

support_batch必须消费已发布fit_id的完整冻结队列，而不是当前测量或其删减行集。
采用BUSINESS_CONTRACT.md原有ell_R、τ≥0及原2～6批次、至多24行范围。
令M为该冻结队列的全局最大限制对数似然，
S={τ≥0:ell_R(τ)≥M-drop}。
drop只表示对数似然下降预算，不解释为置信水平，不自动选阈值。
它接纳int、float、Decimal及与原测量数值相同的有限十进制字符串，排除布尔、负值和非有限值；
非法drop抛ValueError且不发布成果。

S的所有闭连通分量按左端点递增返回；单点以[τ,τ]表示，
互相接触的区间属于一个分量，真正空隙必须保留。
drop=0保留全部全局最大点，不沿用V1并列时只挑最小τ的结果选择规则。
批次数至少2时ell_R在无限远下降，正常有限drop的各分量均有有限端点。
禁止用最外端点包络替代S。

predict_support接受至多8项有序请求，已有/新批次、重复身份、空请求沿用V1规则。
超限或身份非法抛PredictionRequestError。
对每个τ∈S使用原真实水平模型，报告各请求均值和完整协方差每一项的最小值、最大值；
所有条目的定义域均是同一个S。
这些是逐项范围，不声称所有下端点或所有上端点同时组成一份可实现联合分布，
也不是对τ积分得到的混合分布。重复位置仍代表一个随机批次，不能改成独立变量。
空请求合法，仍检查父成果，返回两个空数组。

必须覆盖每个分量及其内部极值。允许全量重算、逐条目求解和复用V1全部驻点隔离。
不能仅用网格、抽样或分量端点试算作为全局完整性依据。
分量端点绝对误差≤1e-7，矩范围端点绝对误差≤1e-8。
不得因舍入合并真实空隙或删除分量。数值正确性无法保证时抛原NumericalError，不发布猜测；
本文件及support_examples.py中的有限正常样例须成功。

## 返回和固定交接

support返回至少以下字段（允许额外信息）：
- result_id：独立发布身份；kind为support。
- fit_id、cohort_id：父点拟合和其冻结队列身份。
- drop：数值形式的预算。
- components：[[lo,hi],...]，端点为有限数值。
- snapshot、provenance：与父fit结果中同名字段相等的完整冻结输入和有序来源。

support_prediction返回至少：
- result_id；kind为support_prediction。
- support_id、fit_id：本次消费的支持成果及其父拟合。
- requests：与V1相同的有序对象列表。
- mean_ranges：每个请求一个[minimum,maximum]。
- covariance_ranges：q×q矩阵，每格一个[minimum,maximum]；q为请求数。

端点输出采用与V1相同的普通数值，返回容器不成为内部可变别名。
内部表示、计算组织和新增成果编码由实现选择。
支持成果固定父fit_id、完整冻结队列、drop和全部分量，
范围成果固定支持成果、有序请求和范围。之后更正或撤回来源、修改输入或返回值、
关闭重开均不能改变旧成果或其绑定；后来执行旧support_id仍消费原集合和原队列。
read_result只解码已存成果，不重新求支持区域或预测范围。
原fit、prediction负载及含V1数据的数据库仍须可打开和读取，不重置既有数据。

未知父身份沿用ResultNotFound；存在但成果类型不符抛ValueError。
继承原StorageError、原子发布、一次失败一次消费及可重试规则，
扩展db.fail_next_publication("support")和("support_prediction")，
分别在对应发布写入成果头后、完整负载提交前触发同类存储失败。
失败不暴露半成品、不改变已有成果；撤去一次性失败后可稳定重试。
新增表或兼容扩展的组织方式不作指定，不要求另建通用迁移系统。

在batch_analysis扩展完整支持集合生产，在predictions扩展范围预测业务；
拟合职责需要生产完整支持集合；预测职责需要改变单点消费语义，
在该集合上计算矩范围。仅给集合生产加入口会留下点报告；
仅给预测端一个外包区间会在非法τ上取值。请交付两职责的联动实现，
并简述集合、身份和数值边界之间的交接不变量。

## 有限可核账样例

五批次样例沿用NUMERICAL_CASES.json的multi_stationary。
drop=0.080时有两段，约为
[0.25003895168768846,3.1138075525644451]和
[4.2132069678019726,5.7106684402659102]。
中间τ≈3.5556579892030454不属于S，第二峰τ≈5.040483857472118属于S。
已有批次A的均值范围约为[-8.229436493964886,-7.873988348833430]，
最大值在第二段内部τ≈5.021832529627914，而非分量端点。
请求[A已有,X新,X新,Y新]保留顺序和X共享身份。

另外三批次各一行，读数均1、方差均1：
drop=0时S=[[0,0]]；drop=0.5时S=[[0,exp(0.5)-1]]。
所有请求均值恒1。该输入用于完整协方差范围、零边界及常数条目核账。
非零最优τ时，drop=0的预测范围也须退化成原点预测（若全局最大点唯一）。

## 核验与演示入口

保留全部原tests/test_*.py及原业务接口。
从项目根目录运行：
- python3.11 -B -m unittest discover -s tests -v：完整原回归。
- python3.11 -B support_checks.py reference：只核对有限夹具，当前V1也可运行。
- python3.11 -B support_checks.py verify：原回归、有限参照及新增联合业务核验；
  V2实现之前会因缺少新增接口失败，这是新增能力缺口。
- python3.11 -B support_examples.py：完成V2后演示两段集合、内部均值极值、
  重复新身份及更正后重开读取，并执行数值断言。

补充独立业务核账，核验正常链路、零下降、零边界、内部极值、身份规则、
发布失败重试、来源更正和固定读取；有限夹具不替代全局完整性说明。
沿现有.pointwise-runtime.json接通上述联合verify和真实demo，
保持version=1、kind=cli，setup为准备命令的argv数组列表，verify/demo为命令argv数组。
旧demo接口及其回归保留；演示使用自己创建的数据库并清理，不覆盖用户已有数据。
