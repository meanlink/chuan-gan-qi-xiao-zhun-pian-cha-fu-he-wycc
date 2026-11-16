"""按温区分层的校准残差 bootstrap，分段续算且固定随机种子可复现。"""
import copy
import math
import random
import time
import numpy as np

SEED = 1007
DEFAULT_SEGMENT_SIZE = 500


def metadata():
    return {"name": "传感器校准偏差复核", "short": "sensor-bootstrap", "tagline": "保留温区构成，估计校准残差的可信范围。", "client": "望衡仪器 · 16 人校准实验室，复核工业温度探头的批次偏差", "workflow": "实验员汇总低、常、高温记录，只按整体平均误差判定是否重校。", "pains": ["不同温区的样本构成被打散", "偏差估计缺少区间", "补偿值变化后要重复手算"], "upstream": "探头与标准源配对记录 WH_calibration_pairs.csv", "downstream": "计量工程师据残差分层区间安排复校",
            "entities": ["校准配对样本", "分层偏差复核", "计量复核简报"], "dataset_name": "T-24 探头批次 · 三温区 240 对读数",
            "columns": [{"key": "sample", "label": "读数编号", "type": "string"}, {"key": "band", "label": "温区", "type": "string"}, {"key": "reference", "label": "标准值 °C", "type": "number"}, {"key": "measured", "label": "探头值 °C", "type": "number"}],
            "parameters": [{"key": "offset", "label": "扣除补偿值 °C", "type": "number", "default": 0, "min": -2, "max": 2}, {"key": "confidence", "label": "置信度", "type": "select", "default": "0.95", "options": [{"value": str(x), "label": f"{x*100:g}%"} for x in [.9, .95, .99]]}, {"key": "resamples", "label": "重采样次数", "type": "number", "default": 2000, "min": 500, "max": 5000}],
            "workbench_title": "分层校准区间估计", "action_label": "执行分层 Bootstrap", "unit": "°C", "accent": "oklch(50% 0.105 320)", "style": "metrology",
            "seed_story": ["08:00 实验员导入 WH_calibration_pairs.csv，240 对读数。", "08:15 核对低温、常温、高温各 80 对。", "08:30 设补偿值 0°C、95% 区间、2000 次采样。", "08:35 执行分层 bootstrap，查看总体及各温区区间。", "08:50 找出区间不跨 0 的温区。", "09:10 将补偿值设为 0.3°C，复核剩余偏差。", "09:40 导出计量简报，安排分温区补偿试验。"],
            "method": "残差=探头值−标准值−补偿值；每温区独立有放回抽取原样本量，再按原温区样本占比合成总体平均残差；percentile bootstrap 区间；每条重采样由固定 seed=1007、温区序和次数序号派生独立 RNG，因此分段、暂停或接管后续算，与同一参数下整份计算得到完全相同的区间。", "limitations": ["区间依赖本批次及温区构成", "重复测量相关性尚未建模", "统计区间不是法定计量合格证据"]}


def seed_records():
    rng = random.Random(1007)
    rows = []
    for band, center, bias, sigma in [("低温", -10, -.08, .14), ("常温", 25, .22, .1), ("高温", 70, .66, .23)]:
        for i in range(80):
            ref = center + rng.uniform(-3, 3)
            rows.append({"sample": f"T24-{band}-{i+1:03}", "band": band, "reference": round(ref, 4), "measured": round(ref + bias + rng.gauss(0, sigma), 4)})
    return rows


def _settings(params):
    try:
        offset = float(params.get("offset", 0))
        confidence = float(params.get("confidence", .95))
        raw_b = float(params.get("resamples", 2000))
        resamples = int(raw_b)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("补偿值、置信度和重采样次数须为有效数值")
    if not math.isfinite(offset) or not -2 <= offset <= 2 or confidence not in (.9, .95, .99) or raw_b != resamples or not 500 <= resamples <= 5000:
        raise ValueError("补偿范围 −2–2°C，次数为 500–5000 整数，置信度为 0.9/0.95/0.99")
    return offset, confidence, resamples


def prepare(records, params):
    """校验输入并准备每温区的残差数组；与重采样次数无关，可在每次续算时重建。"""
    offset, confidence, resamples = _settings(params)
    grouped, seen = {}, set()
    for r in records:
        try:
            sample, band = str(r["sample"]), str(r["band"])
            ref, measured = float(r["reference"]), float(r["measured"])
            if sample in seen or not band.strip() or not all(math.isfinite(x) for x in (ref, measured)):
                raise ValueError()
            seen.add(sample)
            grouped.setdefault(band, []).append(measured - ref - offset)
        except (KeyError, TypeError, ValueError):
            raise ValueError("样本编号须唯一，温区及两个有限读数不能为空")
    if len(grouped) < 2 or any(len(v) < 3 for v in grouped.values()):
        raise ValueError("至少两个温区，每温区至少 3 对读数")
    if len(records) > 5000:
        raise ValueError("单次最多 5000 对读数，请按批次拆分")
    bands = sorted(grouped)
    values = {band: np.asarray(grouped[band], dtype=float) for band in bands}
    return {"offset": offset, "confidence": confidence, "target": resamples, "bands": bands, "values": values,
            "total": sum(len(v) for v in grouped.values())}


def initial_progress(prepared, fingerprint, segment_size=DEFAULT_SEGMENT_SIZE, target=None):
    return {"fingerprint": fingerprint, "target": int(target or prepared["target"]), "completed": 0,
            "segment_size": int(segment_size or DEFAULT_SEGMENT_SIZE),
            "bands": {band: {"n": int(prepared["values"][band].size), "means": []} for band in prepared["bands"]}}


def means_for(band, values, band_index, start, stop):
    """第 i 条重采样的随机流只由 seed、温区序和 i 决定，和分段边界无关。"""
    out = np.empty(max(0, stop - start), dtype=float)
    n = values.size
    for pos, i in enumerate(range(start, stop)):
        rng = np.random.default_rng(np.random.SeedSequence([SEED, band_index, i]))
        out[pos] = values[rng.integers(0, n, size=n)].mean()
    return out


def advance(progress, prepared, segment_size=None):
    """只计算尚未完成的一段，返回新的进度对象（不修改入参）。"""
    progress = copy.deepcopy(progress)
    target = int(progress.get("target") or prepared["target"])
    step = int(segment_size or progress.get("segment_size") or DEFAULT_SEGMENT_SIZE)
    step = max(1, step)
    if target > prepared["target"]:
        raise ValueError("目标采样次数超出参数范围")
    started = time.time()
    for index, band in enumerate(prepared["bands"]):
        entry = progress.setdefault("bands", {}).setdefault(band, {"n": int(prepared["values"][band].size), "means": []})
        if int(entry.get("n", 0)) != int(prepared["values"][band].size):
            raise ValueError("温区样本构成与已存进度不一致，无法续算")
        done = len(entry.get("means") or [])
        if done > target:
            entry["means"] = entry["means"][:target]
            done = target
        stop = min(target, done + step)
        if stop > done:
            found = means_for(band, prepared["values"][band], index, done, stop)
            entry["means"] = list(entry["means"]) + [float(x) for x in found]
    progress["completed"] = min((len(e.get("means") or []) for e in progress.get("bands", {}).values()), default=0)
    progress["updated_at"] = started
    return progress


def complete(progress, prepared):
    target = int(progress.get("target") or prepared["target"])
    return bool(progress.get("bands")) and all(len((progress["bands"].get(band) or {}).get("means") or []) >= target for band in prepared["bands"])


def progress_meta(progress):
    """供列表页与轮询使用的轻量进度，不包含逐次采样明细。"""
    progress = progress or {}
    target = int(progress.get("target") or 0)
    bands = progress.get("bands") or {}
    per_band = [{"band": band, "n": int(entry.get("n") or 0), "completed": len(entry.get("means") or [])}
                for band, entry in sorted(bands.items())]
    completed = min((b["completed"] for b in per_band), default=0)
    return {"target": target, "completed": completed, "segment_size": int(progress.get("segment_size") or 0),
            "bands": per_band, "percent": round(completed * 100 / target, 1) if target else 0,
            "updated_at": progress.get("updated_at")}


def finalize(prepared, progress):
    """各温区进度齐备后才发布结论；区间只取决于已存样本和目标次数。"""
    if not complete(progress, prepared):
        raise ValueError("采样尚未完成，不能发布结论")
    target = int(progress["target"])
    confidence = prepared["confidence"]
    q = [(1 - confidence) / 2, (1 + confidence) / 2]
    total = prepared["total"]
    aggregate = np.zeros(target)
    rows = []
    bias_total = 0.0
    for band in prepared["bands"]:
        values = prepared["values"][band]
        means = np.asarray(progress["bands"][band]["means"][:target], dtype=float)
        # 保留每层样本量，避免整体重抽样改变温区结构。
        aggregate += means * values.size / total
        low, high = [float(x) for x in np.quantile(means, q)]
        bias = float(values.mean())
        bias_total += bias * values.size
        rows.append({"band": band, "n": int(values.size), "bias": round(bias, 6), "low": round(low, 6), "high": round(high, 6), "review": "偏差区间未跨 0" if low > 0 or high < 0 else "区间跨 0"})
    low, high = [float(x) for x in np.quantile(aggregate, q)]
    bias = bias_total / total
    return {"summary": f"分层重采样 {target} 次，补偿后平均残差 {bias:.4f}°C，{confidence*100:g}% 区间 [{low:.4f}, {high:.4f}]°C。",
            "metrics": [{"label": "平均剩余偏差", "value": round(bias, 6), "unit": "°C"}, {"label": "区间下界", "value": round(low, 6), "unit": "°C"}, {"label": "区间上界", "value": round(high, 6), "unit": "°C"}, {"label": "重采样次数", "value": target}],
            "table": {"columns": [{"key": "band", "label": "温区"}, {"key": "n", "label": "样本数"}, {"key": "bias", "label": "平均残差 °C"}, {"key": "low", "label": "区间下界 °C"}, {"key": "high", "label": "区间上界 °C"}, {"key": "review", "label": "复校线索"}], "rows": rows},
            "chart": {"type": "bar", "labels": [r["band"] for r in rows], "series": [{"name": "平均残差 °C", "values": [r["bias"] for r in rows]}, {"name": "区间下界", "values": [r["low"] for r in rows]}, {"name": "区间上界", "values": [r["high"] for r in rows]}]},
            "findings": [f"{r['band']} {r['n']} 对，平均残差 {r['bias']:.4f}°C；{r['review']}。" for r in rows] + [f"原温区构成保持不变；本次扣除补偿值 {prepared['offset']:g}°C，RNG seed=1007，共 {target} 次。", "采样按段持久化，分段、暂停或接管续算不改变同参数同总次数的区间。"], "method": metadata()["method"], "warnings": ["重复测量相关性未建模，正式计量判断仍需依照实验室规程。"]}


def analyze(records, params):
    """完整执行一份分析；内部同样按段推进，便于测试和演示种子。"""
    result, _ = analyze_with_progress(records, params)
    return result


def analyze_with_progress(records, params):
    """返回结果与逐次采样进度，便于把已算样本原样保存以供续算。"""
    prepared = prepare(records, params)
    progress = initial_progress(prepared, None, prepared["target"])
    while not complete(progress, prepared):
        progress = advance(progress, prepared, prepared["target"])
    return finalize(prepared, progress), progress
