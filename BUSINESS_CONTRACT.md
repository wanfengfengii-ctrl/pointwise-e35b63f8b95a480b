# 正常业务契约

## 数据与状态

统一单位mg/L，接受mg/L、ug/L、g/L。因子a分别为1、0.001、1000；读数乘a，测量方差乘a²。测量ID与批次ID是非空且非全空白的不透明字符串，禁止NUL；保持大小写和原字符。revision为非布尔正整数。正常读数有限，方差有限且严格为正。输入非法时整批不变。

measurements/validation.py先规范整批；measurements/revisions.py根据全部相关历史构造纯写入计划；measurements/repository.py在一个事务中提交历史及当前索引。同一ID和版本的相同规范内容为重放，异内容为RevisionConflict；包括提交内部及旧历史版本。旧合法版本保存历史但不覆盖当前最高版本。撤回仅有身份、版本和withdrawn=true，沿用严格较早的最近来源内容；未知来源撤回拒绝。恢复是更高的完整有效修订。同批撤回可以引用前面已给出的较早修订。接纳回执中的current_revision是该批完成后的当前版本。

cohorts/selection.py拒绝空、重复、未知和已撤回选择；cohorts/repository.py在同一事务选择并保存完整快照。cohorts/snapshot.py中的行序、测量ID、批次ID、浓度、方差及来源修订永久固定；provenance.py提供有序修订摘要。每次成功冻结有独立cohort_id。

## 计算与下游消费

模型 y_i=μ+u_batch(i)+e_i；批次偏移独立，方差τ≥0；e_i独立，方差v_i已知且正。拟合域为2～6个批次、至多24行，使用完整冻结行，不删除合法观测。

D=diag(v_i)，Z按冻结批次身份构造，V=D+τZZᵀ，s=1ᵀV⁻¹1，μ_hat=1ᵀV⁻¹y/s，P=V⁻¹−V⁻¹11ᵀV⁻¹/s。

ell_R(τ)=−[(n−1)log(2π)+log|V|+log(s)+yᵀPy]/2。

batch_analysis/likelihood.py拥有该限制似然及FitState。stationary.py以精确Fraction批次统计构造得分多项式，平方自由化并以Sturm计数隔离全部正根；selection.py把这些根及τ=0放在同一目标口径下比较。全局并列选最小τ，不用普通最大似然、固定网格或单次局部迭代替代。τ绝对误差≤1e-7，限制对数似然误差≤1e-8；若数值或候选完整性不能保证，抛NumericalError，不发布猜测。

为复算候选，记w_b=Σ_i∈b 1/v_i，m_b=Σ_i∈b y_i/v_i /w_b，d_b=1/w_b，W=Σ_i (y_i−m_batch(i))²/v_i。令A=Σ_b Π_c≠b(τ+d_c)，N=Σ_b<c (m_b−m_c)²Π_k≠b,c(τ+d_k)。限制似然等价为
−[(n−1)log(2π)+Σ_i log(v_i)+Σ_b log(w_b)+log A+W+N/A]/2。
得分分子相差非零因子后为A'A+N'A−NA'。A在非负域严格为正，故无额外非负分母奇点。批次数≥2时无限远似然下降。原始行内残差及常数仍由完整协方差计算核对。密集运算采用80位Decimal Cholesky与线性求解，根隔离使用精确有理端点且区间宽≤1e-24；不满足公开浮点输出绝对精度时失败。极端数值可能触发数值业务错误。

预测消费已发布FitState，固定其τ，对μ使用平坦先验。已有ID必须在固定来源中；新ID必须不在固定来源中；相同ID的标记不能矛盾。predictions/requests.py保存顺序，identities.py将重复位置映射到唯一随机批次；conditioning.py构造交叉块与条件状态；joint.py恢复有序完整结果。请求为空合法。

B_qi在查询批次等于观测批次时为τ，否则0；K_qr在查询批次身份相同为τ，否则0。a=1_q−BV⁻¹1。

预测均值=1_q μ_hat+BV⁻¹(y−1μ_hat)；
预测协方差=K−BV⁻¹Bᵀ+aaᵀ/s。

对象是真实水平μ+u，不加入未来测量噪声，不传播τ估计误差。重复新身份共享一个偏移；不同新身份仍共享均值不确定性。τ=0时全部真实水平共享总体均值及其方差。均值、完整协方差各项误差≤1e-8。不得裁剪非对角项伪造独立性。

NUMERICAL_CASES.json固定三种有限样例。多驻点队列五批次分别为−8、−8、0、−9、1，测量方差1、0.1、100、0.1、10。三个正驻点约0.5726353006188497、3.5556579892030454、5.040483857472118；比较零边界后第一个为全局最大值。测试独立核账该结论，数据文件自身不替代断言。

## 发布、读取与错误

results/schema.py保存版本1、修订历史/当前索引、完整队列、成果头与完整负载，并以外键约束来源关系。initialize_schema只创建缺失结构；不兼容版本抛SchemaVersionError且不改变数据，不隐式导入样例。

results/fit_codec.py持久保存固定观测、来源、τ、限制似然、均值、精度及观测逆作用向量。prediction_codec.py保存父fit_id、有序请求和完整矩阵。编码核验有限性与维度；解码只读已存状态，不求最优τ、不条件化。成果头和负载在results/database.py的一次事务内提交，提交后才返回身份。来源或父成果不符、存储错误、计算错误都不暴露本次成功成果。发布失败后已有成果保持不变，撤去一次性失败夹具即可重试。ResultNotFound表示未知成果，StorageError映射SQLite异常。

application/measurements.py的apply_measurements(batch)实现I1；application/cohorts.py的freeze_cohort(ids)实现I2；application/analysis.py的fit_batch(cohort_id)、predict_batches(fit_id,requests)实现I3/I4；application/results.py的read_result(result_id)实现I5。API由database_session绑定当前连接，不增添隐藏业务参数。MeasurementError、RevisionConflict、CohortSelectionError、FitDomainError、PredictionRequestError分别表示相应领域错误。所有修改事务回滚后错误向上抛出；CLI映射为JSON error与退出码2。

读取返回新容器。修改输入、返回值、当前来源、关闭重开均不能改变既有队列和成果。read_result不依赖任何拟合选择或条件化入口，不用当前测量重建旧数值。

## 确定性业务回归

normal_checks下标由RUN_MANIFEST.json定义：
0为完整unittest discover，保留六文件全部测试。
1共同覆盖V1单位/修订/撤回恢复、V5新批次共享身份、V7真实SQLite发布失败回滚重试、V8源更正与磁盘重开。
2覆盖V2批中后项冲突整批回滚及V6已有/新条件化、标记冲突、请求重排。
3覆盖V3冻结内容、顺序与来源，拒绝非法选择，更正/撤回不改变旧队列。
4覆盖V4平衡手算、零边界、全部正驻点、独立高精度目标值、重复根、候选并列比较及规模边界。
完整套件另含异精度已有/新批次精确联合高斯核账、demo数据库不覆盖和用户更正保全。所有断言对实际业务输出执行；独立参照不调用被测统计函数。

程序没有随机统计采样。UUID仅生成成果身份，不影响批次身份或数值。无第三方依赖，无外部服务，不要求前端。多层随机效应、随机斜率、未知测量方差、τ估计误差传播、置信区间及自动质控决策不属于当前能力。
