from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from uat_bot.browser.screenshots import ScreenshotManager
from uat_bot.config import Settings
from uat_bot.core.run_state import RunState
from uat_bot.core.user_manager import KamiwazaUserManager
from uat_bot.core.worker import Worker
from uat_bot.models import RunCreateRequest, RunDetail, RunStatus, RunSummary
from uat_bot.reporting.analyzer import RunAnalyzer
from uat_bot.reporting.generator import ReportGenerator
from uat_bot.scenarios.uat_context import UATContextLoader
from uat_bot.stress.planner import AssignmentPlanner
from uat_bot.stress.ramp import ramp_delay_seconds
from uat_bot.vision.client import VisionClient


class StressOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.user_manager = KamiwazaUserManager(settings)
        self.reporter = ReportGenerator()
        self.planner = AssignmentPlanner()
        self.uat_context_loader = UATContextLoader(settings)
        self._runs: dict[str, RunState] = {}
        self._lock = asyncio.Lock()

    async def list_runs(self) -> list[RunSummary]:
        async with self._lock:
            runs = list(self._runs.values())
        return [self._summary(state) for state in sorted(runs, key=lambda r: r.created_at, reverse=True)]

    async def get_run(self, run_id: str) -> RunState | None:
        async with self._lock:
            return self._runs.get(run_id)

    async def start_run(self, config: RunCreateRequest) -> RunState:
        run_id = uuid.uuid4().hex
        run_dir = self.settings.uat_data_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        state = RunState(run_id=run_id, config=config, root_dir=run_dir)
        state.metrics_path = run_dir / "metrics.jsonl"
        state.event_log_path = run_dir / "events.jsonl"

        async with self._lock:
            self._runs[run_id] = state

        task = asyncio.create_task(self._execute_run(state), name=f"uat-run-{run_id}")
        state.set_task(task)
        return state

    async def stop_run(self, run_id: str) -> bool:
        state = await self.get_run(run_id)
        if not state:
            return False

        state.request_cancel()
        if state.task and not state.task.done():
            state.task.cancel()
            try:
                await state.task
            except asyncio.CancelledError:
                pass
        return True

    async def purge_run(self, run_id: str) -> bool:
        state = await self.get_run(run_id)
        if not state:
            return False

        await self.stop_run(run_id)

        async with self._lock:
            state = self._runs.pop(run_id, None)
        if not state:
            return False

        shutil.rmtree(state.root_dir, ignore_errors=True)
        return True

    async def stream_event(self, run_id: str, timeout: float = 1.0):
        state = await self.get_run(run_id)
        if not state:
            return None
        return await state.next_event(timeout=timeout)

    async def _execute_run(self, state: RunState) -> None:
        state.status = RunStatus.running
        state.started_at = datetime.now(UTC)
        runtime_cfg = self.user_manager.resolve_runtime_config(state.config)
        state.effective_kamiwaza_url = runtime_cfg.base_url or None
        state.auth_source = runtime_cfg.source
        await state.emit(
            "run.started",
            {
                "config": self._redacted_config(state.config.model_dump(mode="json")),
                "effective_kamiwaza_url": state.effective_kamiwaza_url,
                "auth_source": state.auth_source,
            },
        )

        metric_lock = asyncio.Lock()
        screenshot_manager = ScreenshotManager(
            run_dir=state.root_dir,
            quality_setting=self.settings.uat_screenshot_quality,
        )

        async def metric_sink(row: dict) -> None:
            async with metric_lock:
                if state.metrics_path is None:
                    return
                with state.metrics_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=True) + "\n")

        try:
            bundle = self.uat_context_loader.load_bundle(component=state.config.component)
            state.uat_guidance = bundle
            if bundle.docs:
                analysis_dir = state.root_dir / "analysis"
                analysis_dir.mkdir(parents=True, exist_ok=True)
                guidance_path = analysis_dir / "uat_guidance_index.json"
                summary_rows = [
                    {
                        "path": doc.path,
                        "char_count": len(doc.content),
                        "snippet": doc.content[:200],
                    }
                    for doc in bundle.docs
                ]
                guidance_path.write_text(
                    json.dumps(
                        {
                            "component": bundle.component,
                            "source_dirs": bundle.source_dirs,
                            "doc_count": len(bundle.docs),
                            "docs": summary_rows,
                        },
                        ensure_ascii=True,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            await state.emit(
                "run.guidance_loaded",
                {
                    "component": state.config.component,
                    "source_dirs": bundle.source_dirs,
                    "files": bundle.file_paths,
                },
            )

            if state.config.skip_user_provisioning:
                # Use admin credentials directly — no API user provisioning
                from uat_bot.models import TestUser

                admin_user = runtime_cfg.admin_user or "admin"
                admin_password = runtime_cfg.admin_password or ""
                roles = self.user_manager._build_role_list(state.config.role_distribution)
                users = []
                for idx, role in enumerate(roles, start=1):
                    users.append(
                        TestUser(
                            username=admin_user,
                            password=admin_password,
                            role=role,
                            user_id=f"direct-{idx}",
                        )
                    )
                state.users = users
                await state.emit(
                    "run.users_provisioned",
                    {"count": len(users), "mode": "direct_credentials"},
                )
            else:
                users = await self.user_manager.provision_test_users(
                    run_id=state.run_id,
                    count=state.config.concurrent_users,
                    role_distribution=state.config.role_distribution,
                    runtime_config=runtime_cfg,
                )
                state.users = users
                await state.emit("run.users_provisioned", {"count": len(users)})

            assignments = self.planner.assign(
                users=users,
                browser_distribution=state.config.browser_distribution,
                os_profiles=state.config.os_emulation,
                scenarios=state.config.scenarios,
            )

            # Build vision client if enabled and API key is available
            vision_client = None
            if state.config.vision_enabled and self.settings.anthropic_api_key:
                vision_client = VisionClient(
                    api_key=self.settings.anthropic_api_key,
                    model=self.settings.uat_vision_model,
                    model_complex=self.settings.uat_vision_model_complex,
                )

            semaphore = asyncio.Semaphore(self.settings.uat_max_workers)
            worker_tasks: list[asyncio.Task[None]] = []

            for idx, assignment in enumerate(assignments):
                delay = ramp_delay_seconds(
                    idx, len(assignments), state.config.ramp_up_seconds
                )

                task = asyncio.create_task(
                    self._run_worker(
                        state=state,
                        assignment=assignment,
                        delay_seconds=delay,
                        semaphore=semaphore,
                        screenshot_manager=screenshot_manager,
                        metric_sink=metric_sink,
                        vision_client=vision_client,
                    )
                )
                worker_tasks.append(task)

            results = await asyncio.gather(*worker_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    state.failed_workers += 1
                    state.errors.append(str(result))

            state.progress_pct = 100.0
            if state.cancelled:
                state.status = RunStatus.cancelled
            elif state.failed_workers > 0 and state.completed_workers == 0:
                state.status = RunStatus.failed
            else:
                state.status = RunStatus.completed

        except asyncio.CancelledError:
            state.status = RunStatus.cancelled
            state.request_cancel()
            raise
        except Exception as exc:
            state.status = RunStatus.failed
            state.errors.append(str(exc))
            await state.emit("run.error", {"error": str(exc)})
        finally:
            if not state.config.skip_user_provisioning:
                try:
                    await self.user_manager.cleanup_test_users(state.users, runtime_config=runtime_cfg)
                except Exception as cleanup_exc:  # noqa: BLE001
                    state.errors.append(f"cleanup error: {cleanup_exc}")

            # Run AI analysis on screenshots via claude/codex CLI
            ai_analysis = None
            try:
                analyzer = RunAnalyzer()
                ai_analysis = await analyzer.analyze_run(state.root_dir)
                if ai_analysis.error != "no_backend":
                    await state.emit(
                        "ai.analysis_complete",
                        {"verdict": ai_analysis.overall_verdict},
                    )
            except Exception as analysis_exc:  # noqa: BLE001
                state.errors.append(f"ai analysis error: {analysis_exc}")

            try:
                state.report_path = await self.reporter.generate(
                    state.run_id, state.root_dir, ai_analysis=ai_analysis,
                )
            except Exception as report_exc:  # noqa: BLE001
                state.errors.append(f"report error: {report_exc}")

            state.ended_at = datetime.now(UTC)
            await state.emit(
                "run.finished",
                {
                    "status": state.status.value,
                    "completed_workers": state.completed_workers,
                    "failed_workers": state.failed_workers,
                    "errors": state.errors,
                },
            )

    async def _run_worker(
        self,
        state: RunState,
        assignment,
        delay_seconds: float,
        semaphore: asyncio.Semaphore,
        screenshot_manager: ScreenshotManager,
        metric_sink,
        vision_client=None,
    ) -> None:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        async with semaphore:
            if state.cancelled:
                return

            # Use extension_url as the target when set (e.g., Kaizen app URL)
            effective_target = (
                state.config.extension_url
                or state.effective_kamiwaza_url
            )

            worker = Worker(
                run_id=state.run_id,
                assignment=assignment,
                settings=self.settings,
                screenshot_manager=screenshot_manager,
                metric_sink=metric_sink,
                event_sink=state.emit,
                component=state.config.component,
                guidance_context=(
                    state.uat_guidance.combined_context() if state.uat_guidance else ""
                ),
                target_url=effective_target,
                vision_client=vision_client,
                scenario_weights=state.config.scenario_weights,
                single_iteration=state.config.single_iteration,
                test_message=state.config.test_message,
            )
            try:
                await worker.run(
                    duration_seconds=state.config.duration_seconds,
                    cancel_event=state.cancel_event,
                )
                state.completed_workers += 1
            except asyncio.CancelledError:
                state.failed_workers += 1
                raise
            except Exception as exc:
                state.failed_workers += 1
                state.errors.append(f"{assignment.worker_id}: {exc}")
                await state.emit(
                    "worker.error",
                    {"worker_id": assignment.worker_id, "error": str(exc)},
                )
            finally:
                total = max(1, state.config.concurrent_users)
                done = state.completed_workers + state.failed_workers
                state.progress_pct = round((done / total) * 100.0, 2)

    def _summary(self, state: RunState) -> RunSummary:
        # Determine test type from config
        test_type = "kamiwaza"
        scenarios = state.config.scenarios or []
        if any(s.startswith("kaizen") for s in scenarios) or state.config.extension_url:
            test_type = "kaizen"

        return RunSummary(
            run_id=state.run_id,
            status=state.status,
            test_type=test_type,
            created_at=state.created_at,
            started_at=state.started_at,
            ended_at=state.ended_at,
            concurrent_users=state.config.concurrent_users,
            completed_workers=state.completed_workers,
            failed_workers=state.failed_workers,
        )

    def detail(self, state: RunState) -> RunDetail:
        return RunDetail(
            **self._summary(state).model_dump(),
            progress_pct=state.progress_pct,
            errors=state.errors,
            metrics_path=str(state.metrics_path) if state.metrics_path else None,
            event_log_path=str(state.event_log_path) if state.event_log_path else None,
            report_path=str(state.report_path) if state.report_path else None,
            users_created=len(state.users),
            component=state.config.component,
            uat_guidance_files=state.uat_guidance.file_paths if state.uat_guidance else [],
            effective_kamiwaza_url=state.effective_kamiwaza_url,
            auth_source=state.auth_source,
        )

    @staticmethod
    def _redacted_config(config: dict[str, Any]) -> dict[str, Any]:
        redacted = dict(config)
        for key in ("kamiwaza_admin_password", "kamiwaza_admin_token"):
            if key in redacted and redacted[key]:
                redacted[key] = "***redacted***"
        return redacted
