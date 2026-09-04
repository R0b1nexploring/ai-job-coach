from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .qa import inspect_pdf
from .renderer import render_docx, render_html
from .validation import REPO_ROOT, ResumeWorkflowError, load_content, validate_content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验结构化简历，并生成 DOCX、PDF 和 QA 报告。"
    )
    parser.add_argument("--input", type=Path, required=True, help="content_version=2 的 JSON")
    parser.add_argument("--name", required=True, help="安全的输出名，例如 company-role-target")
    parser.add_argument("--photo", type=Path, help="可选的本地证件照")
    parser.add_argument("--force", action="store_true", help="覆盖同名产物")
    args = parser.parse_args(argv)

    try:
        content, summary = validate_content(load_content(args.input))
        if args.photo and not args.photo.is_file():
            raise ResumeWorkflowError(["photo: 文件不存在"])
        stem = _safe_stem(args.name)
        if not stem:
            raise ResumeWorkflowError(["name: must contain letters, digits, hyphens, or underscores"])
        docx_dir = REPO_ROOT / "output" / "docx"
        pdf_dir = REPO_ROOT / "output" / "pdf"
        qa_dir = REPO_ROOT / "output" / "qa"
        preview_dir = REPO_ROOT / "tmp" / "pdfs" / "generated"
        for directory in (docx_dir, pdf_dir, qa_dir, preview_dir):
            directory.mkdir(parents=True, exist_ok=True)
        docx_path = docx_dir / f"{stem}.docx"
        pdf_path = pdf_dir / f"{stem}.pdf"
        qa_path = qa_dir / f"{stem}.qa.json"
        existing = [path for path in (docx_path, pdf_path, qa_path) if path.exists()]
        if existing and not args.force:
            raise ResumeWorkflowError(["output: artifact exists; pass --force to replace it"])
        if args.force:
            for path in existing:
                path.unlink()

        docx_path.write_bytes(render_docx(content, args.photo))
        _render_pdf(content, args.photo, docx_path, pdf_path, preview_dir)
        if not pdf_path.exists():
            raise ResumeWorkflowError(["pdf: conversion did not create the expected artifact"])
        report = inspect_pdf(pdf_path, content, preview_dir)
        report["content_summary"] = summary
        qa_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if report["status"] != "passed":
            raise ResumeWorkflowError(report["issues"])
    except ResumeWorkflowError as exc:
        print("简历生成失败：", file=sys.stderr)
        for issue in exc.issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"简历生成失败：{type(exc).__name__}", file=sys.stderr)
        return 1

    print(
        f"已生成 {pdf_path.name}：{summary['sections']} 个分区，"
        f"{summary['bullets']} 条要点，{summary['unachieved']} 条未达成学习目标。"
    )
    print(f"DOCX: {docx_path}")
    print(f"PDF:  {pdf_path}")
    print(f"QA:   {qa_path}")
    return 0


def _render_pdf(
    content: dict,
    photo_path: Path | None,
    docx_path: Path,
    pdf_path: Path,
    preview_dir: Path,
) -> None:
    chrome = _find_chrome()
    if chrome:
        html_path = preview_dir / f"{pdf_path.stem}.html"
        html_path.write_text(render_html(content, photo_path), encoding="utf-8")
        try:
            with tempfile.TemporaryDirectory(prefix="resume-chrome-", dir=preview_dir) as profile_dir:
                _run_chrome(
                    chrome,
                    profile_dir,
                    html_path,
                    pdf_path,
                )
        finally:
            html_path.unlink(missing_ok=True)
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            return
    _convert_docx_to_pdf(docx_path, pdf_path.parent)


def _find_chrome() -> str | None:
    candidates = (
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    )
    return next((str(path) for path in candidates if path and Path(path).is_file()), None)


def _run_chrome(chrome: str, profile_dir: str, html_path: Path, pdf_path: Path) -> None:
    command = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--disable-background-mode",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-extensions",
        "--disable-sync",
        "--no-first-run",
        "--no-pdf-header-footer",
        f"--user-data-dir={profile_dir}",
        f"--print-to-pdf={pdf_path}",
        html_path.resolve().as_uri(),
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    deadline = time.monotonic() + 20
    last_size = -1
    stable_checks = 0
    while process.poll() is None and time.monotonic() < deadline:
        if pdf_path.exists():
            size = pdf_path.stat().st_size
            stable_checks = stable_checks + 1 if size == last_size and size > 0 else 0
            last_size = size
            if stable_checks >= 3:
                break
        time.sleep(0.15)
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()


def _convert_docx_to_pdf(docx_path: Path, pdf_dir: Path) -> None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise ResumeWorkflowError(["pdf: LibreOffice/soffice is not available"])
    result = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(docx_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ResumeWorkflowError(["pdf: LibreOffice conversion failed"])


def _safe_stem(value: str) -> str:
    return "".join(char for char in value.strip() if char.isalnum() or char in "-_")[:100]


if __name__ == "__main__":
    raise SystemExit(main())
