"""Build a four-page manuscript and full analysis from real completed experiment outputs.

Run with a Python environment containing python-docx, numpy and Pillow.
This script never runs inference and refuses incomplete/missing full-experiment data.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import re

METHOD_NAMES = {'original': '原始分类', 'repair': '仅OCR修复', 'fixed_fusion': '固定融合', 'js_gate': 'JS门控融合', 'oracle': 'Oracle诊断'}
CONDITIONS = ['clean', 'correct', 'wrong', 'neutral', 'block']


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def truth(value):
    return str(value).lower() in ['true', '1']


def pct(value):
    return '不适用' if value is None else f'{100 * float(value):.1f}%'


def ci(value):
    return '不可估计' if value is None else f'[{100 * value[0]:.1f}, {100 * value[1]:.1f}]'


def signed(value):
    return f'{100 * value:+.1f}个百分点'


def paired_ci(values, seed, count):
    import numpy as np
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = []
    for start in range(0, count, 128):
        ids = rng.integers(0, len(arr), (min(128, count-start), len(arr)))
        means.extend(arr[ids].mean(axis=1).tolist())
    return [float(x) for x in np.percentile(means, [2.5, 97.5])]


def load_results(root):
    summary = read_json(root / 'summary.json')
    manifest = read_json(root / 'case_manifest.json')
    with (root / 'samples.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if summary.get('status') != 'complete' or not rows:
        raise ValueError('Require completed summary and nonempty samples')
    source_split = {}
    for row in rows:
        sid = int(row['sample_id'])
        if sid in source_split and source_split[sid] != row['split']:
            raise ValueError('Development/test leakage detected')
        source_split[sid] = row['split']
    if sum(v == 'dev' for v in source_split.values()) != 100 or sum(v == 'test' for v in source_split.values()) != 400:
        raise ValueError('Paper requires full experiment: 100 development and 400 held-out test sources')
    metrics = {(m['condition'], m['method']): m for m in summary['metrics']}
    index = {}
    for row in rows:
        key = (row['split'], int(row['sample_id']), row['condition'], row['method'])
        if key in index:
            raise ValueError(f'Duplicate sample-method record: {key}')
        index[key] = row
    for condition in CONDITIONS:
        for method in METHOD_NAMES:
            m = metrics[(condition, method)]
            actual = [r for r in rows if r['split'] == 'test' and r['condition'] == condition and r['method'] == method]
            if m['n'] != 400 or len(actual) != 400:
                raise ValueError(f'Incomplete full metric: {condition}/{method}')
            accuracy = sum(truth(r['correct']) for r in actual) / len(actual)
            if abs(accuracy - m['accuracy']) > 1e-9:
                raise ValueError('CSV and summary accuracy disagree')
    return summary, manifest, rows, metrics, index


def compare(rows, condition, method, reference, seed, boots):
    chosen = [r for r in rows if r['split'] == 'test' and r['condition'] == condition]
    baseline = {int(r['sample_id']): r for r in chosen if r['method'] == reference}
    target = [r for r in chosen if r['method'] == method]
    accuracy = [int(truth(r['correct'])) - int(truth(baseline[int(r['sample_id'])]['correct'])) for r in target]
    eligible = [r for r in target if truth(r['clean_correct']) and condition.startswith('wrong')]
    asr = [int(r['pred'] == r['target']) - int(baseline[int(r['sample_id'])]['pred'] == r['target']) for r in eligible]
    return {'condition': condition, 'method': method, 'reference': reference,
            'accuracy_delta': sum(accuracy) / len(accuracy), 'accuracy_ci95': paired_ci(accuracy, seed, boots),
            'asr_delta': sum(asr) / len(asr) if asr else None, 'asr_ci95': paired_ci(asr, seed, boots),
            'paired_n': len(accuracy), 'asr_n': len(asr)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=Path('outputs/full'))
    parser.add_argument('--output', type=Path, default=Path('deliverables'))
    parser.add_argument('--references', type=Path, default=Path('references.md'))
    args = parser.parse_args()
    from verify_results import verify
    verify(args.results, write=True)
    summary, manifest, rows, metrics, index = load_results(args.results)
    references_text = args.references.read_text(encoding='utf-8')
    references = [re.sub(r'（已核验.*?）', '', line[2:]).strip() for line in references_text.splitlines() if line.startswith('- ')]
    if not references:
        raise ValueError('No references found in references.md')
    params, gate = summary['parameters'], summary['gate']
    seed, boots = int(params.get('seed', 2026)), int(params.get('bootstrap', 2000))
    comparisons = [compare(rows, c, 'js_gate', 'repair', seed, boots) for c in CONDITIONS]
    comp = next(c for c in comparisons if c['condition'] == 'wrong')
    original, repair, gated = [metrics[('wrong', m)] for m in ['original', 'repair', 'js_gate']]
    clean_gated = metrics[('clean', 'js_gate')]
    clean_original = metrics[('clean', 'original')]
    wrong_rows = [r for r in rows if r['split'] == 'test' and r['condition'] == 'wrong' and r['method'] == 'original']
    detected = sum(bool(json.loads(r['ocr_boxes'])) for r in wrong_rows)
    active = sum(truth(r['gate_active']) for r in wrong_rows)
    direction = '提升' if comp['accuracy_delta'] > 0 else ('下降' if comp['accuracy_delta'] < 0 else '持平')
    uncertainty = ('区间跨越零，不能据此确认差异稳定存在。' if comp['accuracy_ci95'][0] <= 0 <= comp['accuracy_ci95'][1]
                   else '区间未跨零，但这仅反映本采样与设定下的配对差异，并非跨数据集保证。')
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    from docx import Document
    from docx.shared import Cm, Pt
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin = sec.bottom_margin = sec.left_margin = sec.right_margin = Cm(1.8)
    sec.header_distance = sec.footer_distance = Cm(.7)
    for name in ['Normal', 'Body Text', 'Caption', 'Heading 1', 'Heading 2']:
        style = doc.styles[name]
        style.font.name = '宋体'
        style._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), '宋体')
        style.font.size = Pt(10.5 if name not in ['Heading 1', 'Heading 2'] else 11)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.space_before = Pt(0)
        style.paragraph_format.line_spacing = 1.08
    doc.styles['Normal'].paragraph_format.widow_control = True
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = OxmlElement('w:fldSimple'); field.set(qn('w:instr'), 'PAGE'); footer._p.append(field)

    def p(text, bold=False):
        para = doc.add_paragraph()
        run = para.add_run(text); run.bold = bold
        return para

    def heading(text):
        doc.add_heading(text, level=1)

    def figure(path, max_width=16.5, max_height=7.5):
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        scale = min(max_width / w, max_height / h)
        para = doc.add_paragraph(); para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.add_run().add_picture(str(path), width=Cm(w*scale), height=Cm(h*scale))
        para.paragraph_format.space_after = Pt(2)

    # Explicit page 1: title, abstract, introduction and method.
    title = p('CLIP叠字干扰下的OCR修复与开发集门控融合：一项可复现实验', True)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.runs[0].font.size = Pt(15)
    heading('摘要')
    p(f'视觉—语言模型可能将图中类别文字误作物体证据。本文在CIFAR-10官方测试集均衡抽取500张图，按每类10张开发、40张测试严格隔离，比较原始分类、OCR修复、固定融合及开发集选择的JS门控融合，并以已知文字框修复作诊断。在错误类别叠字条件下，原始与门控准确率分别为{pct(original["accuracy"])}和{pct(gated["accuracy"])}；clean原始正确子集的目标攻击成功率分别为{pct(original["targeted_asr"])}和{pct(gated["targeted_asr"])}。相对最简单的OCR修复，门控准确率变化为{signed(comp["accuracy_delta"])}，配对95%区间为{ci(comp["accuracy_ci95"])}个百分点。本文报告效果与失败边界，不将既有文字攻击现象或通用OCR修复组合宣称为首创。')
    p('关键词：CLIP；文字叠加；OCR；图像修复；配对bootstrap')
    heading('1 引言')
    p('CLIP通过图文对比学习建立共享表示[1]，文字与视觉概念的关联同时可能使图中单词影响零样本分类。既有工作已讨论多模态神经元与文字攻击[2]。本实验关注一个受控、可审计的问题：不用已知攻击框，仅靠OCR定位后修复，能否降低目标文字干扰；若修复会损伤视觉证据，开发集门控是否优于始终修复？')
    heading('2 方法')
    p('每图先缩放到224×224，再叠加英文白底黑字。clean无叠加；correct叠真类；wrong叠随机其他类别；neutral叠object，属于弱语义但非类别词；block在wrong相同矩形画白块。五条件用于分离类别语义与区域遮挡，不将neutral视为语义完全无关对照。')
    p('令z、zᵣ为原图与OCR修复图的十类CLIP logits，统一转为p=softmax(z)、q=softmax(zᵣ)。固定融合f=(1−α)p+αq，α=0.5。令m=(p+q)/2，D_JS(p,q)=[KL(p‖m)+KL(q‖m)]/2。门控在D_JS>τ时输出融合概率，否则输出p，最终取最大概率类别。')
    p(f'仅开发集网格选择τ与α，以五条件平均准确率最大化；平分优先少干预、小α。冻结参数为τ={gate["threshold"]:g}、α={gate["alpha"]:g}。实际修复仅使用RapidOCR[5]框，裁边扩2像素后对局部区域进行TELEA修复[4]。oracle仅用已知叠字矩形，作为不可部署诊断，不参与门控。')

    doc.add_page_break()
    heading('3 实验设置与主要结果')
    p(f'使用{params.get("model", "openai/clip-vit-base-patch32")}，类别提示统一为“a photo of a {{class}}.”。CIFAR-10来源见[3]。随机种子为{seed}，每类固定随机50张；100张开发图与400张测试图互斥，所有主表均为测试结果。每类40张测试图对应每条件400个独立源图。CPU批量上限8，逐图缓存logits、OCR与修复图以便断点续跑。')
    p('表1 五条件测试准确率（%）；末列为wrong目标攻击成功率（ASR）。ASR分母固定为clean原始分类正确的源图，不因防御方法改变；非目标攻击条件不定义ASR。')
    table = doc.add_table(rows=1, cols=7); table.style = 'Table Grid'
    headers = ['方法', 'clean', 'correct', 'wrong', 'neutral', 'block', 'wrong ASR']
    for cell, text in zip(table.rows[0].cells, headers): cell.text = text
    for method in METHOD_NAMES:
        cells = table.add_row().cells
        values = [METHOD_NAMES[method]] + [pct(metrics[(c, method)]['accuracy']) for c in CONDITIONS] + [pct(metrics[('wrong', method)]['targeted_asr'])]
        for cell, text in zip(cells, values): cell.text = text
    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                para.paragraph_format.space_after = Pt(3)
                for run in para.runs: run.font.size = Pt(10.5)
    heading('3.1 统计口径')
    p(f'准确率覆盖全部测试源图。wrong ASR共有{original["targeted_clean_correct_n"]}个clean原始正确源图，分子为当前预测恰好等于该图指定错误目标的数量；防御后仍错误但不再命中目标会降低ASR，故必须同时查看准确率。区间采用{boots}次源图有放回bootstrap，方法差值在同一源图上配对；每条件在经验混合分布下重采样源图，未固定重采样中的类数；这不等同于分层bootstrap，且未做多重检验修正。')
    p(f'wrong准确率：原始{pct(original["accuracy"])}，仅修复{pct(repair["accuracy"])}，门控{pct(gated["accuracy"])}。门控相对仅修复{direction}，差值{signed(comp["accuracy_delta"])}，95%区间{ci(comp["accuracy_ci95"])}个百分点。{uncertainty}')
    p(f'门控相对仅修复的ASR差值为{signed(comp["asr_delta"]) if comp["asr_delta"] is not None else "不可估计"}，配对区间{ci(comp["asr_ci95"])}个百分点；ASR差为负才代表目标命中减少。clean门控与原始准确率分别为{pct(clean_gated["accuracy"])}与{pct(clean_original["accuracy"])}，其变化揭示防御的非攻击代价。')
    p(f'wrong条件OCR检出至少一个框的样本为{detected}/{len(wrong_rows)}，门控触发为{active}/{len(wrong_rows)}。这些计数并不等价于文字被完整移除：OCR框可能仅覆盖字形，白底与原物体遮挡残留仍可影响分类。')

    doc.add_page_break()
    heading('4 结果分析与实际案例')
    chart = args.results / 'main_results.png'
    if not chart.exists(): raise FileNotFoundError(chart)
    figure(chart, max_height=4.5)
    p('图1 五条件测试准确率；目标ASR见表1。oracle为已知区域诊断，不能当作实际部署防御；修复既可能移除文字，也可能丢失原物体细节。')
    cases = manifest.get('examples', {})
    selected = []
    from PIL import Image, ImageDraw
    for category in ['success', 'failure']:
        ids = cases.get(category, [])
        if not ids:
            continue
        sid = int(ids[0])
        row = index[('test', sid, 'wrong', 'original')]
        gated_row = index[('test', sid, 'wrong', 'js_gate')]
        if not truth(row['clean_correct']) or row['pred'] != row['target']:
            raise ValueError('Case manifest contains a non-successful initial attack')
        if truth(gated_row['correct']) != (category == 'success'):
            raise ValueError('Case category inconsistent with CSV')
        selected.append((category, sid, row, gated_row))
    if selected:
        canvas = Image.new('RGB', (224*3, 248*len(selected)), 'white')
        draw = ImageDraw.Draw(canvas)
        for i, (category, sid, row, gr) in enumerate(selected):
            for j, key in enumerate(['clean_path', 'image_path', 'repair_path']):
                path = Path(row[key].replace('\\', '/'))
                if not path.is_absolute(): path = Path(__file__).resolve().parent / path
                if not path.exists(): raise FileNotFoundError(path)
                with Image.open(path) as image:
                    canvas.paste(image.convert('RGB').resize((224,224)), (224*j,248*i))
            draw.text((4,248*i+227), f'{category} | id={sid} | clean / attacked / OCR repaired', fill='black')
        case_path = output / 'paper_cases.png'; canvas.save(case_path)
        figure(case_path, max_width=14, max_height=9.3)
        descriptions = [f'{"成功" if category == "success" else "失败"}案例ID {sid}：真类{row["label"]}，攻击目标{row["target"]}，门控输出{gr["pred"]}' for category, sid, row, gr in selected]
        p('图2 真实攻击案例，列顺序为clean、叠字图、OCR修复图。'+'；'.join(descriptions)+'。类别编号顺序与实验CLASSES一致；案例仅作机制诊断，不代表总体频率。')
    else:
        p('没有满足“clean正确且wrong命中目标”的可展示案例，因此不绘制或替代生成案例。')
    for category in ['success', 'failure']:
        if not cases.get(category): p(f'{"成功" if category == "success" else "失败"}案例组为空；本实验未虚构该类别图片。')
    p(f'匹配白块的原始准确率为{pct(metrics[("block", "original")]["accuracy"])}，而错误文字仅为{pct(original["accuracy"])}，支持类别文字语义是主要干扰来源，而非相同面积遮挡本身。门控保留了部分原图概率，也保留攻击目标证据，因此wrong下不如仅修复；但correct下门控比仅修复高{signed(metrics[("correct", "js_gate")]["accuracy"]-metrics[("correct", "repair")]["accuracy"])}，体现开发集多条件目标与最强去干扰目标的取舍。正确类别文字直接提供标签，不能作为自然图像识别能力提升的证据。')

    doc.add_page_break()
    heading('5 局限与适用范围')
    p('第一，原始CIFAR图只有32×32，放大后添加的文字相对显著；本结果不能直接外推到自然高清图片、中文、真实路牌或复杂排版。第二，固定字体与区域仅是受控压力测试，不等于面向模型优化的最强自适应攻击；白底遮挡也可能直接破坏视觉信息。第三，OCR误检自然场景文字会使clean图被不必要修复，漏检则保留攻击线索。')
    sensitivity = [m for m in summary['metrics'] if m['condition'].startswith('wrong_') and m['method'] == 'js_gate']
    if sensitivity:
        p('已完成的敏感性子集采用冻结门控，其规模与结果为：'+'；'.join(f'{m["condition"]}，n={m["n"]}，准确率{pct(m["accuracy"])}，ASR {pct(m["targeted_asr"])}' for m in sensitivity)+'。子集较小，只作方向性诊断。')
    else:
        p('本次完成结果中不含独立字号/位置敏感性记录，因此不对这些变化报告数字；可选实验应使用固定测试子集及已冻结门控，不能回流调参。')
    p('第四，本研究只评估一个CLIP骨干、一种文本模板与固定抽样，未覆盖训练随机性或多数据集泛化。bootstrap反映当前源图抽样不确定性，不涵盖模型选择、OCR配置或分布迁移。开发集虽与测试严格分离，但其规模较小，门控可能过拟合开发条件。第五，oracle知道攻击区域，不能公平代表实际防御能力；它只能诊断定位与修复的潜在影响。')
    heading('6 结论')
    p(f'在本实验的错误标签叠字条件下，JS门控的准确率为{pct(gated["accuracy"])}、目标ASR为{pct(gated["targeted_asr"])}；相对始终OCR修复的准确率差为{signed(comp["accuracy_delta"])}。{uncertainty}因此应同时报告攻击缓解、clean代价与失败案例，而不能仅凭ASR下降宣称防御有效。该实现的价值在于可复现的数据划分、实际OCR框约束及配对评估，不在于提出未经证实的首创主张。')
    heading('参考文献')
    for i, reference in enumerate(references,1):
        # Keep citations compact; full verified text is preserved in analysis.md.
        short = reference.split(' （')[0]
        if i == 3:
            short = 'Krizhevsky A. Learning Multiple Layers of Features from Tiny Images. Technical report, 2009. https://cave.cs.toronto.edu/kriz/cifar.html'
        p(f'[{i}] {short}')
    p('复现说明：源代码、逐样本CSV、参数/环境日志和完整分析随项目保存。论文数值均由完成的实验输出动态读取；插图只来自实际缓存图像。')
    doc_path = output / 'paper.docx'
    doc.save(doc_path)
    # Content validation only; rendering/pagination verification belongs to the parent.
    reopened = Document(doc_path)
    if len(reopened.tables) != 1 or not any('参考文献' in para.text for para in reopened.paragraphs):
        raise RuntimeError('DOCX content verification failed')

    lines = ['# 完整实验分析', '', '本文档只使用已完成的真实实验输出。论文显式分页为四个内容块；最终实际页数仍需Word/LibreOffice渲染核验。', '',
             '## 实验设置', '', '```json', json.dumps(params, ensure_ascii=False, indent=2), '```', '',
             '## 冻结门控', '', '```json', json.dumps(gate, ensure_ascii=False, indent=2), '```', '',
             '## 完整测试指标', '', '| 条件 | 方法 | n | 准确率 | 95% CI | ASR | ASR分母 | ASR 95% CI | 相对原条件翻转 |',
             '|---|---|---:|---:|---|---:|---:|---|---:|']
    for m in summary['metrics']:
        lines.append(f'| {m["condition"]} | {METHOD_NAMES[m["method"]]} | {m["n"]} | {pct(m["accuracy"])} | {ci(m["accuracy_ci95"])} | {pct(m["targeted_asr"])} | {m["targeted_clean_correct_n"]} | {ci(m["targeted_asr_ci95"])} | {pct(m["flip_vs_original"])} |')
    lines += ['', '## 与最简单仅OCR修复的直接配对比较', '', '差值=JS门控−repair；准确率差越高越好，ASR差越低越好。下表CI单位为百分点，按同源图保持配对，不使用独立两组近似。', '', '| 条件 | 准确率差 | 配对95% CI | ASR差 | 配对95% CI |', '|---|---:|---|---:|---|']
    for c in comparisons:
        lines.append(f'| {c["condition"]} | {signed(c["accuracy_delta"])} | {ci(c["accuracy_ci95"])} | {signed(c["asr_delta"]) if c["asr_delta"] is not None else "不适用"} | {ci(c["asr_ci95"])} |')
    lines += ['', uncertainty, '', '## 检测与门控诊断', '', f'wrong样本中检测到OCR框：{detected}/{len(wrong_rows)}；门控触发：{active}/{len(wrong_rows)}。', '',
              'ASR只在clean原始正确子集定义，防御后变成其他错误类别并不等于恢复正确。因此ASR、准确率与clean代价必须共同判断。无多重比较校正，CI不能解释成方法有95%概率优越。', '',
              '## 实际案例', '', '```json', json.dumps(manifest, ensure_ascii=False, indent=2), '```', '',
              '## 时间与缓存', '', '```json', json.dumps(summary['timing'], ensure_ascii=False, indent=2), '```', '',
              '缓存中的逐行OCR时间是初次计算耗时，不是当前运行时延。共享推理不支持从总时间推算各方法独立部署速度。', '',
              '## 可视化', '', '![测试准确率与ASR](<../outputs/full/accuracy_asr.png>)', '',
              '![JS分布](<../outputs/full/js_distribution.png>)', '', '![字号与位置敏感性](<../outputs/full/sensitivity.png>)', '',
              '## 局限', '', '低分辨率图像放大、固定英文字体与白底叠加、单骨干和单提示模板限制外部效度。OCR漏检/误检与修复纹理可共同影响结果；oracle不是可部署方法。开发调参严格隔离，但不能排除小开发集过拟合。案例选择仅用于解释，不是总体效应估计。', '',
              '## 核验参考资料（原文保留）', '', references_text]
    (output / 'analysis.md').write_text('\n'.join(lines), encoding='utf-8')
    (output / 'paper_statistics.json').write_text(json.dumps({'gate_vs_repair': comparisons}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Wrote {doc_path} and {output / "analysis.md"}; actual page count requires rendering.')


if __name__ == '__main__':
    main()
