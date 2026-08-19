"""Gradio interface backed by persistent research workflows."""

from __future__ import annotations

import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import gradio as gr

from paper_agents.agents import (
    ReaderAgent,
    ScreenerAgent,
    SynthesizerAgent,
    VerifierAgent,
)
from paper_agents.harness import ResearchWorkflow, RuntimeConfig
from paper_agents.providers import OpenAICompatibleProvider
from paper_agents.storage import ResearchStore
from paper_agents.tools import (
    CompositeRetriever,
    CrossrefClient,
    OpenAlexClient,
    UploadedPDFRetriever,
)


DATABASE = Path(os.getenv("PAPER_AGENTS_DATABASE", "data/research.db"))
REPORT_DIRECTORY = Path(os.getenv("PAPER_AGENTS_REPORTS", "data/reports"))
UPLOAD_DIRECTORY = Path(os.getenv("PAPER_AGENTS_UPLOADS", "data/uploads"))


@dataclass(frozen=True)
class TaskConfig:
    api_key: str
    model: str
    email: str
    topic_id: str
    question: str
    search_query: str
    rows: int
    from_year: int | None
    until_year: int | None
    fetch_open_access_full_text: bool = True
    max_workers: int = 4
    uploaded_paths: tuple[str, ...] = ()


@dataclass
class TaskRecord:
    job_id: str
    status: str = "queued"
    message: str = "任务已进入队列"
    run_id: str | None = None
    report_path: str | None = None


class BackgroundTaskManager:
    """Keep local research running after the browser tab is closed."""

    def __init__(self, *, max_workers: int = 1) -> None:
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="paper-research"
        )
        self.records: dict[str, TaskRecord] = {}
        self.lock = threading.Lock()

    def _build_workflow(self, config: TaskConfig) -> ResearchWorkflow:
        provider = OpenAICompatibleProvider(
            api_base="https://api.deepseek.com",
            api_key=config.api_key,
            model=config.model,
        )
        retrievers = [
            OpenAlexClient(
                email=config.email,
                fetch_full_text=config.fetch_open_access_full_text,
            ),
            CrossrefClient(mailto=config.email),
        ]
        if config.uploaded_paths:
            retrievers.insert(
                0, UploadedPDFRetriever([Path(path) for path in config.uploaded_paths])
            )
        return ResearchWorkflow(
            store=ResearchStore(DATABASE),
            retriever=CompositeRetriever(retrievers),
            screener=ScreenerAgent(provider),
            reader=ReaderAgent(provider),
            verifier=VerifierAgent(provider),
            synthesizer=SynthesizerAgent(provider),
            report_directory=REPORT_DIRECTORY,
            runtime_config=RuntimeConfig(max_workers=config.max_workers),
        )

    def submit(self, config: TaskConfig) -> str:
        job_id = "job-" + uuid4().hex[:10]
        with self.lock:
            self.records[job_id] = TaskRecord(job_id=job_id)
        self.executor.submit(self._execute_new, job_id, config)
        return job_id

    def submit_resume(self, run_id: str, config: TaskConfig) -> str:
        job_id = "job-" + uuid4().hex[:10]
        with self.lock:
            self.records[job_id] = TaskRecord(
                job_id=job_id, status="queued", message=f"等待恢复 {run_id}"
            )
        self.executor.submit(self._execute_resume, job_id, run_id, config)
        return job_id

    def _set(self, job_id: str, **updates: str | None) -> None:
        with self.lock:
            record = self.records[job_id]
            for key, value in updates.items():
                setattr(record, key, value)

    def _execute_new(self, job_id: str, config: TaskConfig) -> None:
        self._set(job_id, status="running", message="正在检索、筛选、研读和核验")
        workflow = None
        try:
            workflow = self._build_workflow(config)
            run = workflow.run(
                topic_id=config.topic_id,
                question=config.question,
                search_query=config.search_query,
                rows=config.rows,
                from_year=config.from_year,
                until_year=config.until_year,
            )
            self._finish(job_id, run.run_id, run.status.value)
        except Exception as exc:
            self._set(job_id, status="failed", message=f"任务失败：{exc}")
        finally:
            if workflow is not None:
                workflow.close()

    def _execute_resume(self, job_id: str, run_id: str, config: TaskConfig) -> None:
        self._set(job_id, status="running", message=f"正在从 {run_id} 继续")
        workflow = None
        try:
            workflow = self._build_workflow(config)
            run = workflow.resume(run_id)
            self._finish(job_id, run.run_id, run.status.value)
        except Exception as exc:
            self._set(job_id, status="failed", message=f"恢复失败：{exc}")
        finally:
            if workflow is not None:
                workflow.close()

    def _finish(self, job_id: str, run_id: str, run_status: str) -> None:
        report = REPORT_DIRECTORY / f"{run_id}.md"
        self._set(
            job_id,
            status="completed" if run_status == "completed" else run_status,
            message=f"任务状态：{run_status}",
            run_id=run_id,
            report_path=str(report.resolve()) if report.exists() else None,
        )

    def get(self, job_id: str) -> TaskRecord | None:
        with self.lock:
            record = self.records.get(job_id)
            return TaskRecord(**vars(record)) if record else None


TASK_MANAGER = BackgroundTaskManager(max_workers=1)


def _year(value: float | int | None) -> int | None:
    return int(value) if value is not None else None


def start_task(
    api_key: str,
    model: str,
    email: str,
    topic_id: str,
    question: str,
    search_query: str,
    rows: float,
    from_year: float,
    until_year: float,
    fetch_open_access_full_text: bool,
    max_workers: float,
    uploaded_files: list[str] | None,
) -> tuple[str, str, None]:
    if not api_key.strip():
        return "", "请填写 DeepSeek API Key。Key 只保留在本次本机运行内存中。", None
    if not question.strip() or not search_query.strip():
        return "", "请填写研究问题和英文检索词。", None
    saved_uploads: list[str] = []
    if uploaded_files:
        batch_dir = UPLOAD_DIRECTORY / ("batch-" + uuid4().hex[:10])
        batch_dir.mkdir(parents=True, exist_ok=True)
        for original in uploaded_files:
            source = Path(original)
            if source.suffix.casefold() != ".pdf":
                return "", f"只支持 PDF 文件：{source.name}", None
            destination = batch_dir / source.name
            shutil.copy2(source, destination)
            saved_uploads.append(str(destination.resolve()))
    config = TaskConfig(
        api_key=api_key.strip(),
        model=model,
        email=email.strip(),
        topic_id=topic_id.strip() or "custom-topic",
        question=question.strip(),
        search_query=search_query.strip(),
        rows=int(rows),
        from_year=_year(from_year),
        until_year=_year(until_year),
        fetch_open_access_full_text=bool(fetch_open_access_full_text),
        max_workers=int(max_workers),
        uploaded_paths=tuple(saved_uploads),
    )
    job_id = TASK_MANAGER.submit(config)
    return job_id, f"已启动后台任务 {job_id}。关闭浏览器不会主动取消。", None


def resume_task(
    run_id: str,
    api_key: str,
    model: str,
    email: str,
) -> tuple[str, str, None]:
    if not run_id.strip() or not api_key.strip():
        return "", "恢复任务需要 run_id 和 DeepSeek API Key。", None
    saved = ResearchStore(DATABASE).get_run(run_id.strip())
    if saved is None:
        return "", f"未找到任务 {run_id}。", None
    config = TaskConfig(
        api_key=api_key.strip(),
        model=model,
        email=email.strip(),
        topic_id=saved.topic_id,
        question=saved.question,
        search_query="resume-does-not-search",
        rows=1,
        from_year=None,
        until_year=None,
        fetch_open_access_full_text=True,
        max_workers=4,
    )
    job_id = TASK_MANAGER.submit_resume(run_id.strip(), config)
    return job_id, f"已提交恢复任务 {job_id}。", None


def check_task(job_id: str) -> tuple[str, str | None]:
    if not job_id.strip():
        return "请先启动任务，或输入 job_id。", None
    record = TASK_MANAGER.get(job_id.strip())
    if record is None:
        return "本次程序运行中未找到该 job_id；可使用 run_id 恢复持久化任务。", None
    details = [f"job_id: {record.job_id}", f"status: {record.status}", record.message]
    if record.run_id:
        details.append(f"run_id: {record.run_id}")
    return "\n\n".join(details), record.report_path


def list_saved_runs() -> str:
    runs = ResearchStore(DATABASE).list_runs()
    if not runs:
        return "暂无已保存任务。"
    return "\n".join(
        f"{run.run_id} | {run.status.value} | 候选 {run.candidate_count} | "
        f"入选 {run.included_count} | 核验 {run.verified_count} | {run.question}"
        for run in runs
    )


def inspect_run(run_id: str) -> tuple[str, str | None]:
    run_id = run_id.strip()
    if not run_id:
        return "请输入 run_id。", None
    store = ResearchStore(DATABASE)
    run = store.get_run(run_id)
    if run is None:
        return f"未找到任务 {run_id}。", None
    candidates = store.list_artifacts(run_id, "candidate")
    access = {"full_text": 0, "abstract_only": 0, "unavailable": 0}
    sources: dict[str, int] = {}
    for item in candidates:
        level = item.get("paper", {}).get("document_access", "unavailable")
        access[level] = access.get(level, 0) + 1
        source = item.get("retrieval_source", "unknown")
        sources[source] = sources.get(source, 0) + 1
    work = store.list_work(run_id)
    work_counts: dict[str, int] = {}
    for item in work:
        work_counts[item.status.value] = work_counts.get(item.status.value, 0) + 1
    source_text = "、".join(f"{key} {value}" for key, value in sorted(sources.items())) or "无"
    work_text = "、".join(f"{key} {value}" for key, value in sorted(work_counts.items())) or "无"
    details = (
        f"## {run.run_id}\n\n"
        f"- 状态：`{run.status.value}`\n"
        f"- 研究问题：{run.question}\n"
        f"- 候选 / 入选 / 通过核验 / 失败："
        f"{run.candidate_count} / {run.included_count} / {run.verified_count} / {run.failed_count}\n"
        f"- 全文 / 仅摘要 / 不可用：{access['full_text']} / "
        f"{access['abstract_only']} / {access['unavailable']}\n"
        f"- 检索来源：{source_text}\n"
        f"- 持久化队列：{work_text}\n"
        + (f"- 最近错误：{run.error}\n" if run.error else "")
    )
    report = REPORT_DIRECTORY / f"{run_id}.md"
    return details, str(report.resolve()) if report.exists() else None


def build_app() -> gr.Blocks:
    with gr.Blocks(title="论文调研多 Agent 系统") as demo:
        gr.Markdown(
            "# 论文调研多 Agent 系统\n"
            "本机运行、DeepSeek API 推理、OpenAlex + Crossref 多源检索。"
        )
        with gr.Row():
            api_key = gr.Textbox(label="DeepSeek API Key", type="password")
            model = gr.Dropdown(
                ["deepseek-v4-flash", "deepseek-v4-pro"],
                value="deepseek-v4-flash",
                label="模型",
            )
            email = gr.Textbox(label="Crossref 联系邮箱（建议填写）")

        topic_id = gr.Textbox(label="主题 ID", value="gnss-multipath")
        question = gr.Textbox(
            label="研究问题",
            value="近五年 GNSS 多径检测、建模和抑制方法有哪些，它们的产品化潜力如何？",
            lines=3,
        )
        search_query = gr.Textbox(
            label="英文检索词（OpenAlex + Crossref）",
            value="GNSS multipath mitigation urban canyon",
        )
        with gr.Row():
            rows = gr.Slider(1, 100, value=5, step=1, label="候选论文数")
            from_year = gr.Number(value=2021, precision=0, label="开始年份")
            until_year = gr.Number(value=2026, precision=0, label="结束年份")
        with gr.Row():
            fetch_full_text = gr.Checkbox(
                value=True, label="尝试获取开放获取 PDF 全文"
            )
            max_workers = gr.Slider(1, 8, value=4, step=1, label="并发研读数")
        uploaded_files = gr.File(
            label="可选：上传你已有的论文 PDF（可多选）",
            file_count="multiple",
            file_types=[".pdf"],
            type="filepath",
        )

        with gr.Row():
            start = gr.Button("开始调研", variant="primary")
            check = gr.Button("查询状态")
        job_id = gr.Textbox(label="job_id")
        status = gr.Markdown("尚未启动任务。")
        report_file = gr.File(label="最终报告")

        start.click(
            start_task,
            inputs=[
                api_key,
                model,
                email,
                topic_id,
                question,
                search_query,
                rows,
                from_year,
                until_year,
                fetch_full_text,
                max_workers,
                uploaded_files,
            ],
            outputs=[job_id, status, report_file],
        )
        check.click(check_task, inputs=[job_id], outputs=[status, report_file])

        gr.Markdown("## 中断恢复")
        run_id = gr.Textbox(label="run_id")
        with gr.Row():
            resume = gr.Button("恢复任务")
            refresh = gr.Button("刷新已保存任务")
        saved_runs = gr.Textbox(label="SQLite 任务记录", lines=6, interactive=False)
        resume.click(
            resume_task,
            inputs=[run_id, api_key, model, email],
            outputs=[job_id, status, report_file],
        )
        refresh.click(list_saved_runs, outputs=[saved_runs])

        gr.Markdown("## 任务详情与证据级别")
        inspect_id = gr.Textbox(label="要查看的 run_id")
        inspect_button = gr.Button("查看任务详情")
        inspect_result = gr.Markdown()
        inspect_report = gr.File(label="调研报告下载")
        inspect_button.click(
            inspect_run,
            inputs=[inspect_id],
            outputs=[inspect_result, inspect_report],
        )
    return demo


def main() -> None:
    demo = build_app()
    demo.queue().launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        inbrowser=True,
    )


if __name__ == "__main__":
    main()
