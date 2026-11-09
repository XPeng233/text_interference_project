# 完整实验分析

本文档只使用已完成的真实实验输出。最终PDF已导出并确认包含参考文献共四页，文件签名与Word/PDF哈希记录于document_validation.json。内容与结构检查通过；视觉检查未完成。

## 主要结论与机制解释

匹配白块条件的原始准确率为83.75%，接近clean的83.00%，但错误类别文字使其降至11.75%，说明这一设置的主要破坏来自类别语义而不只是匹配矩形遮挡。正确类别文字达到99.75%，属于直接提供标签线索，不能作为自然视觉能力提升的证据。

仅OCR修复在wrong达到82.00%，门控为80.25%，相差−1.75个百分点。门控保留原图概率也会保留错误文字目标证据。开发目标为五条件平均，而不是单独最小化攻击成功率，因此门控在correct较repair高9个百分点、neutral高1.75个百分点，却在wrong较弱。此结果支持报告性能取舍，而非宣称门控全面优越。

字号子集中，原始准确率为14%/6%/8%（20/32/44px），没有严格单调关系；门控为84%/82%/82%。位置子集原始为10%/8%/6%（顶/中/底），门控为80%/80%/82%。每个条件只有同一组50张图，微小差异不能解释为普遍位置规律；主实验与子集样本组成不同，也不应直接比较两者的32px准确率。


## 实验设置

```json
{
  "limit": 2,
  "full": true,
  "output": "outputs\\full",
  "data_dir": "cache\\data",
  "cache_dir": "cache",
  "model": "openai/clip-vit-base-patch32",
  "device": "cpu",
  "batch_size": 8,
  "threads": 4,
  "seed": 2026,
  "font": null,
  "bootstrap": 2000,
  "sensitivity": true,
  "position_sensitivity": true,
  "no_download": false,
  "font_resolved": "C:/Windows/Fonts/arial.ttf",
  "conditions": [
    "clean",
    "correct",
    "wrong",
    "neutral",
    "block"
  ],
  "version": "ocr-clip-v1",
  "condition_note": "Five controlled conditions; neutral object is weakly semantic but not a CIFAR10 class name.",
  "fixed_fusion_alpha": 0.5
}
```

## 冻结门控

```json
{
  "threshold": 0.01,
  "alpha": 0.75,
  "accuracy": 0.862,
  "interventions": 212
}
```

## 完整测试指标

| 条件 | 方法 | n | 准确率 | 95% CI | ASR | ASR分母 | ASR 95% CI | 相对原条件翻转 |
|---|---|---:|---:|---|---:|---:|---|---:|
| clean | 原始分类 | 400 | 83.0% | [79.2, 86.5] | 不适用 | 0 | 不可估计 | 0.0% |
| clean | 仅OCR修复 | 400 | 82.8% | [79.0, 86.2] | 不适用 | 0 | 不可估计 | 1.2% |
| clean | 固定融合 | 400 | 83.0% | [79.2, 86.5] | 不适用 | 0 | 不可估计 | 0.0% |
| clean | JS门控融合 | 400 | 83.0% | [79.2, 86.5] | 不适用 | 0 | 不可估计 | 0.5% |
| clean | Oracle诊断 | 400 | 83.0% | [79.2, 86.5] | 不适用 | 0 | 不可估计 | 0.0% |
| correct | 原始分类 | 400 | 99.8% | [99.2, 100.0] | 不适用 | 0 | 不可估计 | 0.0% |
| correct | 仅OCR修复 | 400 | 82.8% | [79.0, 86.2] | 不适用 | 0 | 不可估计 | 17.0% |
| correct | 固定融合 | 400 | 98.8% | [97.5, 99.8] | 不适用 | 0 | 不可估计 | 1.0% |
| correct | JS门控融合 | 400 | 91.8% | [89.0, 94.2] | 不适用 | 0 | 不可估计 | 8.0% |
| correct | Oracle诊断 | 400 | 82.2% | [78.5, 85.8] | 不适用 | 0 | 不可估计 | 17.5% |
| wrong | 原始分类 | 400 | 11.8% | [8.8, 15.0] | 85.8% | 332 | [81.9, 89.5] | 0.0% |
| wrong | 仅OCR修复 | 400 | 82.0% | [78.2, 85.8] | 0.6% | 332 | [0.0, 1.5] | 85.8% |
| wrong | 固定融合 | 400 | 57.0% | [52.2, 61.8] | 31.3% | 332 | [26.5, 36.1] | 47.2% |
| wrong | JS门控融合 | 400 | 80.2% | [76.2, 84.0] | 3.6% | 332 | [1.8, 5.7] | 79.2% |
| wrong | Oracle诊断 | 400 | 81.5% | [77.8, 85.0] | 0.6% | 332 | [0.0, 1.5] | 85.5% |
| neutral | 原始分类 | 400 | 84.0% | [80.5, 87.2] | 不适用 | 0 | 不可估计 | 0.0% |
| neutral | 仅OCR修复 | 400 | 81.5% | [77.5, 85.2] | 不适用 | 0 | 不可估计 | 11.2% |
| neutral | 固定融合 | 400 | 84.5% | [80.8, 87.8] | 不适用 | 0 | 不可估计 | 4.5% |
| neutral | JS门控融合 | 400 | 83.2% | [79.5, 86.8] | 不适用 | 0 | 不可估计 | 8.2% |
| neutral | Oracle诊断 | 400 | 81.0% | [77.0, 84.5] | 不适用 | 0 | 不可估计 | 12.5% |
| block | 原始分类 | 400 | 83.8% | [80.0, 87.2] | 不适用 | 0 | 不可估计 | 0.0% |
| block | 仅OCR修复 | 400 | 83.2% | [79.5, 86.8] | 不适用 | 0 | 不可估计 | 1.2% |
| block | 固定融合 | 400 | 84.0% | [80.2, 87.5] | 不适用 | 0 | 不可估计 | 0.2% |
| block | JS门控融合 | 400 | 83.5% | [79.5, 87.0] | 不适用 | 0 | 不可估计 | 0.8% |
| block | Oracle诊断 | 400 | 81.5% | [77.8, 85.0] | 不适用 | 0 | 不可估计 | 9.2% |
| wrong_font20 | 原始分类 | 50 | 14.0% | [6.0, 24.0] | 82.9% | 41 | [70.7, 92.7] | 0.0% |
| wrong_font20 | 仅OCR修复 | 50 | 88.0% | [78.0, 96.0] | 2.4% | 41 | [0.0, 7.3] | 84.0% |
| wrong_font20 | 固定融合 | 50 | 66.0% | [52.0, 78.0] | 19.5% | 41 | [7.3, 31.8] | 58.0% |
| wrong_font20 | JS门控融合 | 50 | 84.0% | [74.0, 94.0] | 2.4% | 41 | [0.0, 7.3] | 80.0% |
| wrong_font20 | Oracle诊断 | 50 | 86.0% | [76.0, 94.0] | 2.4% | 41 | [0.0, 7.3] | 84.0% |
| wrong_font32 | 原始分类 | 50 | 6.0% | [0.0, 14.0] | 92.7% | 41 | [82.9, 100.0] | 0.0% |
| wrong_font32 | 仅OCR修复 | 50 | 84.0% | [72.0, 94.0] | 2.4% | 41 | [0.0, 7.3] | 90.0% |
| wrong_font32 | 固定融合 | 50 | 66.0% | [52.0, 78.0] | 19.5% | 41 | [7.3, 31.7] | 66.0% |
| wrong_font32 | JS门控融合 | 50 | 82.0% | [70.0, 92.0] | 2.4% | 41 | [0.0, 7.3] | 88.0% |
| wrong_font32 | Oracle诊断 | 50 | 82.0% | [70.0, 92.0] | 2.4% | 41 | [0.0, 7.3] | 90.0% |
| wrong_font44 | 原始分类 | 50 | 8.0% | [2.0, 16.0] | 90.2% | 41 | [80.5, 97.6] | 0.0% |
| wrong_font44 | 仅OCR修复 | 50 | 84.0% | [74.0, 94.0] | 0.0% | 41 | [0.0, 0.0] | 90.0% |
| wrong_font44 | 固定融合 | 50 | 56.0% | [42.0, 70.0] | 31.7% | 41 | [17.1, 46.3] | 54.0% |
| wrong_font44 | JS门控融合 | 50 | 82.0% | [70.0, 92.0] | 0.0% | 41 | [0.0, 0.0] | 88.0% |
| wrong_font44 | Oracle诊断 | 50 | 82.0% | [70.0, 92.0] | 0.0% | 41 | [0.0, 0.0] | 90.0% |
| wrong_position_top | 原始分类 | 50 | 10.0% | [4.0, 18.0] | 87.8% | 41 | [78.0, 97.6] | 0.0% |
| wrong_position_top | 仅OCR修复 | 50 | 84.0% | [74.0, 94.0] | 0.0% | 41 | [0.0, 0.0] | 88.0% |
| wrong_position_top | 固定融合 | 50 | 54.0% | [40.0, 68.0] | 31.7% | 41 | [17.1, 46.3] | 50.0% |
| wrong_position_top | JS门控融合 | 50 | 80.0% | [68.0, 90.0] | 2.4% | 41 | [0.0, 7.3] | 82.0% |
| wrong_position_top | Oracle诊断 | 50 | 82.0% | [70.0, 92.0] | 0.0% | 41 | [0.0, 0.0] | 88.0% |
| wrong_position_center | 原始分类 | 50 | 8.0% | [2.0, 16.0] | 90.2% | 41 | [80.5, 97.6] | 0.0% |
| wrong_position_center | 仅OCR修复 | 50 | 80.0% | [68.0, 90.0] | 0.0% | 41 | [0.0, 0.0] | 90.0% |
| wrong_position_center | 固定融合 | 50 | 52.0% | [38.0, 66.0] | 36.6% | 41 | [22.0, 51.2] | 48.0% |
| wrong_position_center | JS门控融合 | 50 | 80.0% | [68.0, 90.0] | 2.4% | 41 | [0.0, 7.3] | 84.0% |
| wrong_position_center | Oracle诊断 | 50 | 80.0% | [68.0, 90.0] | 0.0% | 41 | [0.0, 0.0] | 90.0% |
| wrong_position_bottom | 原始分类 | 50 | 6.0% | [0.0, 14.0] | 92.7% | 41 | [82.9, 100.0] | 0.0% |
| wrong_position_bottom | 仅OCR修复 | 50 | 84.0% | [72.0, 94.0] | 2.4% | 41 | [0.0, 7.3] | 90.0% |
| wrong_position_bottom | 固定融合 | 50 | 66.0% | [52.0, 78.0] | 19.5% | 41 | [7.3, 31.7] | 66.0% |
| wrong_position_bottom | JS门控融合 | 50 | 82.0% | [70.0, 92.0] | 2.4% | 41 | [0.0, 7.3] | 88.0% |
| wrong_position_bottom | Oracle诊断 | 50 | 82.0% | [70.0, 92.0] | 2.4% | 41 | [0.0, 7.3] | 90.0% |

## 与最简单仅OCR修复的直接配对比较

差值=JS门控−repair；准确率差越高越好，ASR差越低越好。下表CI单位为百分点，按同源图保持配对，不使用独立两组近似。

| 条件 | 准确率差 | 配对95% CI | ASR差 | 配对95% CI |
|---|---:|---|---:|---|
| clean | +0.2个百分点 | [0.0, 1.0] | 不适用 | 不可估计 |
| correct | +9.0个百分点 | [6.2, 11.8] | 不适用 | 不可估计 |
| wrong | -1.8个百分点 | [-3.0, -0.5] | +3.0个百分点 | [1.2, 5.1] |
| neutral | +1.8个百分点 | [0.5, 3.2] | 不适用 | 不可估计 |
| block | +0.2个百分点 | [0.0, 1.0] | 不适用 | 不可估计 |

区间未跨零，但这仅反映本采样与设定下的配对差异，并非跨数据集保证。

## 检测与门控诊断

wrong样本中检测到OCR框：400/400；门控触发：399/400。

ASR只在clean原始正确子集定义，防御后变成其他错误类别并不等于恢复正确。因此ASR、准确率与clean代价必须共同判断。无多重比较校正，CI不能解释成方法有95%概率优越。

## 实际案例

```json
{
  "definition": "Originally clean-correct and wrong-overlay target hit; success means gated prediction recovers true class.",
  "examples": {
    "success": [
      4037,
      9273,
      7863,
      539
    ],
    "failure": [
      5074,
      9866,
      6399,
      7071
    ]
  },
  "note": "Empty groups have no figure; no examples are fabricated."
}
```

## 时间与缓存

```json
{
  "wall_seconds": 939.0528252999975,
  "clip_load_seconds": 0.5684400999998616,
  "clip_uncached_inference_seconds": 441.7610528999321,
  "clip_cache_hits": 221,
  "clip_cache_misses": 5911,
  "ocr_cache_hits": 201,
  "ocr_cache_misses": 2599,
  "ocr_uncached_compute_seconds": 380.59150189988577,
  "note": "Per-row OCR seconds are original cached compute duration, not current-run latency. Wall time includes setup, downloads, plots and statistics. Shared inference means method-specific end-to-end timing is not estimated."
}
```

缓存中的逐行OCR时间是初次计算耗时，不是当前运行时延。共享推理不支持从总时间推算各方法独立部署速度。

## 可视化

![测试准确率与ASR](<../outputs/full/accuracy_asr.png>)

![JS分布](<../outputs/full/js_distribution.png>)

![字号与位置敏感性](<../outputs/full/sensitivity.png>)

## 局限

低分辨率图像放大、固定英文字体与白底叠加、单骨干和单提示模板限制外部效度。OCR漏检/误检与修复纹理可共同影响结果；oracle不是可部署方法。开发调参严格隔离，但不能排除小开发集过拟合。案例选择仅用于解释，不是总体效应估计。

## 核验参考资料（原文保留）

# 已核验来源

- Radford A, Kim J W, Hallacy C, et al. Learning Transferable Visual Models From Natural Language Supervision. ICML, 2021. https://arxiv.org/abs/2103.00020 （已核验标题、作者、年份；CLIP原始论文）
- Goh G, Cammarata N, Voss C, et al. Multimodal Neurons in Artificial Neural Networks. Distill, 2021. DOI:10.23915/distill.00030. https://distill.pub/2021/multimodal-neurons/ （已核验标题、作者、年份与typographical attacks相关章节描述；不能声称文字攻击是本项目首次发现）
- Krizhevsky A. Learning Multiple Layers of Features from Tiny Images. Technical report, 2009. 官方数据介绍 https://cave.cs.toronto.edu/kriz/cifar.html ，报告 https://cave.cs.toronto.edu/kriz/learning-features-2009-TR.pdf 。官方页面确认CIFAR-10测试集10000张、每类1000张、32×32彩色图像。数据许可未在该页面明确指定，项目不重新分发原始数据，并保留来源及引用。

- Telea A. An Image Inpainting Technique Based on the Fast Marching Method. Journal of Graphics Tools, 9(1), 2004:23–34. https://docs.opencv.org/4.13.0/df/d3d/tutorial_py_inpainting.html （OpenCV官方教程核验作者、题目、年份与卷页，本文修复使用INPAINT_TELEA）
- RapidAI. RapidOCR [Software]. https://github.com/RapidAI/RapidOCR （实现来源；项目运行时版本另见environment.json，勿将当前仓库版本等同于已安装包）

核验日期：2026-11-09。后续实现依赖的官方来源与许可另记录在项目说明中。
