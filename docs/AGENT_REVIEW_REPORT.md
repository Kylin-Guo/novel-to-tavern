Novel-to-Tavern 仓库审查报告（供 Agent 执行）
- 审查对象：https://github.com/Kylin-Guo/novel-to-tavern
- 审查基准：公开仓库 master 分支，2026-10-17
- 报告用途：指导本地 Agent 复核问题、修复缺陷、补充测试；不是要求 Agent 不加判断地套用修改。
- 审查类型：静态代码与设计审查。浏览环境能够读取公开 GitHub 页面和部分 raw 文件，但无法在此容器中 clone 仓库、执行项目测试或 Tavo；部分目录（尤其 tests/ 和 tools/）未能在远程浏览界面中逐文件独立展开。因此，Agent 必须先在本地 checkout 中验证每个发现、枚举完整文件清单并运行测试。不能把本报告当作“289 个测试已由审查者实际运行”的证明。
0. 执行摘要
项目方向整体合理：它已经从早期文档模板发展成有 CLI、分阶段管线、Pydantic 数据模型、证据定位、世界书计划、角色卡序列化器、校验器、运行报告和测试框架的工程项目。特别值得保留的是：原始小说只读、事实带来源、人物归一留待审核、输出隔离在 run 目录、JSON 由代码序列化、以及把事实提取与最终导出分开的设计。
但在当前公开源码中，发现了几个需要优先复核/修复的高风险点：
1. 严格章节导出代码疑似会直接抛出 TypeError：导出器调用 build_greetings() 时传入 strict_label 和 strict_chapter_index，但当前 builder.py 中该函数定义没有这两个形参，也没有 **kwargs。这与 RUN_REPORT.md 声称已生成严格章节卡不一致。必须先在本地复现并增加真正调用 CLI 的回归测试。
2. 严格无剧透不能只过滤世界书条目：严格导出路径仍将完整 digests、entities、timeline 交给 greeting builder。即使只给函数增加两个参数、让程序不再崩溃，也可能把未来角色名单、结局或后期事件带入 first_mes / alternate_greetings。必须按起始章节构建受限的 greeting 输入。
3. 缺省 fact_type 会把未标注事实静默归为 canon_fact：这与提取提示词“拿不准不要用 canon_fact 兜底”的原则相冲突。缺字段时应进入 unknown/待审，而非默认正史。
4. 语义校验的 partially_supported 不被视为问题：部分支持的复合主张目前可能通过 .ok 判断并继续进入导出。严格保真模式应把部分支持项拆分或放入人工复核队列。
5. 证据定位的“找到引文”不等于唯一、准确地定位到该处：代码移除所有空白后仅取首次匹配；重复短句、段落边界或短引文可能产生歧义，报告中的“100% 定位”不能解释为“100% 语义正确”。
6. 完整原著主线条目的触发词仍包含“剧情”“主线”等常见词：它关联的是数万字符的全书主线；意外触发会造成 Token 暴涨及未来剧情泄漏。
7. 公共仓库中存在由《天之炽》全书产生的衍生角色卡：NOTICE.md 声明它不在 MIT 许可范围内并不自动等于获得公开再分发授权。建议在确认权利状态前，停止继续分发并考虑以合成/公版 fixture 替换。删除 Git 当前树中的文件不等于清除历史版本。
8. pyproject.toml 的包许可证元数据写成 Proprietary，但仓库 LICENSE 和 README 声明 MIT，需要统一。
9. CLI 的 --run-id 在多个子命令中直接拼接路径，而路径合法性检查看起来只在创建 run 时调用；应对每个读写 run 的命令统一做路径边界校验。
10. 文档/状态不一致：CLI 里 TARGET_CLIENT 仍写“ Tavo（待实测）”，但其他文档称已测试基本导入；另一方面，运行报告说严格章节导出成功，当前函数签名却不匹配。需要用当前 checkout 重新产生可信的测试报告，不能手工保留旧结果。
建议顺序：先本地复现严重问题和确认敏感衍生物的处理方案；接着修复严格导出、事实分类、证据定位与语义校验；然后处理触发词、CLI 路径和参数验证；最后统一文档状态、配置项和测试/兼容性记录。
1. 严重程度定义
- P1 — 高优先级：会导致关键功能崩溃、剧透风险、正史污染或公开分发风险。修复前不要声称相应能力可靠。
- P2 — 中优先级：会造成路径错误、误触发、漏提取、缓存污染、配置误导或质量难以验证，应在下一轮迭代处理。
- P3 — 低优先级/维护性：重复代码、文档组织、可维护性与使用体验；不应压过 P1/P2。
- 待核实：远程静态检查发现迹象，需 Agent 在本地全仓搜索并用测试确认。
2. P1：高优先级问题
P1-01 严格章节导出调用与函数签名不一致，可能无法运行
位置：
- src/novel_to_tavern/export/runner.py，严格导出分支调用 build_greetings(...) 附近（公开源码约 L410 起）
- src/novel_to_tavern/export/builder.py，build_greetings() 定义（公开源码约 L176 起）
观察：当前可见的 runner.py 在严格章节导出时向 build_greetings() 传入 strict_label 和 strict_chapter_index；当前可见的 builder.py 函数签名只包含 book_title、digests、entities、timeline，没有这两个关键字参数，也没有 **kwargs。Python 会抛出 TypeError: unexpected keyword argument ...。
风险：n2t export --run-id ... --start-chapter N 可能无法生成严格章节卡。docs/RUN_REPORT.md 声称曾生成过 card_start_chapter_1.json，与当前源码不一致，可能说明报告过期或后续修改引入回归。
修复建议：
1. 在本地 checkout 先运行该命令复现，不要先改代码。
2. 不要只给函数签名增加两个未使用参数来消除异常；应明确设计 build_greetings_for_start_chapter(...)，或把章节过滤后的输入传入现有 builder。
3. 严格模式必须基于截至起始章节可见的摘要、人物、地点和事件生成开场白。
4. 严格模式的 alternate_greetings 不能保留“原著结局后”的开场白，除非该卡明确允许切换到该时间点且配套知识也已更新；推荐严格章节卡只保留与该起点匹配的 greeting。
5. 加集成测试，真实调用 CLI 的严格导出路径，断言退出码、输出文件存在、字段有效并通过剧透测试。
验收：n2t export --run-id <fixture_run> --start-chapter 1 与中后章节导出都能成功；输出中的开场白、替代开场白、人物名单及触发条目不引用起始章节之后的事实。
P1-02 严格无剧透仅过滤条目不够，开场白仍可能读取全书数据
位置：src/novel_to_tavern/export/runner.py 严格导出调用 build_greetings() 的输入构造；src/novel_to_tavern/export/builder.py 的 build_greetings()、角色 roster、地点和事件摘要构造逻辑。
观察：严格导出路径把全量 digests、entities、timeline 传给 greeting builder。即使世界书规划已经根据 start_chapter 过滤晚于起始章节的内容，开场白仍可能从全量人物/地点/时间线挑出后期人物或终局事件。
风险：严格卡的世界书可能不含未来事实，但 first_mes 或 alternate_greetings 却提前泄露未来角色、地点、结局或事件。这样“严格章节卡”名不副实。
修复建议：
- 明确区分“小说全文 canonical 数据”和“当前起始点活动数据”。严格导出开始时先产生 StartState，再让 greeting builder 只能接收该状态及截至章节 N 的资料。
- 对 event_chapter > N、valid_from_chapter > N 或 revealed_at_chapter > N 的资料，在传入 greeting 前过滤；处理 revealed_at_chapter 缺失时要保守，未知不可默认视为早已公开。
- 在生成结果中检查 greeting 的实体 ID/事件引用；不建议仅用最终字符串关键词检测剧透，因为同名、别名和间接泄漏难靠关键词完全覆盖。
验收：用一个合成测试故事，人物 B 第 8 章才出现、秘密在第 12 章才揭露；从第 2 章严格启动时，问候、备选问候、常驻条目和条目触发均不得出现 B 或秘密内容。
P1-03 fact_type 默认值会把漏标事实变成正史
位置：src/novel_to_tavern/extract/schema.py，RawFact.fact_type、RawEvent.fact_type（公开源码约 L47–70）；对应 extract/prompts.py。
观察：提取提示词明确要求只有原文确立的事实才使用 canon_fact，不确定信息用 inference 或 unknown。但 RawFact / RawEvent 的 fact_type 默认值是 CANON。如果模型漏掉字段，Pydantic 会静默填入 canon_fact。
风险：本应未知/推断的事实可能被升级成原著正史；若后续语义审计未运行或误判，错误会进入世界书与角色卡。
修复建议：
- 对模型输入 schema，把 fact_type 设为必填；或缺失时安全回退到 unknown 并进入 review queue。
- RawMention.kind 默认 character 也有类似的静默分类风险：缺少类型时应使用 unknown 或要求模型明确分类，而不是默认每个实体都是人物。
- 不应以 quote 非空或定位成功代替“事实类型正确”。
- 增加无 fact_type、错误枚举值、类型缺失与引用正确但事实不确定的测试。
验收：构造缺字段模型响应，结果必须变为 unknown/待审或触发重试，不得自动成为 canon_fact。
P1-04 partially_supported 语义校验结果可能仍当作通过
位置：src/novel_to_tavern/verify/schema.py 中 PROBLEM_VERDICTS 与 SemanticVerdict.ok；src/novel_to_tavern/verify/ 相关逻辑。
观察：当前问题 verdict 集合包含 contradicted 和 insufficient_evidence，但 partially_supported 没有被纳入问题集合；.ok 因而可能为真。对“部分内容有原文依据、部分内容没有依据”的复合主张，这会产生假阳性通过。
风险：角色背景、能力、因果关系等复合事实的一部分被证实后，额外的编造部分仍可能输出。
修复建议：
- 将 partially_supported 默认送入 review_required，严格模式下不直接导出。
- 先把复合主张拆成最小事实单元，再逐条校验；仅将已支持的原子事实进入 canon。
- 在 audit.md 分开报告 supported、partially_supported、contradicted、insufficient_evidence、not_checked 的计数。
验收：构造一个含两个子断言、只支持其中一个的事实，默认不得作为已确认的完整 canon 项导出。
P1-05 引文定位“命中”不等于唯一且正确的来源定位
位置：src/novel_to_tavern/extract/evidence.py 的 normalize_for_match() / locate_quote()（公开源码约 L33–88）；extract/prompts.py 中 quote 长度要求。
观察：当前算法移除所有空白并在 chunk 拼接文本中查找引文，通常只接受首次命中。代码不检查同一句在同一 chunk 是否重复出现，也可能把跨段落的空白消除后视为连续匹配。提示词约束 quote 约 5–80 字，但 schema/定位代码可接受更短的字符串，且代码允许更长的引用。
此外，matched_text 是整条/多条源文本行的拼接，而不是模型提供的精确短引文。因此“原文引文 100% 找到”目前只能说明文本匹配成功，不能说明语义支持、出现位置唯一或引用窗口准确。
风险：同一句话在不同人物或章节重复出现时，事实可能被错误地定位到第一次出现；过短引文（例如常见短语）会产生误定位；保存整行还可能把比必要证据长得多的原文写入中间文件/报告。
修复建议：
1. 返回所有匹配位置，而不是只取第一个；若多处命中，标记 ambiguous 并要求补充定位上下文或再次抽取。
2. 维护精确引文与可选上下文窗口两个字段：quote_exact 和 context_excerpt；限制上下文长度。
3. 对引文长度做强制校验；过短或过长的 quote 应重试或放入人工审核。
4. 用保留章节 ID、行号、字符 offset 的方式定位；不要单靠“去除所有空白后的全文子串”决定位置。
5. 报告应分别给出 matched、unique_match、ambiguous、not_found，避免用一个“100% 定位率”掩盖歧义。
验收：测试同一个短句在同一章节出现三次、多个章节重复、跨段落边界、空格和换行变化、常见 2–4 字短语、无法命中等情形。
P1-06 全书主线条目使用常见触发词，存在误触发和整书剧透风险
位置：src/novel_to_tavern/export/builder.py 的 PLOT_ENTRY_KEYS / build_plot_entry()；exports/README.md 对全书主线条目的说明。
观察：完整原著主线被存为一个数万字符的世界书条目；触发词中仍有“剧情”“主线”等常见中文词。普通对话如“这个剧情怎么发展”“主线任务是什么”，可能触发整个原著主线。文档承认默认卡包含全书主线、依赖提示词要求模型按时间行事，而非结构化时间过滤。
风险：意外把未来剧情放进上下文；输入 Token 突然上升；模型可能把本应尚未揭露的原著真相作为当前知识使用。对于追求严格设定的项目，这与目标冲突。
修复建议：
- 不要把完整主线作为普通关键词自动触发的大条目。优先将时间线拆为章节/阶段条目，附 valid_from_chapter、revealed_at_chapter，由起始状态控制哪些条目允许激活。
- 如果保留全文检索入口，使用明确且少见的显式命令关键词（例如用户主动请求“原著逐章大纲”），不要使用“剧情”“主线”这类自然对话高频词。
- 添加真实中文用户提示语的误触发测试集，包括“剧情太慢了”“主线是什么”“改一下剧情”“前情回顾”等。
- 严格章节卡不得包含全书主线条目；即使不激活，也不应把未来事实写入可能被客户端其他机制读取的常驻区域。
验收：常见聊天内容不触发全书大条目；明确检索命令能按预期命中；严格章节输出不存在起始章节后的主线内容。
P1-07 公共 exports/ 中包含基于受版权保护小说生成的角色卡
位置：exports/天之炽/world_simulator_v2.json、exports/README.md、NOTICE.md、.gitignore。
观察：仓库跟踪了一份约 225 KB、含 180 个内嵌世界书条目的角色卡。运行报告描述输入是小说《天之炽》156 章文本，并包含全书主线条目。NOTICE.md 已声明该导出不是 MIT 授权、权利归原作者/权利人，但文件仍在公开 GitHub 仓库中可下载。
风险：声明“本文件不在许可证范围内”不会自动赋予公开分发衍生角色卡的授权。该产物含原著结构化设定与较完整剧情概述，可能产生版权、仓库可持续公开和项目使用者误以为可自由再分发的风险。这里是分发风险提示，不是法律结论。
修复建议：
1. 仓库所有者确认是否拥有公开分发该产物的权利。未确认前，建议停止继续把该文件作为公开样例分发。
2. 用原创合成小说或明确可再分发的公版文本替换仓库样例；只保留用于验证格式的最小 fixture。
3. 把真实小说、抽取中间数据和用户生成卡默认排除在 Git 之外；CI 测试使用合成资料。
4. 若决定移除已提交的导出物，应区分“从最新版本删除”和“从 Git 历史清除”。历史重写会影响协作者 clone 与远端，需要仓库所有者明确批准后才能进行，不要由 Agent 擅自 force-push。
5. 保留清楚的 NOTICE，但不要把 NOTICE 当作解决授权问题的替代品。
验收：公开仓库样例仅包含授权文本；.gitignore 覆盖所有运行输出；报告明确记录真实作品不会进入测试 fixture。
3. P2：中优先级问题
P2-01 pyproject.toml 许可证与仓库 LICENSE 不一致
位置：pyproject.toml [project] license = { text = "Proprietary" }；根目录 LICENSE；README。
观察：包元数据为 Proprietary，但根目录许可证和 README 称代码/文档使用 MIT。
风险：发布到包索引、构建 wheel 或被工具读取元数据时，会得到与实际声明冲突的许可证信息。
建议：统一项目元数据与实际授权边界。若代码为 MIT 而某些目录例外，明确写在根 README、NOTICE 和打包文件清单；避免将 exports/ 衍生作品与软件源代码混为同一许可范围。使用当前 pyproject.toml 规范支持的许可证声明写法，并加元数据检查测试。
P2-02 子命令缺少统一 run_id 路径边界验证
位置：src/novel_to_tavern/cli.py 的 _cmd_extract、_cmd_resolve、_cmd_timeline、_cmd_verify、_cmd_export；src/novel_to_tavern/ 的 run 路径工具。
观察：多个子命令根据 Path(config.project.output_root) / args.run_id 构造路径；合法 ID 检查看起来主要位于 ingest/create-run 路径，并非每个读取既有 run 的入口都会调用。
风险：错误或恶意的 --run-id 值（如 ../...、绝对路径、符号链接路径）可能导致工具在预期 run 根目录之外读取或写入文件。即使这是本地 CLI，仍会带来误操作风险。
建议：建立一个统一 resolve_run_dir(output_root, run_id, must_exist) 函数。所有子命令都必须先验证 ID 格式，再 resolve() 并断言目标目录在受控 output_root 之下；还应检查符号链接边界。不要只在创建目录时校验。
验收：对 ../escape、绝对路径、空字符串、反斜杠路径、Unicode ID、合法 ID 与符号链接分别测试。失败必须发生在任何文件写入之前。
P2-03 --start-chapter 的范围验证不充分
位置：src/novel_to_tavern/cli.py 中 --start-chapter 参数与 start_index = start_chapter - 1 if start_chapter else None 一类转换。
观察：章节编号面向用户应当从 1 开始，但参数仅以整数解析时，0 可能因为 falsey 而被当成未指定，负数可能被转换为意外索引。
建议：为 CLI 增加正整数校验；检查章节上限，超过章节数量时清晰报错。内部转换使用显式 is not None，不要用真值判断是否提供参数。
验收：0、负数、非整数、超过总章节数均返回明确错误，不生成输出；1 和末章有效。
P2-04 缓存键必须区分真正的 API endpoint
位置：src/novel_to_tavern/extract/runner.py 的 cache key 构造；src/novel_to_tavern/llm/provider.py。
观察/待本地确认：缓存键包含 provider 名称、模型、提示词/Schema 版本、chunk hash 和温度，但若 provider.name 仅是通用值（如 openai_compatible），没有纳入规范化 endpoint 身份，切换不同免费 API 提供商但使用相同模型字符串时，可能复用上一个 endpoint 的缓存。
建议：将 endpoint 的非敏感指纹纳入缓存键，例如规范化 base URL 的哈希；绝不能把 API key 放入文件名或日志。还要覆盖所有影响输出的参数，包括 top-p、最大输出 token、响应格式和 provider-specific 参数（如实际支持）。
验收：相同文本/模型名/提示词但不同 endpoint 的请求不会误命中同一缓存；同 endpoint 且配置相同时仍能命中缓存。
P2-05 配置里疑似存在没有被消费或没有进入指纹的字段
位置：config/config.example.yaml、src/novel_to_tavern/config.py 与 CLI/workflow。
需 Agent 全仓搜索确认的字段：
- input.formats：ingest 文件发现逻辑可能直接硬编码 .txt / .md，未必按此配置过滤。
- input.normalize_newlines：检查实际读取是否使用它，以及是否参与 resume/config fingerprint。
- project.mode、default_start_chapter：确认它们是否真实影响默认导出；不能仅写在 YAML 中但 CLI 从不使用。
- llm.synthesis_model、audit_model、temperature_synthesis：当前 build_provider() 看起来主要使用 extraction_model / temperature_extract；verify 路径似乎也复用该 provider。因此这些配置可能尚未连到实现。
- max_output_tokens、max_concurrent_requests 等参数也应逐个检查是否已由 provider/runner 消费。
风险：用户改了配置但行为不变，或者变更后 resume 错误复用旧结果。
建议：为每个配置键建立“定义位置 → 消费位置 → 测试”的表。未实现的选项要么接通并测试，要么移除并注明路线图状态。所有影响解析/提取结果的配置必须纳入 run fingerprint/cache key。
P2-06 partially_supported 和未运行语义审核的状态应更透明
位置：README 快速开始、docs/RUN_REPORT.md、n2t verify 流程、导出器。
观察：README 的典型快速流程从 timeline 直接进入 export，没有把 verify 作为严格保真输出的前置门槛。示例运行报告记录语义支持性验证因为 API 额度未执行；仅抽样检查少量事实。引文命中率不能替代语义支持性验证。
建议：
- 设计 --strict-fidelity 或等价模式：若高重要性事实尚未完成语义审核，阻止严格导出或明确要求用户显式确认。
- 普通省钱模式可以继续导出，但 audit.md 与卡片元数据/生成日志必须显著标注“语义验证未完成”。
- 将自动验证、人工抽样、Tavo 实际运行分为三个独立状态，不用“100% 引文定位”概括整体质量。
P2-07 世界书生成有明确的实体覆盖阈值，可能漏掉用户想扮演的小角色
位置：src/novel_to_tavern/timeline/worldbible.py 中 MIN_ENTITY_FACTS、MAX_INDEX_ENTRIES、角色索引规划；运行报告中 canonical entity 与 worldbook entry 计数。
观察：部分实体只有在达到事实数量或跨章节出现的阈值后才会获得独立条目；人物索引也有上限。运行报告中 canonical 实体数明显多于最终世界书条目数。
风险：提取到的人物可能没有任何可触发的独立背景。用户如果想扮演不在头部索引中的配角，模型可能只能从有限聊天史中临时编造其设定。
建议：
- 保留所有实体的索引和“为何未生成详细条目”的原因；不能静默丢弃。
- 把条目策略做成配置（核心人物/所有人物/按名单 include），允许用户强制保留指定人物。
- 对小角色可以生成很短的安全条目，而不是每人都输出冗长档案。
- 报告 entity coverage：人物总数、拥有独立条目的数量、只有索引的数量、被过滤的数量及原因。
P2-08 世界书触发参数需要真实运行测试，而不仅是 JSON 验证
位置：docs/FORMAT_COMPATIBILITY.md、docs/TAVO_IMPORT_CHECKLIST.md、src/novel_to_tavern/tavern/validator.py。
观察：当前校验器能验证字段/结构，但不能证明 Tavo 的实际触发、插入位置、递归和上下文预算行为。文档亦说明这些运行时项目尚未完整验证。
建议：
- 在 Tavo 中记录客户端版本、iOS 版本、导入时间、主卡 hash、条目数量、常驻/触发测试结果。
- 至少用 10 个 fixture 验证：常驻规则、中文名字触发、别名触发、无关词不触发、两个条目冲突、strict start 不含未来条目、未命中时的 fallback、条目预算、重复条目、重新导入后的持久性。
- 自动校验与人工导入结果分开；不要把兼容目标版本写成对所有 Tavo 版本的保证。
P2-09 严格导出/CLI 状态名称和实现阶段存在文档漂移
位置：src/novel_to_tavern/cli.py 的 TARGET_CLIENT、README.md、docs/PLAN.md、docs/IMPLEMENTATION_PLAN.md、docs/RUN_REPORT.md、docs/TAVO_IMPORT_CHECKLIST.md。
观察：CLI label 仍将 Tavo 标为“待实测”；Tavo checklist 又称基本导入与内嵌世界书识别已测试；README/RUN_REPORT 记载的严格章节导出又与当前 builder/runner 函数接口不一致。文档的 Phase 编号、语义 verify、timeline、export 顺序也需要统一。
建议：在一次通过测试的 checkout 上重跑最小 fixture，重新生成 RUN_REPORT，而不是手工改数字。统一“格式符合性”“Tavo 能导入”“世界书触发已测”“无剧透已测”四个状态。每个状态必须有具体证据和测试日期。
P2-10 100% quote-location 指标的命名可能让用户高估可靠性
位置：docs/RUN_REPORT.md、exports/README.md、evidence.py 的 locator 统计。
观察：示例报告中 5,746/5,746 的 quote locator 命中率为 100%，但本次审查未看到同一指标对唯一命中、语义支持、错误归属进行分别计数。
建议：将 metrics 拆为 quote_found_rate、unique_quote_rate、source_ref_valid_rate、semantic_supported_rate、human_reviewed_rate。报告明确写出哪部分没运行，不能用一个 100% 让读者误解为“事实都准确”。
4. P3：代码维护和工程一致性
P3-01 build_plot_entry() 在同一文件重复定义
位置：src/novel_to_tavern/export/builder.py，公开源码中约 L71 与 L101。
观察：同名函数出现两次，第二个定义覆盖第一个定义。即使目前逻辑接近，这也会让维护者误判哪个版本生效。
建议：保留单一实现，检查两段是否有差异后合并；加一个 worldbook plot entry fixture 验证 keys、正文、长度与时序 metadata。
P3-02 默认章节解析配置与文档应保持一致
位置：src/novel_to_tavern/ingest/chapters.py、config/config.example.yaml、docs/FORMAT_COMPATIBILITY.md。
观察：自动章节检测在标题识别不足时会回退到合成章节/自动分块。这是合理 fallback，但用户必须知道“源文件真实章节”与“工具合成分块”不是一回事。
建议：在 manifest 和 audit report 中明确使用的是 detected、manual 还是 fallback_chunked 章节边界。对只有一章标题或无标题的文本显示警告，并提供正则/手工映射配置。
P3-03 错误日志与调试信息要避免泄露长篇文本
位置：src/novel_to_tavern/llm/、失败响应 quarantine、audit report。
建议：日志默认记录 chunk ID/hash、错误类型和短截断，不默认记录整段原文或完整 provider response。用户可以通过显式 debug 选项将敏感调试记录存入本地受保护目录。
P3-04 提示词版本、配置版本与产物 manifest 应形成闭环
位置：src/novel_to_tavern/extract/runner.py、run manifest、docs/DATA_MODEL.md。
肯定点：当前缓存键已经考虑模型、提示词模板指纹、Schema 版本、chunk hash 与温度，是值得保留的设计。
建议：补齐 endpoint 指纹与全部有效 generation 参数；在最终 export manifest 中写入输入 hash、配置 hash、Schema 版本、prompt 版本、run ID、起始章节、导出文件 hash 和各项质量门禁结果。这样 README/RUN_REPORT 就能由实际机器产物生成，不靠人工同步。
P3-05 测试计数应有单一来源
位置：README 中“289 offline tests”类固定数字、CI workflow、测试目录。
建议：README 不要手写容易过期的测试数量。CI 自动输出测试总数/通过/失败；RUN_REPORT 引用具体 commit、命令和输出。如果不能在审查环境运行测试，应明确写“测试由 CI 在 commit X 上通过”，而不是泛称已通过。
5. 设计层面的改进建议
5.1 将主卡拆成“运行协议”和“原著资料”两类内容
主卡应常驻的只有：模拟器身份、用户角色控制权、NPC 知识边界、因果/时间规则、对不确定事实的处理原则、分支模式规则。详细人物、势力、地点、能力和历史应通过 worldbook 条目按需加载。
“原著全书主线”不要默认作为一个普通关键词条目。对起始章节 N 的严格体验，应由 exporter 在生成时过滤可见数据，而不是期待模型在看到全书剧透后自律。
5.2 Canon 和推断/分支内容必须物理可区分
建议最终导出与中间资料始终分清：
- 原著 canon；
- 角色相信/谣言；
- 模型推断；
- 用户新增；
- 分支剧情新发生的内容。
分支剧情不应反向覆写原著 canon；新事件应写入当前 run 的动态状态，而不是永久修改世界书原文资料。
5.3 不要把“JSON 合法”当作“角色卡质量合格”
至少需要四层 QA：
1. 结构：JSON、字段类型、格式版本；
2. 来源：每项关键 canon 能否找到唯一来源；
3. 语义：原文是否真的支持该陈述；
4. 运行：在 Tavo 中实际触发与起始章节行为是否正确。
四层应分别呈现通过/失败/未测试，不应汇总成单一绿色“verified”标志。
5.4 长篇小说的人物覆盖要可配置
默认不应该用文件大小或模型直觉删除人物。可以把人物划分为 core、recurring、minor、mentioned，根据每个等级安排条目详细度。对指定要扮演的人物允许 --include-character 强制生成资料。所有被省略的人物应在报告中列出原因。
6. 建议的整改顺序与 Agent 任务拆分
Task A — 本地核验和安全检查（先做）
- [ ] git status、当前分支和 commit hash。
- [ ] 输出整个文件树；确认 tests/、tools/、.github/workflows 的所有文件。
- [ ] python -m pytest -q，保留完整结果；不允许只引用 README 测试数量。
- [ ] 尝试 n2t export --run-id <fixture> --start-chapter 1 复现 build_greetings 参数错误。
- [ ] 全仓搜索配置键，输出定义/使用/测试表。
- [ ] 确认 exports/天之炽/world_simulator_v2.json 是否具有公开分发授权；在用户作决定前不要自行 force-push 或重写 Git 历史。
Task B — 严格章节导出的功能正确性
- [ ] 修复 builder/runner 函数契约不一致。
- [ ] 以起始章节状态生成 greeting、alternate greetings、角色列表和世界书。
- [ ] 增加未来角色、后期揭露秘密、结局信息不会进入早期卡的测试。
- [ ] 对 --start-chapter 0、负数、超过末章做 CLI 校验。
Task C — 事实与来源正确性
- [ ] fact_type 和实体 kind 缺失时默认安全，不得自动成为 canon/character。
- [ ] quote locator 返回唯一性/歧义状态，强化 quote 长度和上下文存储。
- [ ] 将 partially_supported 默认放入复核队列；把复合主张拆成原子事实。
- [ ] 为未执行语义检查的导出设置透明标记；必要时实现 strict-fidelity gate。
Task D — 世界书触发与覆盖
- [ ] 收窄全书主线条目的触发词；测试常见中文输入误触发。
- [ ] 清楚报告缺少独立 worldbook entry 的实体；允许 include list。
- [ ] 严格模式下不将全书主线写入可被激活的卡中；优先用章节分段条目/按时间状态过滤。
- [ ] 在 Tavo 中测试至少 10 个实际触发/无剧透用例，并记录客户端版本与日期。
Task E — 工程一致性与安全
- [ ] 将 pyproject.toml license 与实际许可证范围对齐。
- [ ] 所有子命令统一验证 run ID 和解析路径边界。
- [ ] 校正或删除未使用的 config options，将影响输出的选项纳入缓存键/fingerprint。
- [ ] 删除重复 build_plot_entry()，补对应测试。
- [ ] 重生成 README/PLAN/RUN_REPORT/TAVO checklist 的当前状态信息。
- [ ] 确保示例生成文件由合成或明确授权文本产生。
Task F — 最终审查门禁
- [ ] 全部离线测试通过；CI 记录 commit hash 与测试数量。
- [ ] 结构/来源/语义/运行四类 QA 分别出结果。
- [ ] n2t export 生成主卡、独立世界书和严格章节卡的测试全部通过。
- [ ] 验证卡片内嵌世界书和独立世界书的条目语义一致。
- [ ] docs/RUN_REPORT.md 由实际 run 结果生成，不存在未经执行却标记为成功的步骤。
- [ ] 对未验证项目明确标记 not_tested，不写成已完成。
7. 本地 Agent 必须输出的报告格式
修复工作开始前，先生成 docs/REVIEW_RECHECK.md，逐项填写：
ID	本报告判断	本地复核结果	证据/命令	决定	对应测试


每个 P1/P2 必须有以下结论之一：confirmed、not_reproducible、partially_confirmed、needs_user_decision。对 not_reproducible 必须解释当前代码为何不成立，不可直接删掉发现。
随后再创建 docs/REMEDIATION_PLAN.md。不要一次性重写整个项目；按 Task A → B → C → D → E 顺序，一次修复一个可验证的切片。每个切片完成后先运行对应测试，再继续下一个。
未经用户明确授权，不要对公开仓库执行强制推送、Git 历史重写、删除用户数据或切换到收费 API。
8. 审查依据（上游文件链接）
- 仓库主页与 README：https://github.com/Kylin-Guo/novel-to-tavern
- CLI：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/src/novel_to_tavern/cli.py
- 提取 Schema：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/src/novel_to_tavern/extract/schema.py
- 提取提示词：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/src/novel_to_tavern/extract/prompts.py
- 证据定位：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/src/novel_to_tavern/extract/evidence.py
- 提取 Runner：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/src/novel_to_tavern/extract/runner.py
- 语义校验 Schema：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/src/novel_to_tavern/verify/schema.py
- 导出 Builder：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/src/novel_to_tavern/export/builder.py
- 导出 Runner：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/src/novel_to_tavern/export/runner.py
- 配置模型：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/src/novel_to_tavern/config.py
- 包元数据：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/pyproject.toml
- 格式兼容说明：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/docs/FORMAT_COMPATIBILITY.md
- 运行报告：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/docs/RUN_REPORT.md
- Tavo 导入检查：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/docs/TAVO_IMPORT_CHECKLIST.md
- 示例导出说明：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/exports/README.md
- 示例卡（请先检查分发权利）：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/exports/%E5%A4%A9%E4%B9%8B%E7%82%BD/world_simulator_v2.json
- 许可证：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/LICENSE
- NOTICE：https://github.com/Kylin-Guo/novel-to-tavern/blob/master/NOTICE.md
最终判断
项目架构和开发方向是值得继续的，尤其是结构化中间层、来源追溯、世界书与角色卡分离生成，以及以 Tavo 为最终运行目标的选择。当前首要问题不是再增加功能，而是确保“严格章节导出”真的严格且能运行、事实默认值不会污染 canon、证据定位与语义校验不过度宣称可靠，以及公共样例和包许可证元数据没有歧义。
Agent 应先在本地核实上述问题，再按优先级修复。不要先重写架构，也不要把本报告的静态发现未经测试就改成代码。
