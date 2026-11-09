# CLIP 英文叠字攻击与 OCR 修复实验

本程序只计算真实模型结果，不包含预填实验数字。默认模型为 `openai/clip-vit-base-patch32`。建议先跑单元测试和小样本，再启动完整实验。顶层无第三方库导入，`python experiment.py --help` 在依赖尚未安装时也可运行。

## 运行

在项目目录创建独立环境：`py -3.12 -m venv .venv`，然后执行 `.venv\Scripts\python.exe -m pip install -r requirements-lock.txt`。锁定文件由本项目实际运行环境导出。所有模型与数据首次使用需要网络下载，不需要API密钥或付费服务。PowerShell：

```powershell
.venv\Scripts\python.exe experiment.py --help
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe experiment.py --limit 2 --output outputs/smoke
.venv\Scripts\python.exe experiment.py --full --output outputs/full
.venv\Scripts\python.exe experiment.py --full --sensitivity --output outputs/full_sensitivity
```

`--limit` 是**每类源图张数**，范围 2–50，默认2，共20源图，产生100种图像条件与500行方法结果（缓存可去重）。不是总数。CPU批量默认8且禁止超过8；线程默认4，低配可设 `--threads 2 --batch-size 4`。完整实验会耗时，请先确认 smoke 正常。`--device cuda` 可选择可用GPU。`--font PATH` 可显式指定英文TrueType字体。

数据目录默认 `cache/data`，与主代理下载脚本共享官方压缩包。CLIP/HuggingFace目录默认 `cache/huggingface`（已有HF_HOME则尊重原值）。支持调用前设置 `HF_ENDPOINT`，未设置时使用官方默认源。默认允许下载数据和模型；数据离线使用 `--no-download`，模型离线同时设置 `HF_HUB_OFFLINE=1`。所有缓存默认放当前工作区 `cache`，可用 `--cache-dir` 修改。

## 设计与严格隔离

- 官方 CIFAR10 **test** 数据集，每类用 `seed+类别编号` 固定随机打乱，取前50：前10开发、后40测试，完整共500。smoke按固定开发/测试区域取子集，不会导致同一图由开发变测试。选中ID保存到 `selection.json`。
- 先将原图 bicubic resize 到224×224，再在底部叠英文文字（32px、白底黑字）。wrong目标从其他9类确定性随机选择。correct使用真类，neutral使用object，block使用与wrong完全相同矩形的白色遮挡，clean不叠字。实验共五个控制条件。neutral的object是具有弱语义、但非CIFAR10类别名的词，不将其描述为完全无关语义。
- CLIP统一使用10个 `a photo of a {class}.` 文本提示，原始logits全部先softmax，再做概率融合或JS计算，不混合不同标度。
- 比较 original、repair、fixed_fusion（alpha=0.5）、js_gate、oracle。门控规则为JS大于阈值时使用融合概率；否则保留原概率。阈值和alpha仅在开发集上按平均准确率网格搜索，冻结后用于测试。平分时优先少干预，再优先较小融合权重。完整开发集每个条件等量，未使用测试标签挑参数。
- 实际repair只接收RapidOCR检测框，OCR文本内容不用于分类。框裁剪到图像内并扩2px，联合区域外留12px上下文，OpenCV TELEA半径3修复。空检测保持原样。检测结果、置信度、框和修复图均缓存。oracle单独使用已知叠字/遮挡矩形修复，仅为诊断而非可部署防御，也不保证优于OCR。
- 原始白底文字范围记录在逐样本结果中。检测框通常只能覆盖字形而非全部白底，因此实际修复与oracle本就不同，此差异会作为真实失败案例展示。
- `--position-sensitivity` 在每类固定前5张测试图（完整运行共50；smoke不足则全部）上增加32px wrong文字的top/center/bottom位置敏感性，使用冻结门控。可与字号敏感性同时启用。
- 可选字号敏感性 `--sensitivity` 在每类固定前5张测试图（smoke不足则全部）上评估wrong字体20/32/44，复用已冻结门控，不参与调参。字体过宽时按实际可见图像边界裁剪，记录可见框。

## 统计、缓存与输出

`samples.csv` 包含开发/测试标志、源ID、类别、目标、条件、方法、原/修复/oracle logits、预测概率、OCR框、叠字框、JS、预测、正确性、clean基准、图像路径及原始OCR时间。

`summary.json` 只报告测试集：准确率、相对原条件预测翻转、相对clean预测翻转、clean原始正确子集上的targeted ASR，以及按源图配对bootstrap的准确率差和ASR差95%区间。ASR只针对wrong系列，其他条件为null；无符合条件源图时ASR也为null，不记作零。各条件分别重采样源图，同一源图方法保持配对，默认2000次，不做多重比较修正。报告的是样本估计，不表示总体保证。

`parameters.json` / `environment.json` / `gate_tuning.json` 分别记录参数、版本环境、完整开发集网格结果。`summary.json`记录总墙钟、模型加载、未缓存CLIP推理时间和命中次数。逐行OCR时间是首次计算的缓存时间，**不能**当本次运行延迟；共享批次不虚构各方法端到端时间。

`accuracy_asr.png` / `js_distribution.png` 分析准确率、ASR及JS分布；`cases_success.png` 和 `cases_failure.png` 展示原始clean正确且攻击确实命中目标的实际案例，门控回到真类为成功，否则失败。某类没有真实案例则不生成该类图，`case_manifest.json`明确记录空集合，不伪造。

缓存按图像字节和实现版本指纹寻址，CLIP额外带模型名和可用提交指纹；每批完成就逐图保存logits，OCR逐图写PNG和JSON，重跑可从缓存恢复。最终CSV、图表和统计会重新生成。为不同参数运行使用不同 `--output` 目录，缓存目录可共享。更新依赖/处理器或实现后建议清除相应缓存或修改VERSION，避免跨实现复用。中断不会自动写完成状态；异常记录 `last_error.json`，仅完成后生成 `summary.json`。不要把旧输出目录中的历史summary误当本次已完成，建议每次独立输出目录。

单元测试不下载模型/数据、不推理，核心选择、split隔离、softmax、JS、目标标签、裁框、调参隔离均用标准库测试；图像/统计测试在相应依赖尚未安装时明确跳过。

## 一键运行与单张图片演示

`./run_project.ps1` 运行测试、冒烟实验及结果核验；`./run_project.ps1 -Full` 运行完整实验及字号、位置敏感性。

完成正式实验后，运行 `.venv\Scripts\python.exe predict_image.py 你的图片.png`，即可用冻结门控演示防御，输出原始/修复/防御预测与修复图。该入口只接收图片，不需要已知攻击框或真实类别。它仅在CIFAR-10十个类别中选择，不能当通用识图系统，softmax数值也不是校准后的正确概率。

`python verify_results.py outputs/full` 独立重算准确率、目标ASR与置信区间，核对划分、完整性、概率融合和开发调参，并绑定输入文件SHA256。先运行 `python analysis_figures.py` 再运行 `python build_paper.py --results outputs/full` 生成中文论文及详细分析，需另外安装python-docx；正文数值读取真实运行文件，缺失正式实验时拒绝生成。请在项目根目录执行。

## 已完成的真实运行与结论

正式实验：100开发图、400独立测试图；主五条件及50图字号/位置敏感性，共14000条方法预测。全部19项单元测试通过，正式CSV/summary通过增强核验。运行环境为Windows、Python 3.12.7、CPU，模型提交版本见logs/resource_verification.json。

错误文字条件下：原始准确率11.75%，仅OCR修复82.00%，固定融合57.00%，JS门控80.25%；clean原始与门控均83.00%。目标ASR分母332张clean原始正确图，原始85.84%，修复0.60%，门控3.61%。门控不优于最简单修复：wrong准确率差为−1.75个百分点，配对95%区间约[−3.01,−0.50]个百分点。门控在正确标签和非类别词条件下保留更多原图信息，但也保留错误文字证据。不要将方案包装成所有场景都更好。

正式运行总墙钟约939秒，包含缓存复用、统计和绘图，不含此前的依赖与数据下载时间，不是从零部署耗时或各方法独立延迟。结果适用于受控低分辨率放大图与英文叠字，不能直接泛化到真实高清/中文场景。

## 交付入口

- `deliverables/analysis.md`：完整指标、配对统计与局限分析。
- `outputs/full/samples.csv`、`summary.json`、`verification.json`：逐样本、汇总及哈希绑定核验。
- `logs/full.txt`、`unit_tests.txt`、`demo.txt`：实际运行证据。


不重新分发模型权重或CIFAR原始压缩包。包内含实验生成图与修复图用于核验；原始数据及模型来源见references.md和下载脚本。
