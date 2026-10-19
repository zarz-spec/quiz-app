# -*- coding: utf-8 -*-
"""真题解析核心：提取文字 + 解析选择题/答案/解析。供 转题.py 和 serve.py 共用。"""
import os, re, subprocess, json

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quiz_template.html")

# ---------------- 提取文字 ----------------
def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(path)
        text = "\n\n".join((p.extract_text() or "") for p in r.pages)
        if len(text.strip()) < 100:   # 扫描件/图片 PDF 无文字层，回退 OCR
            text = ocr_pdf(path)
        return text
    if ext in (".docx", ".doc"):
        out = subprocess.run(["textutil", "-convert", "txt", "-stdout", path],
                             capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or "textutil 失败")
        return out.stdout
    if ext in (".txt", ".md", ".text"):
        return open(path, encoding="utf-8", errors="ignore").read()
    raise RuntimeError(f"不支持的文件类型 {ext}")

def ocr_pdf(path):
    """扫描件 OCR（macOS Vision，仅本机可用；服务器无 OCR 时返回空，优雅降级）。"""
    d = os.path.dirname(os.path.abspath(__file__))
    bin_path = os.path.join(d, "ocr")
    if os.path.exists(bin_path):
        cmd = [bin_path, path]
    else:
        cmd = ["swift", os.path.join(d, "ocr.swift"), path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return out.stdout or ""
    except Exception:
        return ""   # 无 OCR 环境（如 Linux 服务器），扫描件返回空，由上层提示

# ---------------- 解析器 ----------------
def normalize(s):
    s = s or ""
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)  # 清 PDF 控制字符
    out = []
    for ch in s:
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:
            ch = chr(o - 0xFEE0)
        elif ch == "　":
            ch = " "
        out.append(ch)
    s = "".join(out)
    return s.replace("．", ".").replace("：", ":").replace("（", "(").replace("）", ")")

Q_START = re.compile(r'^\s*(\d{1,3})\s*[.．、)）:：]\s*(.+)$')
OPT_LINE = re.compile(r'^[A-H]\s*[.．、:：)）]?\s*\S')
OPT_MARK = re.compile(r'(^|\s)([A-H])\s*[.．、:：)）]?\s*')

def is_answer_line(line):
    return bool(re.fullmatch(r'(\d{1,3}\s*[.．、]\s*[A-H]\s*)+', line)) or bool(re.fullmatch(r'\s*[A-H]\s*', line))

def is_answer_heading(line):
    # 只匹配真正的答案区标题（整行），不误伤「答案：D」这种每题后的答案
    s = line.strip()
    return bool(re.fullmatch(r'(参考)?答案(及解析|与解析|及评分标准)?\s*[：:]?\s*', s))

def split_option_line(line):
    out = []
    matches = []
    for m in OPT_MARK.finditer(line):
        matches.append((m.group(2), m.end(), m.start()))
    for i, (key, start, idx) in enumerate(matches):
        end = matches[i + 1][2] if i + 1 < len(matches) else len(line)
        text = line[start:end].strip()
        if text:
            out.append((key, text))
    return out

def extract_answers(s):
    m = {}
    for mm in re.finditer(r'(\d{1,3})\s*[.．、:：]?\s*([A-H])\b', s):
        no, k = int(mm.group(1)), mm.group(2)
        if no not in m:
            m[no] = k
    for mm in re.finditer(r'(\d{1,3})\s*[-~～]\s*(\d{1,3})\s*[:：]?\s*([A-H]+)', s):
        a, b, ks = int(mm.group(1)), int(mm.group(2)), mm.group(3)
        for i in range(len(ks)):
            if a + i <= b:
                m[a + i] = ks[i]
    return m

def parse_answer_doc(text):
    text = normalize(text)
    m = {}
    markers = []
    for mm in re.finditer(r'(\d{1,3})\s*[.．、]?\s*答案\s*[:：]\s*([A-H])', text):
        markers.append((int(mm.group(1)), mm.group(2), mm.end(), mm.start()))
    for i, (no, ans, end, start) in enumerate(markers):
        nxt = markers[i + 1][3] if i + 1 < len(markers) else len(text)
        seg = text[end:nxt]
        xm = re.search(r'解析\s*[:：]\s*([\s\S]*)', seg)
        x = re.sub(r'\s+', ' ', xm.group(1).strip()) if xm else ""
        m[no] = {"ans": ans, "x": x}
    return m

def parse(paper_text, ans_text):
    paper_text = normalize(paper_text)
    ans_text = normalize(ans_text or "")
    lines = [l.strip() for l in paper_text.splitlines() if l.strip()]
    ans_map = extract_answers((ans_text or "") + "\n" + paper_text)

    questions = []
    cur = None
    in_explain = False
    for line in lines:
        if is_answer_heading(line):
            break
        qm = Q_START.match(line)
        is_opt = bool(OPT_LINE.match(line))
        m_ans = re.match(r'^答案\s*[:：]\s*([A-H])\s*$', line)   # 每题后的「答案：D」
        m_x = re.match(r'^解析\s*[:：]\s*(.*)$', line)            # 每题后的「解析：…」

        if qm and not is_answer_line(line) and not is_opt:
            cur = {"no": int(qm.group(1)), "stem": [qm.group(2).strip()],
                   "opts": [], "ans": "", "x": ""}
            questions.append(cur)
            in_explain = False
        elif cur and is_opt:
            cur["opts"].extend(split_option_line(line))
            in_explain = False
        elif cur and m_ans:
            cur["ans"] = m_ans.group(1)
            in_explain = False
        elif cur and m_x:
            cur["x"] = (cur["x"] + " " + m_x.group(1)).strip()
            in_explain = True
        elif cur and in_explain:
            cur["x"] = (cur["x"] + " " + line).strip()
        elif cur and not is_answer_line(line):
            cur["stem"].append(line)

    mcq, skipped = [], []
    for c in questions:
        if len(c["opts"]) >= 2:
            opts = [o[1] for o in c["opts"]]
            keys = [o[0] for o in c["opts"]]
            correct = c["ans"] or ans_map.get(c["no"], "")
            correct = correct if correct in keys else ""
            stem = " ".join(c["stem"])
            stem = re.sub(r'^[【\[][^】\]]*[】\]]\s*', '', stem)   # 去【单选题】等标签
            stem = re.sub(r'[（(]\s*[）)]\s*$', '', stem).strip()
            x = c["x"] or ("" if correct else "未识别答案")
            mcq.append({"type": "mcq", "no": c["no"], "q": stem, "opts": opts,
                        "ans": correct, "x": x})
        else:
            skipped.append(c["no"])
    return mcq, skipped, len(ans_map)

def find_answer_file(paper):
    d = os.path.dirname(paper)
    base = os.path.splitext(os.path.basename(paper))[0]
    ym = re.search(r'\d{6}|\d{4}', base)
    year = ym.group() if ym else ""
    candidates = []
    for f in os.listdir(d):
        if "答案" not in f:
            continue
        if os.path.splitext(f)[1].lower() not in (".pdf", ".docx", ".doc", ".txt"):
            continue
        candidates.append(f)
    if not candidates:
        return None
    if len(candidates) == 1:
        return os.path.join(d, candidates[0])
    if year:
        scored = sorted(candidates, key=lambda f: (year in f), reverse=True)
        if year in scored[0]:
            return os.path.join(d, scored[0])
    return None

def render_html(data):
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    return html.replace("/*__QUIZ_DATA__*/", json.dumps(data, ensure_ascii=False))

def convert(paper_text, ans_text, title, subtitle="", source=""):
    """把试卷文字(+答案文字)转成完整的 quiz data dict。"""
    mcq, skipped, acnt = parse(paper_text, ans_text)
    expl = parse_answer_doc((ans_text or "") + "\n" + paper_text)
    for q in mcq:
        e = expl.get(q.get("no"))
        if e:
            if e["ans"] and not q["ans"]:
                q["ans"] = e["ans"]
            if e["x"]:
                q["x"] = e["x"]
    for q in mcq:
        q.pop("no", None)
    n_ans = sum(1 for q in mcq if q["ans"])
    return {
        "title": title,
        "subtitle": subtitle or f"共 {len(mcq)} 题 · {n_ans} 题带答案 · 客观题自动判分",
        "source": source,
        "pointsPerQuestion": 2,
        "fullScore": len(mcq) * 2,
        "questions": mcq,
        "_meta": {"total": len(mcq), "answered": n_ans, "skipped": len(skipped)},
    }
