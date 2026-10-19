# -*- coding: utf-8 -*-
"""刷题产品后端：FastAPI + 用户系统 + 真题转题。"""
import os, json, base64, tempfile, glob, urllib.parse
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import auth
import services.parser as parser

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STATIC = os.path.join(BASE, "static")

auth.init_db()
app = FastAPI(title="刷题工具")


class AuthPayload(BaseModel):
    username: str
    password: str


class FilePayload(BaseModel):
    filename: str = ""
    data: str = ""      # base64 文件内容
    text: str = ""      # 粘贴的文字


class UploadPayload(BaseModel):
    subject: str = ""
    year: str = ""
    paper: FilePayload = FilePayload()
    answer: FilePayload = FilePayload()


def decode_extract(item):
    ext = os.path.splitext(item.filename)[1].lower() or ".txt"
    raw = base64.b64decode(item.data)
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp.write(raw)
    tmp.close()
    try:
        return parser.extract_text(tmp.name)
    finally:
        os.unlink(tmp.name)


def user_dir(uid):
    return os.path.join(DATA, str(uid))


# ---------- 认证 ----------
@app.post("/api/register")
def register(p: AuthPayload):
    uid = auth.register(p.username.strip(), p.password)
    if not uid:
        raise HTTPException(400, "用户名已存在")
    return {"ok": True, "token": auth.create_session(uid)}


@app.post("/api/login")
def login(p: AuthPayload):
    uid = auth.login(p.username.strip(), p.password)
    if not uid:
        raise HTTPException(401, "用户名或密码错误")
    return {"ok": True, "token": auth.create_session(uid)}


# ---------- 题库 ----------
@app.post("/api/upload")
def upload(p: UploadPayload, uid: int = Depends(auth.get_current_user)):
    subject = p.subject.strip() or "未分类"
    year = p.year.strip() or "未命名"

    if p.paper.text:
        paper_text = p.paper.text
    elif p.paper.data:
        paper_text = decode_extract(p.paper)
    else:
        raise HTTPException(400, "请选择试卷文件，或粘贴试卷文字")

    if p.answer.text:
        ans_text = p.answer.text
    elif p.answer.data:
        ans_text = decode_extract(p.answer)
    else:
        ans_text = ""

    title = f"{subject} · {year}"
    data = parser.convert(paper_text, ans_text, title,
                          subtitle=f"{subject} · {year}",
                          source=f"来源：{p.paper.filename}")
    if not data["questions"]:
        n = len(paper_text.strip())
        hint = "扫描件暂不支持，请用文字版 PDF / docx，或直接粘贴题目文字" if n < 50 \
            else f"提取到 {n} 字，但没匹配到「题目+ABCD选项」的格式"
        raise HTTPException(400, f"没有识别出选择题：{hint}")

    safe_subject = subject.replace("/", "_").replace("\\", "_")
    safe_year = year.replace("/", "_").replace("\\", "_")
    folder = os.path.join(user_dir(uid), safe_subject)
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, safe_year)
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    with open(base + ".html", "w", encoding="utf-8") as f:
        f.write(parser.render_html(data))

    return {
        "ok": True,
        "total": data["_meta"]["total"],
        "answered": data["_meta"]["answered"],
        "href": urllib.parse.quote(f"/quiz/{safe_subject}/{safe_year}.html"),
    }


@app.get("/api/list")
def list_quizzes(uid: int = Depends(auth.get_current_user)):
    subjects = {}
    for jpath in glob.glob(os.path.join(user_dir(uid), "**", "*.json"), recursive=True):
        try:
            with open(jpath, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        subject = d.get("subject") or os.path.basename(os.path.dirname(jpath))
        year = d.get("year") or os.path.splitext(os.path.basename(jpath))[0]
        title = d.get("title") or f"{subject} · {year}"
        n = len(d.get("questions", []))
        n_ans = sum(1 for q in d.get("questions", []) if q.get("ans"))
        rel = os.path.relpath(os.path.splitext(jpath)[0], user_dir(uid)) + ".html"
        subjects.setdefault(subject, []).append({
            "subject": subject, "year": year, "title": title,
            "href": urllib.parse.quote("/quiz/" + rel),
            "total": n, "answered": n_ans,
        })
    result = []
    for subject, quizzes in subjects.items():
        quizzes.sort(key=lambda q: q["year"], reverse=True)
        result.append({"subject": subject, "quizzes": quizzes})
    result.sort(key=lambda s: s["subject"])
    return {"ok": True, "data": result}


@app.get("/api/practice")
def practice(subject: str = "", uid: int = Depends(auth.get_current_user)):
    all_q = []
    for jpath in glob.glob(os.path.join(user_dir(uid), "**", "*.json"), recursive=True):
        try:
            with open(jpath, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        s = d.get("subject") or os.path.basename(os.path.dirname(jpath))
        if s != subject:
            continue
        for q in d.get("questions", []):
            if q.get("type") == "mcq":
                all_q.append(q)
    return {"ok": True, "data": {"subject": subject, "total": len(all_q), "questions": all_q}}


# ---------- 静态 ----------
@app.get("/quiz/{path:path}")
def quiz(path: str, uid: int = Depends(auth.get_current_user)):
    fp = os.path.join(user_dir(uid), path)
    if not fp.endswith(".html") or not os.path.exists(fp):
        raise HTTPException(404, "题目不存在")
    return FileResponse(fp)


# 静态前端（放最后，兜底所有未匹配路径）
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
