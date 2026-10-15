# -*- coding: utf-8 -*-
"""
MTS Phase 1–3: モデルごと backend＋1 ワーカースレッド ＋ 段階 A/B/C。

設計（docs/architecture.md「MTS（マルチモデル）」）:
  - 1 つの GeminiBackend を複数スレッドで共有しない
  - モデルごとに独立した backend が、担当仕事を直列処理する
  - 段階 A: 個別占術 main 52（lite / 最上位 flash）
  - 段階 B: クラスタ中間 11本を flash-lite 2 ワーカーで並列（503/空応答は未試行のliteへ一度だけ移譲）
  - 段階 C: 軸サマリー2＋最終1＋deities を最上位 flash 1 ワーカー（直列）
  - 段階 B は11本がそろわなければ Stage C に進ませない
  - profile_summary.json の追記は PipelineContext.summary_lock で直列化

MTS Stage A/B/C のみを提供し、単一backendの逐次実行経路は持たない。
"""
from __future__ import annotations

import json
import queue
import threading
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .backend import GeminiBackend, LLMBackend, MockBackend
from .batch import build_calc_results, build_profile_facts
from .batch_runner import PersonResult, _write_report, row_to_input, safe_id
from .clusters import get_clusters
from .data import load_json
from .pipeline import PipelineContext, run_divination
from .profile import normalize_input
from .registry import REGISTRY, main_slugs


_PLAN_CACHE: dict | None = None


def load_model_plan() -> dict:
    """data/model_plan.json を読む（プロセス内キャッシュ）。"""
    global _PLAN_CACHE
    if _PLAN_CACHE is None:
        _PLAN_CACHE = load_json("model_plan.json")
    return _PLAN_CACHE


def model_for_slug(slug: str, plan: dict | None = None) -> str | None:
    """slug の担当モデル。deferred（deities）は None。"""
    plan = plan or load_model_plan()
    if slug in plan.get("deferred", []):
        return None
    return plan["slug_to_model"].get(slug)


def group_slugs_by_model(slugs: list[str] | None = None,
                         plan: dict | None = None) -> dict[str, list[str]]:
    """モデル名 → 担当 slug 列。計画に無い slug は落とす（deities など）。"""
    plan = plan or load_model_plan()
    slugs = list(slugs if slugs is not None else main_slugs())
    grouped: dict[str, list[str]] = {m: [] for m in plan["models"]}
    for s in slugs:
        m = model_for_slug(s, plan)
        if m is None:
            continue
        if m not in grouped:
            grouped[m] = []
        grouped[m].append(s)
    return {m: v for m, v in grouped.items() if v}


def rpm_for_model(model_name: str, plan: dict | None = None) -> float:
    plan = plan or load_model_plan()
    models = plan.get("models") or {}
    spec = models.get(model_name)
    if not spec:
        from .backend import normalize_gemini_model_name
        spec = models.get(normalize_gemini_model_name(model_name))
    spec = spec or {}
    return float(spec.get("rpm") or 10.0)


def fallback_chain(model_name: str, plan: dict | None = None) -> list[str]:
    """このモデルが 503/空応答で失敗したあとの移譲先（順序どおり）。"""
    plan = plan or load_model_plan()
    models = plan.get("models") or {}
    spec = models.get(model_name)
    if not spec:
        from .backend import normalize_gemini_model_name
        spec = models.get(normalize_gemini_model_name(model_name))
    spec = spec or {}
    return [m for m in (spec.get("fallback") or []) if m and m != model_name]


def _is_stealable(result: dict | None = None,
                  exc: BaseException | None = None) -> bool:
    """503 / 408 / 空応答 / 応答の打ち切りだけを他モデルへ移譲する。

    致命 4xx や boom は移さない（別モデルへ回しても直らないため）。
    mts5.68: 408（Request Timeout＝サーバ側の無応答）も 503 と同じ「混雑」として
    移譲する（backend は 408 を 1 回だけ待って再試行し、2 回目で諦める）。
    """
    chunks = []
    if exc is not None:
        from .backend import ResponseTimeoutError
        if isinstance(exc, ResponseTimeoutError):
            return True
        chunks.append(str(exc))
        code = getattr(exc, "code", None)
        try:
            from .backend import _api_error_code
            code = _api_error_code(exc) if code is None else code
        except Exception:
            pass
        if code in (503, 408):
            return True
    if result:
        chunks.append(str(result.get("reason") or ""))
        if result.get("status") in ("ok", "skipped", "unavailable"):
            return False
    s = " ".join(chunks)
    if "503" in s or "UNAVAILABLE" in s or "high demand" in s.lower():
        return True
    if "408" in s or "request timeout" in s.lower():
        return True
    if "空" in s or "極端に短い" in s:
        return True
    return False


def _stealable_label(exc: BaseException | None) -> str:
    """移譲の理由を 1 語で（ログ用・mts5.68）。"""
    if exc is None:
        return "503/空応答"
    try:
        from .backend import ResponseTimeoutError
        if isinstance(exc, ResponseTimeoutError):
            return "応答の打ち切り"
    except Exception:
        pass
    s = str(exc)
    if "408" in s or "request timeout" in s.lower():
        return "408（無応答）"
    if "503" in s or "UNAVAILABLE" in s or "high demand" in s.lower():
        return "503"
    return "503/空応答"


def backoff_503_s(plan: dict | None = None) -> float:
    """503 のときに待つ秒数（mts5.11 で 20 → 5秒。既定 20 は後方互換）。

    指数バックオフには戻さない（2026-08-28 の実機教訓）。待つ回数は 1回のまま。
    """
    spec = (plan or load_model_plan()).get("reliability") or {}
    try:
        v = float(spec.get("backoff_503_s", 20.0))
    except (TypeError, ValueError):
        v = 20.0
    return v if v > 0 else 20.0


def stage_a_response_timeout(plan: dict | None = None) -> tuple[set[str], float | None]:
    """段階 A の「応答の打ち切り」設定（mts5.11）。

    `plan["stage_a"]["response_timeout"]` が無ければ (空集合, None)＝従来どおり
    応答が返るまで待つ。ある場合は `models` のレーンだけに `seconds` を適用し、
    超えたぶんは既存の移譲（fallback_chain）と同じ経路で別レーンへ回す。
    正常応答の上限（実測: 3.5-lite 約10秒・3.1-lite 約6秒）より十分大きい値を
    既定にする（mts5.9 の実測では 20秒で切ると Stage A が −30%）。
    """
    sa = (plan or load_model_plan()).get("stage_a") or {}
    spec = sa.get("response_timeout") or {}
    models = {m for m in (spec.get("models") or []) if m}
    if not models:
        return set(), None
    try:
        sec = float(spec.get("seconds") or 0)
    except (TypeError, ValueError):
        sec = 0.0
    if sec <= 0:
        return set(), None
    return models, sec


def stage_c_response_timeout(plan: dict | None = None) -> tuple[set[str], float | None]:
    """段階 C の「応答の打ち切り」設定（mts5.68）。

    `plan["stage_c"]["response_timeout"]` が無ければ (空集合, None)＝従来どおり
    応答が返るまで待つ。ある場合は `models` のレーン（既定: 混雑しやすい上位 Flash
    3.8 / 3.6）だけに `seconds` を適用し、超えたぶんは既存の移譲（fallback）と同じ
    経路で次のモデルへ回す。mts5.67 の実機では 3.8-flash が 503 のあと **約 100 秒
    無応答 → 408** を 3 回繰り返し、段階 C の 502 秒のうち約 425 秒が待ち時間だった。
    """
    sc = (plan or load_model_plan()).get("stage_c") or {}
    spec = sc.get("response_timeout") or {}
    models = {m for m in (spec.get("models") or []) if m}
    if not models:
        return set(), None
    try:
        sec = float(spec.get("seconds") or 0)
    except (TypeError, ValueError):
        sec = 0.0
    if sec <= 0:
        return set(), None
    return models, sec


def stage_a_pull_plan(plan: dict | None = None) -> tuple[set[str], int]:
    """段階 A のアイドル・スティール設定（mts5.8）。

    `plan["stage_a"]["pull"]` が無ければ**無効**（＝従来どおり、各レーンは自分の
    担当だけを実行する）。設定がある場合、`models` に列挙したレーンだけが
    引き取り手になり、引き取り元も同じ `models` のレーンに限る。残りが
    `min_backlog` 件未満のレーンからは取らない（終わり際の取り合いを防ぐ）。
    """
    sa = (plan or load_model_plan()).get("stage_a") or {}
    spec = sa.get("pull") or {}
    models = {m for m in (spec.get("models") or []) if m}
    if not models:
        return set(), 0
    try:
        min_backlog = int(spec.get("min_backlog") or 3)
    except (TypeError, ValueError):
        min_backlog = 3
    return models, max(min_backlog, 1)


def make_gemini_backend(model_name: str, plan: dict | None = None,
                        **kwargs) -> GeminiBackend:
    """モデル名に応じた RPM・503の待機で GeminiBackend を1つ作る（スレッド専有用）。"""
    kw = dict(kwargs)
    kw.setdefault("requests_per_minute", rpm_for_model(model_name))
    kw.setdefault("backoff_base_s", backoff_503_s(plan))
    kw.setdefault("model_name", model_name)
    return GeminiBackend(**kw)


def make_mock_backends(plan: dict | None = None) -> dict[str, MockBackend]:
    """テスト用: モデルごとに独立した MockBackend。"""
    plan = plan or load_model_plan()
    return {m: MockBackend() for m in plan["models"]}


def _atomic_write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


@dataclass
class WorkerProgress:
    model: str
    total: int
    done: int = 0
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    unavailable: int = 0
    current_slug: str = ""
    last_error: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    slug_started_at: float | None = None
    pulled: int = 0                               # 他レーンから引き取った件数（mts5.8）
    handed_over: int = 0                          # 最終結果を待つタスクの移譲イベント数（mts5.47）
    history: list = field(default_factory=list)  # {slug, status, sec}


class Progress:
    """main が監視する共有進捗（Lock 付き）。"""

    def __init__(self, stage: str = "A"):
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self.workers: dict[str, WorkerProgress] = {}
        self.stage = stage
        self.t0 = time.monotonic()
        self._all_complete = threading.Event()
        self._steal_open = 0
        self._pull_open = 0        # 引き取り中（アイドル・スティール）の件数
        self._pull_started_at: dict[str, float] = {}
        self.pulls: list[dict] = []
        # 応答の打ち切り（mts5.11）: どのスラッグをどのレーンで切ったか
        self.timeouts: list[dict] = []

    def register(self, model: str, total: int) -> None:
        with self._cv:
            now = time.monotonic()
            self.workers[model] = WorkerProgress(
                model=model, total=total, started_at=now)
            self._all_complete.clear()
            self._cv.notify_all()

    def start_slug(self, model: str, slug: str) -> None:
        with self._cv:
            w = self.workers[model]
            w.current_slug = slug
            w.slug_started_at = time.monotonic()
            self._cv.notify_all()

    def _record_final_unlocked(self, w: WorkerProgress, slug: str,
                               status: str, error: str = "",
                               sec: float | None = None,
                               run_model: str | None = None,
                               pulled_by: str | None = None) -> None:
        """1つの割当タスクの最終結果を所有レーンへ記録する。Lock保持中。"""
        now = time.monotonic()
        if (sec is None and w.slug_started_at is not None
                and (not slug or w.current_slug == slug)):
            sec = round(now - w.slug_started_at, 3)
        st = status or "error"
        w.done += 1
        if st == "ok":
            w.ok += 1
        elif st == "skipped":
            w.skipped += 1
        elif st == "unavailable":
            w.unavailable += 1
        else:
            w.failed += 1
            w.last_error = error or st
        if not slug or w.current_slug == slug:
            w.current_slug = ""
            w.slug_started_at = None
        item = {"slug": slug, "status": st, "sec": sec}
        if error:
            item["error"] = error
        if run_model and run_model != w.model:
            item["run_model"] = run_model
        if pulled_by:
            item["pulled_by"] = pulled_by
        w.history.append(item)
        if w.done >= w.total:
            w.finished_at = now

    def _record_handover_unlocked(self, model: str, slug: str,
                                  error: str = "",
                                  run_model: str | None = None,
                                  sec: float | None = None) -> None:
        """未完了タスクの移譲イベントだけを記録（done/結果カウンタは増やさない）。"""
        w = self.workers.get(model)
        if w is None:
            return
        now = time.monotonic()
        if (sec is None and w.slug_started_at is not None
                and w.current_slug == slug):
            sec = round(now - w.slug_started_at, 3)
        w.handed_over += 1
        if w.current_slug == slug:
            w.current_slug = ""
            w.slug_started_at = None
        item = {"slug": slug, "status": "stolen", "sec": sec,
                "handed_over": True}
        if error:
            item["error"] = error
        if run_model and run_model != model:
            item["run_model"] = run_model
        w.history.append(item)
        if w.done >= w.total:
            w.finished_at = now

    def finish_slug(self, model: str, status: str, error: str = "") -> None:
        """現在の担当タスクの最終結果を記録する。"""
        with self._cv:
            w = self.workers[model]
            self._record_final_unlocked(w, w.current_slug, status, error)
            if self._is_all_done_unlocked():
                self._all_complete.set()
            self._cv.notify_all()

    def finish_slug_named(self, model: str, slug: str, status: str,
                          error: str = "") -> None:
        """slug 名付きで最終結果を記録する。"""
        with self._cv:
            w = self.workers[model]
            self._record_final_unlocked(w, slug, status, error)
            if self._is_all_done_unlocked():
                self._all_complete.set()
            self._cv.notify_all()

    def finish_task(self, owner: str, run_model: str, slug: str,
                    status: str, error: str = "",
                    pulled_by: str | None = None) -> None:
        """転送後に確定したタスク結果を、元の割当レーンへ一度だけ計上する。"""
        with self._cv:
            w = self.workers.get(owner)
            if w is not None:
                self._record_final_unlocked(
                    w, slug, status, error, run_model=run_model,
                    pulled_by=pulled_by)
            if self._is_all_done_unlocked():
                self._all_complete.set()
            self._cv.notify_all()

    def steal_enqueued(self, n: int = 1) -> None:
        with self._cv:
            self._steal_open += n
            self._all_complete.clear()
            self._cv.notify_all()

    def steal_finished(self, n: int = 1) -> None:
        with self._cv:
            self._steal_open = max(0, self._steal_open - n)
            if self._is_all_done_unlocked():
                self._all_complete.set()
            self._cv.notify_all()

    def steal_pending(self) -> int:
        with self._lock:
            return self._steal_open

    def handover_finished(self, model: str, slug: str,
                          error: str = "",
                          run_model: str | None = None) -> None:
        """移譲イベントを記録するが、タスクの最終結果カウンタは保留する。"""
        with self._cv:
            self._record_handover_unlocked(
                model, slug, error=error, run_model=run_model)
            if self._is_all_done_unlocked():
                self._all_complete.set()
            self._cv.notify_all()

    def timeout_recorded(self, model: str, slug: str) -> None:
        """応答の打ち切り（mts5.11）。切った件は別レーンへ移譲される。"""
        with self._cv:
            self.timeouts.append({"slug": slug, "from_model": model})
            self._cv.notify_all()

    def pull_started(self, origin: str, by: str, slug: str) -> None:
        """アイドル・スティール: origin レーンの残りを by レーンが引き取り開始。"""
        with self._cv:
            self._pull_open += 1
            self._pull_started_at[slug] = time.monotonic()
            self._all_complete.clear()
            self._cv.notify_all()

    def pull_finished(self, origin: str, by: str, slug: str, status: str,
                      error: str = "", sec: float | None = None,
                      owner_model: str | None = None) -> None:
        """引き取り試行を閉じ、最終結果だけを元の割当レーンへ反映する。

        status="stolen" は次のモデルへ再移譲した中間状態なので done/成功/失敗を
        増やさない。引き取り元（by）と最終実行者は pulls/history に残す。
        """
        with self._cv:
            self._pull_open = max(0, self._pull_open - 1)
            t0 = self._pull_started_at.pop(slug, None)
            if sec is None and t0 is not None:
                sec = round(time.monotonic() - t0, 3)
            st = status or "error"
            owner = owner_model or origin
            if st == "stolen":
                self._record_handover_unlocked(
                    owner, slug, error=error, run_model=by, sec=sec)
            else:
                w = self.workers.get(owner)
                if w is not None:
                    self._record_final_unlocked(
                        w, slug, st, error, sec=sec,
                        run_model=by, pulled_by=by)
            bw = self.workers.get(by)
            if bw is not None:
                bw.pulled += 1
            event = {"slug": slug, "from_model": origin, "by_model": by,
                     "status": st, "final": st != "stolen",
                     "sec": sec, "error": error}
            if owner != origin:
                event["owner_model"] = owner
            self.pulls.append(event)
            if self._is_all_done_unlocked():
                self._all_complete.set()
            self._cv.notify_all()

    def pull_pending(self) -> int:
        with self._lock:
            return self._pull_open

    def _is_all_done_unlocked(self) -> bool:
        real = [w for w in self.workers.values() if w.total > 0]
        if not real:
            return False
        return (all(w.done >= w.total for w in real)
                and self._steal_open <= 0
                and self._pull_open <= 0)

    def all_done(self) -> bool:
        with self._lock:
            return self._is_all_done_unlocked()

    def wait_all(self, timeout: float | None = None) -> bool:
        """全ワーカー完了を待つ。完了なら True。"""
        return self._all_complete.wait(timeout)

    def totals(self) -> dict:
        with self._lock:
            return self._totals_unlocked()

    def _totals_unlocked(self) -> dict:
        t = {"total": 0, "done": 0, "ok": 0, "failed": 0,
             "skipped": 0, "unavailable": 0}
        for w in self.workers.values():
            t["total"] += w.total
            t["done"] += w.done
            t["ok"] += w.ok
            t["failed"] += w.failed
            t["skipped"] += w.skipped
            t["unavailable"] += w.unavailable
        return t

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = round(time.monotonic() - self.t0, 3)
            tot = self._totals_unlocked()
            remaining = max(tot["total"] - tot["done"], 0)
            eta = None
            if tot["done"] > 0 and remaining > 0 and elapsed > 0:
                eta = round(elapsed / tot["done"] * remaining, 1)
            workers = {}
            for m, w in self.workers.items():
                w_elapsed = None
                if w.started_at is not None:
                    end = w.finished_at if w.finished_at else time.monotonic()
                    w_elapsed = round(end - w.started_at, 3)
                workers[m] = {
                    "total": w.total, "done": w.done, "ok": w.ok,
                    "failed": w.failed, "skipped": w.skipped,
                    "unavailable": w.unavailable,
                    "current_slug": w.current_slug, "last_error": w.last_error,
                    "elapsed_s": w_elapsed,
                    "finished": w.finished_at is not None,
                    "pulled": w.pulled,
                    "handed_over": w.handed_over,
                    "history": list(w.history[-8:]),
                }
            return {
                "stage": self.stage,
                "elapsed_s": elapsed,
                "eta_s": eta,
                "all_done": self._is_all_done_unlocked(),
                "totals": tot,
                "workers": workers,
                "handover_events": sum(w.handed_over for w in self.workers.values()),
                "pull_open": self._pull_open,
                "pulls": list(self.pulls),
                "timeouts": list(self.timeouts),
            }

    def format_status(self) -> str:
        snap = self.snapshot()
        tot = snap["totals"]
        eta = snap["eta_s"]
        eta_s = f" ETA {eta:.0f}s" if eta is not None else ""
        parts = [f"[MTS {snap['stage']}] {tot['done']}/{tot['total']}  "
                 f"{snap['elapsed_s']:.1f}s{eta_s}"]
        for m, w in snap["workers"].items():
            short = m.replace("gemini-", "")
            cur = w["current_slug"] or ("done" if w["finished"] else "-")
            fail = f" fail={w['failed']}" if w["failed"] else ""
            pulled = f" ⇦{w['pulled']}" if w.get("pulled") else ""
            parts.append(f"  {short} {w['done']}/{w['total']} {cur}{fail}{pulled}")
            ho = f" ⏱{w['handed_over']}" if w.get("handed_over") else ""
            if ho:
                parts[-1] = parts[-1] + ho
        n_to = len(snap.get("timeouts") or [])
        if n_to:
            parts.append(f"  ⏱ 打ち切り {n_to}件（別レーンへ移譲）")
        return "\n".join(parts)

    def write_json(self, path) -> Path:
        p = Path(path)
        _atomic_write_json(p, self.snapshot())
        return p


class ProgressMonitor:
    """ハートビート: 定期的に progress.json を書き、任意で行を印字する。"""

    def __init__(self, progress: Progress, path=None,
                 interval_s: float = 2.0, verbose: bool = False):
        self.progress = progress
        self.path = Path(path) if path else None
        self.interval_s = max(float(interval_s), 0.05)
        self.verbose = verbose
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.tick()
            if self.progress.all_done():
                break
        self.tick()  # 最終スナップショット

    def tick(self) -> dict:
        snap = self.progress.snapshot()
        if self.path is not None:
            self.progress.write_json(self.path)
        if self.verbose:
            print(self.progress.format_status(), flush=True)
        return snap

    def start(self) -> ProgressMonitor:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="mts-monitor", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_s + 1.0)
            self._thread = None
        self.tick()

    def __enter__(self) -> ProgressMonitor:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def scan_results_dir(results_dir) -> dict:
    """結果フォルダの *.md（_raw 以外）を数える（フォルダ監視用）。"""
    d = Path(results_dir)
    if not d.is_dir():
        return {"dir": str(d), "exists": False, "md": [], "n": 0}
    mds = sorted(p.stem for p in d.glob("*.md") if "_raw" not in p.name)
    return {"dir": str(d), "exists": True, "md": mds, "n": len(mds)}


def verify_stage_a_files(results_dir, slugs: list[str] | None = None) -> dict:
    """段階 A の期待 slug と、ディスク上の結果ファイルを照合する。"""
    slugs = list(slugs if slugs is not None else main_slugs())
    scan = scan_results_dir(results_dir)
    found_slugs = set()
    for stem in scan["md"]:
        # M01_eto → eto
        if "_" in stem:
            found_slugs.add(stem.split("_", 1)[1])
        else:
            found_slugs.add(stem)
    missing = [s for s in slugs if s not in found_slugs]
    extra = sorted(found_slugs - set(slugs))
    return {
        "expected": len(slugs),
        "found": len(found_slugs & set(slugs)),
        "missing": missing,
        "extra": extra,
        "complete": not missing,
    }


def run_slugs_mts(slugs: list[str], ctx: PipelineContext,
                  backends: dict[str, LLMBackend],
                  plan: dict | None = None,
                  progress: Progress | None = None,
                  verbose: bool = False,
                  monitor_path=None,
                  heartbeat_s: float | None = None) -> list[dict]:
    """段階 A: slug をモデル別のレーンに振り、レーンごと 1 スレッドで直列実行する。

    503 / 空応答は担当モデルで `reliability.backoff_503_s` 秒（mts5.11 で 20 → 5秒）
    ×1 のあと、fallback 先のアイドルワーカーへ移譲する（backend はスレッド間で
    共有しない）。**mts5.11 追加（応答の打ち切り）**: `stage_a.response_timeout` に
    列挙した lite レーンでは、1回の生成が `seconds` 秒を超えたら**そこで打ち切り**、
    503 と同じ経路で別レーンへ回す（mts5.9 の実測では、エラーを伴わない77秒の応答が
    Stage A 264秒の律速だった。20秒で切ると Stage A が約 −30%）。打ち切った件は
    progress の `timeouts` と結果の `timed_out: true` に残す。

    **mts5.8 追加（アイドル・スティール）**: 自分の担当を終えたレーンは、別の
    レーンに十分な残り（`stage_a.pull.min_backlog` 件以上）があるときにかぎり、
    その残りを1件ずつ引き取って**自分の backend** で実行する。遅いレーンが残りを
    抱えて走り、速いレーンが遊ぶ（mts5.7 の実測では 3.5-lite が約177秒待機）のを
    防ぐのが目的。引き取りは `stage_a.pull.models` に列挙した lite のレーンどうしで
    だけ起こり（プレミアム・モデルは引き取り手にも引き取り元にもしない）、
    集計は**元のレーン**に加算する（二重計上しない）。設定が無ければ従来どおり。
    """
    plan = plan or load_model_plan()
    if ctx.summary_lock is None:
        ctx.summary_lock = threading.Lock()
    grouped = group_slugs_by_model(slugs, plan)
    prog = progress or Progress()
    for model, assigned in grouped.items():
        if model not in backends:
            raise KeyError(f"backend が無いモデル: {model}")
        prog.register(model, len(assigned))

    # アイドル・スティール（mts5.8）。設定が無ければ空集合＝従来どおり。
    pull_models, pull_min = stage_a_pull_plan(plan)
    # 応答の打ち切り（mts5.11）。回し先が無い（レーンが1本）ときは効かせない。
    to_models, to_s = stage_a_response_timeout(plan)
    if len([m for m in to_models if m in backends]) < 2:
        to_models, to_s = set(), None

    results: list[dict] = []
    results_lock = threading.Lock()
    steal_qs: dict[str, queue.Queue] = {
        m: queue.Queue() for m in backends if m in (plan.get("models") or {})
    }
    cv = threading.Condition()
    inflight = 0
    fatal: list[BaseException] = []   # 想定外の例外（他レーンを止めて主スレッドで再送出）
    stop = threading.Event()

    # 一次担当はレーンごとのキューにする（アイドル・スティールが他レーンから取り出す）
    worker_models: list[str] = []
    seen: set[str] = set()
    for m in list(grouped) + [m for m in (plan.get("models") or {})
                              if m in backends]:
        if m in seen or m not in backends:
            continue
        seen.add(m)
        worker_models.append(m)
    primary_qs: dict[str, queue.Queue] = {m: queue.Queue() for m in worker_models}
    for m, assigned in grouped.items():
        for s in assigned:
            primary_qs[m].put(s)

    def _enqueue_steal(slug: str, from_model: str, attempted: frozenset[str],
                       meta: dict | None = None) -> bool:
        chain = fallback_chain(from_model, plan)
        for nxt in chain:
            if (nxt in steal_qs and nxt in backends and nxt != from_model
                    and nxt not in attempted):
                payload = dict(meta or {})
                payload.setdefault("owner_model", from_model)
                payload.setdefault("origin_model", payload["owner_model"])
                payload["from_model"] = from_model
                steal_qs[nxt].put((slug, attempted | {from_model}, payload))
                prog.steal_enqueued(1)
                with cv:
                    cv.notify_all()
                if verbose:
                    name = REGISTRY[slug]["name"]
                    print(f"  ↪ 移譲 {name}: {from_model} → {nxt}")
                return True
        return False

    def _pick_backlog(exclude: str) -> tuple[str, str] | None:
        """引き取り元（残りが最も多い lite レーン）から1件取り出す。

        - 引き取り手になれるのは `stage_a.pull.models` のレーンだけ（空のレーンも
          含む＝自分の担当が終わったレーン）。
        - 残りが `pull_min` 件未満のレーンからは取らない（終わり際の取り合いを防ぐ）。
        """
        if not pull_models or exclude not in pull_models:
            return None
        victim, backlog = None, 0
        for m, q in primary_qs.items():
            if m == exclude or m not in pull_models:
                continue
            n = q.qsize()
            if n > backlog:
                victim, backlog = m, n
        if victim is None or backlog < pull_min:
            return None
        try:
            slug = primary_qs[victim].get_nowait()
        except queue.Empty:      # 別レーンが先に取り出した
            return None
        return victim, slug

    def _run_one(model: str, slug: str, *, stolen: bool,
                 attempted: frozenset[str] | None = None,
                 pulled_from: str | None = None,
                 meta: dict | None = None) -> dict:
        be = backends[model]
        name = REGISTRY[slug]["name"]
        owner_model = ((meta or {}).get("owner_model") or pulled_from or model)
        if attempted is None:
            attempted = frozenset({model})
        if pulled_from is not None:
            prog.pull_started(pulled_from, model, slug)
        elif not stolen:
            prog.start_slug(model, slug)

        def _close(status: str, error: str = "") -> None:
            """最終結果を元の割当レーンへ計上し、移譲中カウンタを閉じる。"""
            if pulled_from is not None:
                prog.pull_finished(pulled_from, model, slug, status,
                                   error=error, owner_model=owner_model)
            elif stolen:
                prog.finish_task(
                    owner_model, model, slug, status, error=error,
                    pulled_by=(meta or {}).get("pulled_by"))
                prog.steal_finished(1)
            else:
                prog.finish_slug_named(model, slug, status, error=error)

        def _hand_over(reason: str) -> None:
            """中間移譲を記録する。タスクの最終結果カウンタは保留する。"""
            if pulled_from is not None:
                prog.pull_finished(pulled_from, model, slug, "stolen",
                                   error=reason, owner_model=owner_model)
            else:
                prog.handover_finished(
                    owner_model, slug, error=reason, run_model=model)
                if stolen:
                    prog.steal_finished(1)

        timed_out = False
        prev_to = getattr(be, "response_timeout_s", None)
        if to_s and model in to_models:
            be.response_timeout_s = to_s
        try:
            try:
                r = run_divination(slug, ctx, backend=be, model_hint=model)
            finally:
                if to_s and model in to_models:
                    be.response_timeout_s = prev_to
        except Exception as e:
            from .backend import ResponseTimeoutError
            timed_out = isinstance(e, ResponseTimeoutError)
            r = {"status": "error", "slug": slug,
                 "reason": f"{type(e).__name__}: {e}"}
            steal = _is_stealable(r, e)
            if verbose:
                print(f"  ⚠ [{model}] {name}: {r['reason']}")
                if not timed_out:
                    traceback.print_exc(limit=1)
            payload_meta = dict(meta or {})
            payload_meta.setdefault("owner_model", owner_model)
            if pulled_from is not None:
                payload_meta.setdefault("pulled", True)
                payload_meta.setdefault("pulled_by", model)
            if timed_out:
                payload_meta["timed_out"] = True
            if steal and _enqueue_steal(slug, model, attempted,
                                        payload_meta or None):
                if timed_out:
                    prog.timeout_recorded(model, slug)
                    if verbose:
                        print(f"  ⏱ 打ち切り {name}: {model} → 別レーンへ")
                _hand_over(r.get("reason") or "")
                return {"status": "stolen", "slug": slug, "reason": r["reason"],
                        "timed_out": timed_out, "from_model": model}
            _close(r.get("status") or "error", error=r.get("reason") or "")
            return r
        st = r.get("status")
        steal = _is_stealable(r, None)
        if verbose:
            if st == "ok":
                extra = f"（再生成: {r['issues']}）" if r.get("issues") else ""
                if pulled_from is not None:
                    tag = f"引き取り {pulled_from}→{model} "
                else:
                    tag = "移譲後 " if stolen else ""
                print(f"  ✅ [{model}] {tag}{name}{extra}")
            elif st == "unavailable":
                print(f"  − [{model}] {name}: 対象外（{r.get('reason')}）")
            elif st != "skipped":
                print(f"  ⚠ [{model}] {name}: {r.get('reason')}")
        payload_meta = dict(meta or {})
        payload_meta.setdefault("owner_model", owner_model)
        if pulled_from is not None:
            payload_meta.setdefault("pulled", True)
            payload_meta.setdefault("pulled_by", model)
        if steal and _enqueue_steal(slug, model, attempted, payload_meta):
            _hand_over(r.get("reason") or "")
            return {"status": "stolen", "slug": slug,
                    "reason": r.get("reason") or ""}
        _close(st or "error", error=r.get("reason") or "")
        if pulled_from is not None or meta or stolen:
            r.setdefault("run_model", model)
            r.setdefault("owner_model", owner_model)
        if pulled_from is not None:
            r.setdefault("pulled_from", pulled_from)
        elif (meta or {}).get("pulled"):
            r.setdefault("pulled_from", owner_model)
        if meta:
            if meta.get("from_model"):
                r.setdefault("stolen_from", meta["from_model"])
            if meta.get("timed_out"):
                r.setdefault("timed_out", True)
        return r

    def _queues_empty() -> bool:
        return all(q.empty() for q in steal_qs.values())

    def _primary_empty() -> bool:
        return all(q.empty() for q in primary_qs.values())

    def _idle_unlocked() -> bool:
        """全レーンが静かになったか（自分の進捗ロック保持中に呼ぶ）。"""
        return (inflight <= 0 and _primary_empty() and _queues_empty()
                and prog.steal_pending() <= 0 and prog.pull_pending() <= 0)

    def _worker(model: str) -> None:
        nonlocal inflight
        try:
            _worker_body(model)
        except BaseException as e:      # 想定外の例外はレーンを止めて上へ渡す
            with cv:
                fatal.append(e)
                stop.set()
                cv.notify_all()

    def _worker_body(model: str) -> None:
        nonlocal inflight
        my_q = primary_qs.get(model)
        my_steal = steal_qs.get(model)

        def _process(slug: str, *, stolen: bool,
                     attempted: frozenset[str] | None = None,
                     pulled_from: str | None = None,
                     meta: dict | None = None) -> dict:
            nonlocal inflight
            with cv:
                inflight += 1
            try:
                return _run_one(model, slug, stolen=stolen,
                                attempted=attempted, pulled_from=pulled_from,
                                meta=meta)
            finally:
                with cv:
                    inflight -= 1
                    cv.notify_all()

        # ① 自分の担当（他レーンが引き取っていれば、その分だけ短くなる）
        if my_q is not None:
            while True:
                try:
                    slug = my_q.get_nowait()
                except queue.Empty:
                    break
                if stop.is_set():
                    return
                r = _process(slug, stolen=False)
                if r.get("status") != "stolen":
                    with results_lock:
                        results.append(r)

        if my_steal is None:
            return

        while True:
            # ② 503 で回ってきた仕事（移譲）を先に拾う
            try:
                item = my_steal.get_nowait()
            except queue.Empty:
                item = None
            if item is not None:
                payload = item[2] if len(item) > 2 else None
                slug, attempted = item[0], item[1]
                if verbose and payload and payload.get("timed_out"):
                    print(f"  ⏱ 引き受け {REGISTRY[slug]['name']}: "
                          f"{payload.get('from_model')} → {model}")
                r = _process(slug, stolen=True, attempted=attempted,
                             meta=payload)
                if r.get("status") != "stolen":
                    with results_lock:
                        results.append(r)
                continue
            # ③ アイドル・スティール: 残っているレーンの仕事を引き取る
            picked = _pick_backlog(model)
            if picked is not None:
                origin, slug = picked
                if verbose:
                    print(f"  ⇦ 引き取り {REGISTRY[slug]['name']}: {origin} → {model}")
                r = _process(slug, stolen=True,
                             attempted=frozenset({origin, model}),
                             pulled_from=origin,
                             meta={"from_model": origin, "owner_model": origin,
                                   "pulled": True, "pulled_by": model})
                if r.get("status") != "stolen":
                    with results_lock:
                        results.append(r)
                continue
            # ④ 何も無ければ待つ（全レーン完了・実行中0・キュー空で終了）
            with cv:
                if stop.is_set() or _idle_unlocked():
                    return
                cv.wait(timeout=0.2)
                if stop.is_set() or _idle_unlocked():
                    return

    mon = None
    if monitor_path is not None or heartbeat_s:
        mon = ProgressMonitor(
            prog, path=monitor_path,
            interval_s=heartbeat_s or 2.0, verbose=verbose)
        mon.start()

    try:
        n_workers = max(len(worker_models), 1)
        with ThreadPoolExecutor(max_workers=n_workers,
                                thread_name_prefix="mts") as ex:
            futs = [ex.submit(_worker, m) for m in worker_models]
            for f in as_completed(futs):
                f.result()
        if fatal:
            raise fatal[0]
        prog.wait_all(timeout=1.0)
        if verbose:
            _print_lane_summary(prog)
    finally:
        if mon is not None:
            mon.stop()
    return results


def _print_lane_summary(prog: "Progress", plan: dict | None = None) -> None:
    """段階Aの**レーン別の内訳**を1行で出す（mts5.65）。

    ご指摘「ログを見ると 3.5-flash-lite に偏っている」を受け、担当（割当）・
    引き取り・移譲・打ち切りをレーンごとに可視化する。合計だけでは
    「どちらのレーンが何件さばいたか」が分からず、偏りの実体を読み違えるため。
    """
    plan = plan or load_model_plan()
    snap = prog.snapshot()
    workers = snap.get("workers") or {}
    timeouts = Counter(str(x.get("from_model") or "")
                       for x in (snap.get("timeouts") or []))
    parts = []
    for model in (plan.get("models") or {}):
        w = workers.get(model)
        if not w:
            continue
        parts.append(
            f"{model} {w.get('done', 0)}件"
            f"（担当{w.get('total', 0)}・引取{w.get('pulled', 0)}"
            f"・移譲{w.get('handed_over', 0)}・打切り{timeouts.get(model, 0)}）")
    if not parts:
        return
    total = (snap.get("totals") or {}).get("done", 0)
    print(f"  📊 段階A レーン別: " + " ／ ".join(parts) + f" ＝ 合計{total}件")


def run_person_mts(row: dict, backends: dict[str, LLMBackend], out_root: Path,
                   session_prefix: str = "mts", seed: int | None = None,
                   verbose: bool = True,
                   progress: Progress | None = None,
                   monitor: bool = True,
                   stages: str | tuple = "A") -> PersonResult:
    """1 人分を MTS で実行する。

    stages 既定は \"A\"（main 52・deities なし）。\"ABC\" で段階 B/C まで。
    monitor=True なら out_dir/progress.json にハートビートを書く。
    """
    try:
        from . import runcheck as _runcheck
        _warn_mark = [len(_runcheck.WARNINGS)]        # mts5.53（P-10）: 人ごとの警告の目印
    except Exception:
        _warn_mark = [0]
    try:
        # mts5.55: 再利用の内訳（SKIP_STATS）はプロセス共通。前の実行（Kaggle ではセルフテスト）の
        # 数値を持ち越すと「この人がしていない再利用」がログと警告に出るため、人ごとに戻す。
        from .pipeline import reset_skip_stats as _reset_skip_stats
        _reset_skip_stats()
    except Exception:
        pass
    pid = safe_id(row.get("person_id", ""), row.get("_index", 1))
    out_dir = Path(out_root) / pid
    results_dir = out_dir / "results"
    summary_path = out_dir / "profile_summary.json"
    results_dir.mkdir(parents=True, exist_ok=True)

    raw_input = row_to_input(row)
    ni = normalize_input(raw_input)
    today_mode = not ni.consultation
    res = PersonResult(person_id=pid, today_mode=today_mode,
                       results_dir=str(results_dir))

    if verbose:
        mode = "今日の運勢モード" if today_mode else f"相談: {ni.consultation[:24]}"
        print(f"\n{'=' * 56}\n▶ {pid}  {ni.birth.date}  {mode}  [MTS]\n{'=' * 56}")

    # mts5.31: 素の datetime.now() は**実行環境のタイムゾーン**（Kaggle は UTC）になり、
    # 「今日の運勢」の対象日が日本時間と1日ずれる（00:00〜08:59 JST の実行）。
    # 他のモジュールと同じく JST を明示する。
    from .rng import JST as _JST
    now = datetime.now(_JST)
    facts = build_profile_facts(ni)
    calc = build_calc_results(ni, session_id=f"{session_prefix}-{pid}",
                              consultation=ni.consultation, now=now)

    ctx = PipelineContext(
        inputs=ni, profile_facts=facts, calc_results=calc,
        consultation=ni.consultation, results_dir=results_dir,
        summary_path=summary_path, backend=None, seed=seed,
        summary_lock=threading.Lock(),
    )

    want = _normalize_stages(stages)
    prog = progress or Progress(stage="A")
    mon_path = (out_dir / "progress.json") if monitor else None
    items: list[dict] = []
    if "A" in want:
        items = run_slugs_mts(
            list(main_slugs()), ctx, backends,
            progress=prog, verbose=verbose,
            monitor_path=mon_path, heartbeat_s=2.0 if monitor else None)
    for r in items:
        st = r.get("status")
        if st == "ok":
            res.ok += 1
        elif st == "skipped":
            res.skipped += 1
        elif st == "unavailable":
            res.unavailable += 1
        else:
            res.error += 1
            res.failed.append(r.get("slug") or "")

    check = verify_stage_a_files(results_dir, list(main_slugs()))
    # mts5.53（P-3）: 監査の指摘＝この照合結果は profile_summary.json に記録されるだけで、
    # 欠落があっても**黙って続行**していた（Stage B/C は欠けた結果のまま合成へ進む）。
    if check["missing"]:
        _msg = (f"段階Aの成果物が不足しています（{check['found']}/{check['expected']}）: "
                + ", ".join(check["missing"][:12])
                + (" ほか" if len(check["missing"]) > 12 else ""))
        print(f"  ⚠ {_msg}")
        try:
            from .runcheck import add_warning
            add_warning(_msg)
        except Exception:
            pass
    try:
        payload = {}
        if summary_path.exists():
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        payload["input_raw"] = raw_input
        payload["mts"] = {
            "plan": load_model_plan().get("version"),
            "progress": prog.snapshot(),
            "files": check,
        }
        summary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    if mon_path:
        prog.write_json(mon_path)

    res.report = str(_write_report(out_dir, pid, facts, summary_path))
    # mts5.53（P-2）: 「再利用」は必ずログに残す（指紋一致／旧版／入力変更で再生成）。
    try:
        from .pipeline import SKIP_STATS, skip_stats_total as _skip_total
        _sk = dict(SKIP_STATS)
    except Exception:
        _sk = {}

        def _skip_total(stats=None):      # pragma: no cover - 異常系のフォールバック
            return 0
    if res.skipped or _skip_total(_sk):
        print(f"  ↺ 再利用 {res.skipped}件（この人の分: 入力指紋が一致 {_sk.get('fingerprint_match', 0)}"
              f" / 旧版で照合不能 {_sk.get('no_fingerprint', 0)}）"
              f" / 入力変更で作り直し {_sk.get('stale_regenerated', 0)}件")
        if _sk.get("no_fingerprint"):
            try:
                from .runcheck import add_warning
                add_warning(f"入力指紋の無い旧版の成果物を {_sk['no_fingerprint']}件 再利用しました"
                            "（入力が変わっていても検出できません。作り直すと指紋が付きます）")
            except Exception:
                pass
    if verbose:
        print(f"  → 完了 {res.ok}件 / スキップ {res.skipped} / 対象外 "
              f"{res.unavailable} / 失敗 {res.error}")
        if check["missing"]:
            print(f"  → フォルダ照合 欠落: {check['missing']}")
        print(f"  → レポート: {res.report}")

    if "B" in want or "C" in want:
        tdate = ""
        td = calc.get("target_date") if isinstance(calc, dict) else None
        # mts4.1表示層ゲート: 相談あり＋対象日空欄なら Stage B/C プロンプトへ
        # 対象日を渡さない（明示指定は ni から導出。calc スキーマは不変）。
        if isinstance(td, dict) and (today_mode or ni.target_date is not None):
            tdate = td.get("date") or ""
        syn_res = None
        if "B" in want:
            if verbose:
                print("  ▶ 段階 B: クラスタ中間（lite 並列）")
            syn_res = run_stage_b_mts(
                results_dir, out_dir, backends, facts,
                consultation=ni.consultation, target_date=tdate,
                seed=seed, verbose=verbose,
                monitor_path=mon_path, heartbeat_s=2.0 if monitor else None)
            res.synthesis = syn_res.get("cluster_dir", "")
        if "C" in want:
            if verbose:
                print("  ▶ 段階 C: 軸サマリー＋最終＋神々（最上位 flash）")
            syn_res = run_stage_c_mts(
                results_dir, out_dir, backends, facts,
                consultation=ni.consultation, target_date=tdate,
                seed=seed, verbose=verbose, ctx=ctx,
                per_axis=(syn_res or {}).get("per_axis"),
                monitor_path=mon_path, heartbeat_s=2.0 if monitor else None)
            res.synthesis = syn_res.get("file") or res.synthesis
            dstat = (syn_res.get("deities") or {}).get("status")
            if dstat == "ok":
                res.ok += 1
            elif dstat and dstat != "skipped":
                res.error += 1
                res.failed.append("deities")
        try:
            payload = {}
            if summary_path.exists():
                payload = json.loads(summary_path.read_text(encoding="utf-8"))
            payload.setdefault("mts", {})
            payload["mts"]["stages"] = list(want)
            if syn_res:
                payload["mts"]["synthesis"] = {
                    "file": syn_res.get("file"),
                    "axes": syn_res.get("axes"),
                    "deities": (syn_res.get("deities") or {}).get("status"),
                }
            summary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
    # mts5.53（P-10）: この人ぶんの警告をまとめて出す（既定は警告のみ。
    # RUN_STRICT=1 のときだけ、上位（Cell 1／Cell N2）が不合格にする）。
    try:
        _syn_reuse = int(((syn_res or {}).get("reuse") or {}).get("reused", 0)) \
            if "B" in want or "C" in want else 0
        if _syn_reuse:
            print(f"  ↺ 中間レポートの再利用 {_syn_reuse}本（段階B）")
    except Exception:
        pass
    try:
        from .runcheck import report_since
        _mark = _warn_mark[0]
        _warn_mark[0] = report_since(_mark, prefix="  ⚠")
    except Exception:
        pass
    return res


def _normalize_stages(stages) -> tuple[str, ...]:
    if stages is None:
        return ("A",)
    if isinstance(stages, str):
        s = stages.strip().upper().replace(",", "").replace(" ", "")
        if s in ("A", "B", "C"):
            return (s,)
        out = tuple(ch for ch in s if ch in "ABC")
        return out or ("A",)
    return tuple(str(x).upper() for x in stages)


def stage_b_assignment(plan: dict | None = None) -> dict[str, list[tuple[str, str]]]:
    """モデル名 → [(axis, cluster_id), ...]。

    既定は axis_to_model（method=3.1-lite / culture=3.5-lite）。
    mts5.6: `stage_b.cluster_to_model`（例 {"M-E": "gemini-3.5-flash-lite"}）があるときは
    **クラスタ単位で担当モデルを上書き**できる。2026-09-24 の実行で method 軸の5クラスタ中4本が
    503 で移譲されたため、混雑の偏りに応じてレーンを組み替えられるようにしたもの。
    未指定のクラスタは従来どおり軸の既定モデルが担当する。
    """
    plan = plan or load_model_plan()
    sb = plan.get("stage_b") or {}
    axis_map = sb.get("axis_to_model") or {
        "method": "gemini-3.1-flash-lite",
        "culture": "gemini-3.5-flash-lite",
    }
    override = sb.get("cluster_to_model") or {}
    out: dict[str, list[tuple[str, str]]] = {}
    for axis, model in axis_map.items():
        for c in get_clusters(axis):
            owner = override.get(c["id"], model)
            out.setdefault(owner, []).append((axis, c["id"]))
    return out


def stage_c_model(plan: dict | None = None) -> str:
    """段階Cの一次モデル（既定: gemini-3.8-flash。mts5.67 で 3.5-flash の非推奨化に伴い変更）。"""
    plan = plan or load_model_plan()
    return str((plan.get("stage_c") or {}).get("model") or "gemini-3.8-flash")


def stage_c_chain(plan: dict | None = None) -> list[str]:
    """段階Cのモデル列（mts5.67: 3.8-flash → 3.6-flash → 3-flash-preview → 3.5-lite）。"""
    plan = plan or load_model_plan()
    sc = plan.get("stage_c") or {}
    primary = str(sc.get("model") or "gemini-3.8-flash")
    fb = [m for m in (sc.get("fallback") or []) if m and m != primary]
    return [primary] + fb


def deities_model(plan: dict | None = None) -> str:
    """御縁のある神さま Top10 (M31) の担当モデル（既定: gemini-3-flash-preview）。

    mts5.67: 旧既定 `gemini-3-flash` はこのキーの一覧に無く常に 404 → `-preview` へ
    自動切替されていた（mts5.37 プローブ・実機ログ）ので、実働IDを直書きした。
    """
    plan = plan or load_model_plan()
    sc = plan.get("stage_c") or {}
    return str(sc.get("deities_model") or "gemini-3-flash-preview")


stage_c_deities_model = deities_model  # エイリアス互換


def deities_chain(plan: dict | None = None) -> list[str]:
    """御縁のある神さま Top10 (M31) のフォールバック列。"""
    plan = plan or load_model_plan()
    sc = plan.get("stage_c") or {}
    primary = deities_model(plan)
    fb = [m for m in (sc.get("deities_fallback") or sc.get("fallback") or []) if m and m != primary]
    return [primary] + fb


stage_c_deities_chain = deities_chain  # エイリアス互換


def _cluster_by_id(axis: str, cid: str) -> dict:
    for c in get_clusters(axis):
        if c["id"] == cid:
            return c
    raise KeyError(f"未知のクラスタ: {axis}/{cid}")


def _gen_with_retry(backend, sys_p, usr_p, *, temp, temp2, max_tokens, seed,
                    band, target_mid, retry=True, instruct=True,
                    instruct_band=None) -> str:
    from .synthesis import _fits, _gen, _instruct_range
    text = _gen(backend, sys_p, usr_p, temp, max_tokens, seed)
    if retry and not _fits(text, *band):
        n = len(text.strip())
        hint = ("長すぎます。重複を削って" if n > band[1]
                else "短すぎます。内容を補って")
        # mts5.58/5.60: 最終レポートは比例マージンではなく明示の指示レンジを使う
        # （下限を上げたため。再生成の指示も同じ目標に揃える）
        if instruct_band is not None:
            lo, hi = instruct_band
        else:
            lo, hi = _instruct_range(*band) if instruct else band
        text2 = _gen(
            backend, sys_p,
            usr_p + f"\n\n# 再出力の指示\n- 前回は{n}字で{hint}"
                    f"{lo}〜{hi}字に収めてください。\n"
                    "- 全文を最初から書き直してください。",
            temp2, max_tokens, seed)
        if abs(len(text2) - target_mid) < abs(n - target_mid):
            text = text2
    return text


def _write_cluster_md(cluster_dir: Path, axis: str, cluster: dict,
                      items: list, text: str) -> Path:
    from .synthesis import FOOTER, JST
    cluster_dir.mkdir(parents=True, exist_ok=True)
    path = cluster_dir / f"{cluster['id']}_{axis}.md"
    names = ", ".join(i["name"] for i in items)
    path.write_text(
        f"# 中間レポート: {cluster['title']}\n\n"
        f"**対象**: {len(items)}種（{names}）\n"
        f"**分類軸**: {axis}\n"
        f"**生成**: {datetime.now(JST).isoformat(timespec='seconds')}\n\n"
        f"{text}\n\n{FOOTER}\n", encoding="utf-8")
    return path


def verify_stage_b_files(out_dir, expected: list[tuple[str, str]] | None = None) -> dict:
    """段階 B のクラスタ md を照合する。expected は [(axis, id), ...]。"""
    if expected is None:
        expected = []
        for jobs in stage_b_assignment().values():
            expected.extend(jobs)
    d = Path(out_dir) / "cluster_reports"
    found = []
    missing = []
    for axis, cid in expected:
        p = d / f"{cid}_{axis}.md"
        if p.exists():
            found.append(f"{cid}_{axis}")
        else:
            missing.append(f"{cid}_{axis}")
    return {
        "expected": len(expected),
        "found": len(found),
        "missing": missing,
        "complete": not missing,
    }


def run_stage_b_mts(results_dir, out_dir, backends: dict[str, LLMBackend],
                    facts: dict, consultation: str = "", target_date: str = "",
                    seed: int | None = None, verbose: bool = True,
                    plan: dict | None = None,
                    progress: Progress | None = None,
                    monitor_path=None, heartbeat_s: float | None = None,
                    retry: bool = True) -> dict:
    """段階 B: クラスタ中間レポート 11本を lite 2 ワーカーで並列生成する。

    一時的な 503 / 空応答は、担当 backend での通常の 20秒×1 リトライ後に
    fallback モデルのアイドル・キューへ一度だけ移譲する。Stage A と同様に
    backend はスレッド間で共有しない。移譲先でも失敗したジョブは他モデルへ
    往復させず失敗扱いにし、11本そろわなければ Stage C に進ませない。
    """
    from .synthesis import CLUSTER_CHARS, collect_cluster_inputs, build_cluster_prompt

    plan = plan or load_model_plan()
    results_dir, out_dir = Path(results_dir), Path(out_dir)
    cluster_dir = out_dir / "cluster_reports"
    cluster_dir.mkdir(parents=True, exist_ok=True)

    grouped = stage_b_assignment(plan)
    for model in grouped:
        if model not in backends:
            raise KeyError(f"backend が無いモデル（段階B）: {model}")

    # [(axis, cluster_id)] は一次担当の仕事。fallback job は別キューで追跡し、
    # Progress の一次 total/done を二重計上しない（Stage A と同じ方式）。
    expected = [job for jobs in grouped.values() for job in jobs]
    prog = progress or Progress(stage="B")
    for model, jobs in grouped.items():
        prog.register(model, len(jobs))

    per_axis: dict[str, list] = {}
    reuse_stats = {"reused": 0}          # mts5.53（P-2）: 再利用の件数
    skipped: list[str] = []
    failures: list[dict] = []
    transfers: list[dict] = []
    lock = threading.Lock()
    cv = threading.Condition()

    # fallback はモデルごとのアイドル・キューへ投入する。plan に記載された
    # fallback 先が無担当モデルでも、backend があれば専用の待機ワーカーが拾う。
    steal_qs: dict[str, queue.Queue] = {
        m: queue.Queue() for m in backends
        if m in (plan.get("models") or {})
    }
    primary_left = sum(1 for jobs in grouped.values() if jobs)

    def _queues_empty() -> bool:
        return all(q.empty() for q in steal_qs.values())

    def _enqueue_fallback(axis: str, cid: str, from_model: str,
                          attempted: frozenset[str], original_model: str,
                          reason: str) -> bool:
        """503/空応答を未試行の fallback 先へ一度だけ移譲する。"""
        nxt = None
        for candidate in fallback_chain(from_model, plan):
            if (candidate in steal_qs and candidate in backends
                    and candidate not in attempted):
                nxt = candidate
                break
        if nxt is None:
            return False
        job = {
            "axis": axis,
            "cid": cid,
            "attempted": frozenset(set(attempted) | {from_model}),
            "original_model": original_model,
            "from_model": from_model,
            "reason": reason,
        }
        steal_qs[nxt].put(job)
        with lock:
            transfers.append({
                "job": f"{cid}_{axis}",
                "from_model": from_model,
                "to_model": nxt,
                "reason": reason,
            })
        prog.steal_enqueued(1)
        with cv:
            cv.notify_all()
        if verbose:
            print(f"  ↪ 移譲 {cid}_{axis}: {from_model} → {nxt}")
        return True

    def _finish_primary(model: str, job_name: str, status: str,
                        error: str = "") -> None:
        prog.finish_slug_named(model, job_name, status, error=error)

    def _run_one(model: str, axis: str, cid: str, *, stolen: bool,
                 attempted: frozenset[str], original_model: str) -> dict:
        be = backends[model]
        job_name = f"{cid}_{axis}"
        if not stolen:
            prog.start_slug(model, job_name)
        try:
            cluster = _cluster_by_id(axis, cid)
            # ★ レジューム: 既存の中間レポートがあれば再利用し、再生成しない
            #   （Save & Run をまたぐ Dataset チェックポイント復元時など）。
            #   md は生成成功後にしか書かれないため、存在＝前回の成功成果。
            md_path = cluster_dir / f"{cid}_{axis}.md"
            if not stolen and md_path.exists() and md_path.stat().st_size > 0:
                body = md_path.read_text(encoding="utf-8")
                rec = {
                    "id": cid,
                    "title": cluster["title"],
                    "desc": cluster.get("desc", ""),
                    "count": len(cluster.get("slugs", [])),
                    "slugs": list(cluster.get("slugs", [])),
                    "text": body,
                    "chars": len(body),
                    "axis": axis,
                    "model": model,
                    "original_model": original_model,
                    "fallback": False,
                    "reused": True,
                }
                with lock:
                    per_axis.setdefault(axis, []).append(rec)
                    reuse_stats["reused"] += 1
                # mts5.53（P-2）: 監査の指摘＝再利用が verbose のときしか見えなかった。
                print(f"  ↺ [{model}] {cid}_{axis}: 既存の中間レポートを再利用"
                      "（再生成しません・入力を変えて作り直すときは --fresh 相当で削除）")
                _finish_primary(model, job_name, "ok")
                return {"status": "ok", "reused": True, "job": job_name,
                        "axis": axis, "id": cid}

            items = collect_cluster_inputs(results_dir, cluster)
            if not items:
                with lock:
                    skipped.append(job_name)
                if verbose:
                    print(f"  − [{model}] {cluster['title']}: 結果なし（スキップ）")
                if stolen:
                    prog.steal_finished(1)
                else:
                    _finish_primary(model, job_name, "skipped")
                return {"status": "skipped", "job": job_name,
                        "axis": axis, "id": cid}

            sys_p, usr_p = build_cluster_prompt(
                cluster, items, facts, consultation, target_date)
            if verbose:
                tag = "移譲後 " if stolen else ""
                print(f"  ▶ [{model}] {tag}中間 {cid} {cluster['title']}"
                      f"（{len(items)}種）…")
            text = _gen_with_retry(
                be, sys_p, usr_p, temp=0.6, temp2=0.4, max_tokens=2600,
                seed=seed, band=CLUSTER_CHARS, target_mid=1500, retry=retry)
            if not text.strip():
                raise RuntimeError("Gemini API が空の応答を返しました")

            rec = {
                "id": cid,
                "title": cluster["title"],
                "desc": cluster["desc"],
                "count": len(items),
                "slugs": [i["slug"] for i in items],
                "text": text,
                "chars": len(text),
                "axis": axis,
                "model": model,
                "original_model": original_model,
                "fallback": stolen,
            }
            _write_cluster_md(cluster_dir, axis, cluster, items, text)
            with lock:
                per_axis.setdefault(axis, []).append(rec)
            if verbose:
                tag = "移譲後 " if stolen else ""
                print(f"    → {len(text)}字  {tag}{cid}_{axis}.md")
            if stolen:
                prog.steal_finished(1)
            else:
                _finish_primary(model, job_name, "ok")
            return {"status": "ok", "job": job_name, "axis": axis, "id": cid,
                    "model": model, "fallback": stolen}
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
            stealable = _is_stealable(None, e)
            if verbose:
                print(f"  ⚠ [{model}] {job_name}: {reason}")
                traceback.print_exc(limit=1)
            if stealable and _enqueue_fallback(
                    axis, cid, model, attempted, original_model, reason):
                # 元ジョブは「移譲済み」として一次側では終了させる。fallback
                # 自身が失敗した場合は attempted により元へ戻らない。
                if stolen:
                    prog.steal_finished(1)
                else:
                    _finish_primary(model, job_name, "error",
                                    error="stolen: " + reason)
                return {"status": "stolen", "job": job_name,
                        "axis": axis, "id": cid, "reason": reason}

            with lock:
                failures.append({
                    "job": job_name,
                    "model": model,
                    "original_model": original_model,
                    "reason": reason,
                    "stealable": stealable,
                })
            if stolen:
                prog.steal_finished(1)
            else:
                _finish_primary(model, job_name, "error", error=reason)
            return {"status": "error", "job": job_name,
                    "axis": axis, "id": cid, "reason": reason}

    def _worker(model: str, assigned: list[tuple[str, str]]) -> None:
        nonlocal primary_left
        for axis, cid in assigned:
            _run_one(model, axis, cid, stolen=False,
                     attempted=frozenset({model}), original_model=model)
        with cv:
            if assigned:
                primary_left -= 1
            cv.notify_all()

        my_q = steal_qs.get(model)
        if my_q is None:
            return
        while True:
            with cv:
                while True:
                    try:
                        job = my_q.get_nowait()
                        break
                    except queue.Empty:
                        if (primary_left <= 0 and _queues_empty()
                                and prog.steal_pending() <= 0):
                            return
                        cv.wait(timeout=0.2)
                        if (primary_left <= 0 and _queues_empty()
                                and my_q.empty()
                                and prog.steal_pending() <= 0):
                            return
            _run_one(
                model, job["axis"], job["cid"], stolen=True,
                attempted=job["attempted"],
                original_model=job["original_model"])
            with cv:
                cv.notify_all()

    mon = None
    if monitor_path is not None or heartbeat_s:
        mon = ProgressMonitor(
            prog, path=monitor_path,
            interval_s=heartbeat_s or 2.0, verbose=verbose)
        mon.start()

    # Assigned workers plus any model that can receive a fallback job. Models
    # without primary work wait for the queue and do not enter Progress totals.
    worker_models = []
    seen = set()
    for m in list(grouped) + [m for src in grouped
                              for m in fallback_chain(src, plan)]:
        if m in seen or m not in backends:
            continue
        seen.add(m)
        worker_models.append(m)

    try:
        n_workers = max(len(worker_models), 1)
        with ThreadPoolExecutor(max_workers=n_workers,
                                thread_name_prefix="mts-b") as ex:
            futs = [ex.submit(_worker, m, grouped.get(m, []))
                    for m in worker_models]
            for f in as_completed(futs):
                f.result()
        prog.wait_all(timeout=1.0)
    finally:
        if mon is not None:
            mon.stop()

    # Stage C は中間11本を前提にする。部分的なBを成功扱いにしない。
    # ファイルの存在だけでなく「今回の実行で成功した job」も照合する。
    # これにより、古い実行の残存ファイルで欠落を隠さない。
    check = verify_stage_b_files(out_dir, expected=expected)
    completed_jobs = {
        (rec.get("axis"), rec.get("id"))
        for reps in per_axis.values() for rec in reps
    }
    run_missing = [f"{cid}_{axis}" for axis, cid in expected
                   if (axis, cid) not in completed_jobs]
    # スキップ（結果なし）は原則欠落: ただし M-D 相性（synastry/parimicham）は partner 無しの人は正常にスキップされる
    # （collect_cluster_inputs が空 → skipped）。全11クラスタが空のような異常系は欠落として扱う。
    raw_missing = list(dict.fromkeys([*check["missing"], *run_missing]))
    # M-D のみスキップを許容（partner 無し）。他のクラスタのスキップは異常なので欠落として残す。
    # ただし全クラスタがスキップ（empty results）の場合は従来通りエラーにする。
    if set(skipped) == set(f"{cid}_{axis}" for axis, cid in expected):
        missing = raw_missing
    else:
        missing = [m for m in raw_missing if not (m == "M-D_method" and m in skipped)]
    check["run_found"] = len(expected) - len(run_missing)
    check["run_missing"] = run_missing
    check["skipped"] = list(skipped)
    check["missing_filtered"] = missing
    check["complete"] = not missing
    if not check["complete"]:
        if verbose:
            print(f"  ❌ 段階B未完了: {check['run_found']}/{check['expected']}本 "
                  f"欠落={missing}（スキップ={skipped}）")
        raise RuntimeError(
            "段階Bのクラスタ中間レポートが不足しています。"
            f"欠落: {', '.join(missing)}。"
            "503/空応答なら再実行し、Stage Cへ進まないでください。"
        )

    # Thread completion order is nondeterministic; keep output order stable for
    # downstream prompts and reproducible artifacts.
    for axis in per_axis:
        per_axis[axis].sort(key=lambda r: r["id"])
    return {
        "axes": list(per_axis.keys()),
        "per_axis": per_axis,
        "skipped": skipped,
        "failures": failures,
        "fallbacks": transfers,
        "cluster_dir": str(cluster_dir),
        "verification": check,
        "complete": True,
        "progress": prog.snapshot(),
        "reuse": dict(reuse_stats),       # mts5.53（P-2）
    }


def run_stage_c_mts(results_dir, out_dir, backends, facts: dict,
                    consultation: str = "", target_date: str = "",
                    seed: int | None = None, verbose: bool = True,
                    ctx: PipelineContext | None = None,
                    per_axis: dict | None = None,
                    plan: dict | None = None,
                    progress: Progress | None = None,
                    monitor_path=None, heartbeat_s: float | None = None,
                    retry: bool = True) -> dict:
    """段階 C: 軸サマリー2＋最終1＋deities を最上位 flash 1 ワーカーで直列実行。"""
    from .synthesis import (
        AXIS_LABEL, AXIS_SUMMARY_CHARS, FINAL_CHARS, FINAL_INSTRUCT_CHARS,
        FOOTER, JST,
        append_deities_section, build_axis_summary_prompt,
        build_crossaxis_final_prompt, write_synthesis_file,
    )

    plan = plan or load_model_plan()
    model = stage_c_model(plan)
    chain = stage_c_chain(plan)
    d_model = deities_model(plan)
    d_chain = deities_chain(plan)
    if "lite" in model or (ctx is not None and "lite" in d_model):
        raise RuntimeError(f"段階Cの一次モデルは非lite flash（got {model}, {d_model}）")
    if isinstance(backends, dict):
        all_needed = list(dict.fromkeys(chain + (d_chain if ctx is not None else [])))
        missing = [m for m in all_needed if m not in backends]
        if model not in backends:
            raise KeyError(f"backend が無いモデル（段階C）: {model}")
        if ctx is not None and d_model not in backends:
            raise KeyError(f"backend が無いモデル（段階C deities）: {d_model}")
        chain = [m for m in chain if m in backends]
        d_chain = [m for m in d_chain if m in backends]
        if missing and verbose:
            print(f"  ※ 段階C fallback 欠落: {missing}")

        def _pick_be(name):
            return backends[name]
    else:
        def _pick_be(name):
            return backends

    def _gen_c(**kw):
        last = None
        for m in chain:
            try:
                if verbose and m != model:
                    print(f"    ↪ 段階C 移譲 → {m}")
                return _gen_with_retry(_pick_be(m), **kw)
            except Exception as e:
                last = e
                if not _is_stealable(None, e):
                    raise
                if verbose:
                    print(f"  ⚠ [{m}] 段階C {_stealable_label(e)} → 次へ")
        raise last if last else RuntimeError("段階C: 全モデル失敗")

    results_dir, out_dir = Path(results_dir), Path(out_dir)
    cluster_dir = out_dir / "cluster_reports"
    cluster_dir.mkdir(parents=True, exist_ok=True)

    # Stage C must never consume a partial Stage B. This also protects the
    # resume/direct-call path where run_stage_b_mts was not called in-process.
    # ただし結果なしでスキップされたクラスタ（例: partner 無しの M-D 相性）は欠落ではない
    b_expected = [job for jobs in stage_b_assignment(plan).values()
                  for job in jobs]
    bcheck = verify_stage_b_files(out_dir, expected=b_expected)
    if not bcheck["complete"]:
        from .synthesis import collect_cluster_inputs
        filtered = []
        for name in bcheck["missing"]:
            # M-D のみ partner 無しのスキップを許容。他は欠落として扱う。
            if name == "M-D_method":
                try:
                    cid, axis = name.rsplit("_", 1)
                    cluster = _cluster_by_id(axis, cid)
                    if not collect_cluster_inputs(results_dir, cluster):
                        # 結果なしでスキップされた正当な欠落 → 許容
                        continue
                except Exception:
                    pass
            filtered.append(name)
        if filtered:
            raise RuntimeError(
                "段階Cを開始できません。段階Bのクラスタ中間レポートが不足しています。"
                f"欠落: {', '.join(filtered)}。"
            )
        # M-D スキップのみの欠落なら警告だけで続行
        if verbose and bcheck["missing"]:
            print(f"  ※ 段階B スキップを許容: {bcheck['missing']}（結果なしのため）")

    if not per_axis:
        # ディスクから段階Bの成果を拾う（再開用）
        per_axis = {}
        for axis in ("method", "culture"):
            reps = []
            for c in get_clusters(axis):
                p = cluster_dir / f"{c['id']}_{axis}.md"
                if not p.exists():
                    continue
                body = p.read_text(encoding="utf-8")
                # 本文だけ（見出し・フッタを粗く除く）
                text = body
                for marker in ("## ", "# 中間レポート"):
                    pass
                # ファイル全体から鑑定本文を抽出するのは難しいので全文を渡す
                reps.append({"id": c["id"], "title": c["title"],
                             "count": len(c["slugs"]), "text": body,
                             "chars": len(body)})
            if reps:
                per_axis[axis] = reps
    if not per_axis:
        raise RuntimeError("段階C: 中間レポートがありません（段階Bを先に実行）")

    jobs = [f"axis_{ax}" for ax in per_axis] + ["final"]
    prog = progress or Progress(stage="C")
    if ctx is not None:
        if d_model == model:
            prog.register(model, len(jobs) + 1)
        else:
            prog.register(model, len(jobs))
            prog.register(d_model, 1)
    else:
        prog.register(model, len(jobs))

    mon = None
    if monitor_path is not None or heartbeat_s:
        mon = ProgressMonitor(prog, path=monitor_path,
                              interval_s=heartbeat_s or 2.0, verbose=verbose)
        mon.start()

    # mts5.68: 混雑しやすい上位 Flash レーンには応答の打ち切りを掛ける（段階 C の間だけ。
    # backend は段階間で共有されるため、終わったら必ず元に戻す）
    to_models, to_s = stage_c_response_timeout(plan)
    _to_prev: list[tuple[object, object]] = []
    if to_s and isinstance(backends, dict):
        for _m in sorted(to_models):
            _be = backends.get(_m)
            if _be is None:
                continue
            _to_prev.append((_be, getattr(_be, "response_timeout_s", None)))
            _be.response_timeout_s = to_s
        if verbose and _to_prev:
            print(f"  ※ 段階C 応答の打ち切り: {to_s:g}秒"
                  f"（{', '.join(m for m in sorted(to_models) if m in backends)}・"
                  "超えたら次のモデルへ）")

    axis_summaries = []
    try:
        for axis, reports in per_axis.items():
            job = f"axis_{axis}"
            prog.start_slug(model, job)
            if verbose:
                print(f"  ▶ [{model}] 軸サマリー {axis}（中間{len(reports)}本）…")
            sys_p, usr_p = build_axis_summary_prompt(
                axis, reports, facts, consultation, target_date)
            atext = _gen_c(
                sys_p=sys_p, usr_p=usr_p, temp=0.6, temp2=0.45, max_tokens=3000,
                seed=seed, band=AXIS_SUMMARY_CHARS,
                target_mid=sum(AXIS_SUMMARY_CHARS) // 2, retry=retry,
                instruct=False)
            axis_summaries.append({"axis": axis, "text": atext})
            (cluster_dir / f"AXIS_{axis}.md").write_text(
                f"# 軸サマリー: {AXIS_LABEL.get(axis, axis)}\n\n"
                f"**対象**: 中間{len(reports)}本\n"
                f"**生成**: {datetime.now(JST).isoformat(timespec='seconds')}\n\n"
                f"{atext}\n\n{FOOTER}\n", encoding="utf-8")
            if verbose:
                print(f"    → {len(atext)}字")
            prog.finish_slug_named(model, job, "ok")

        prog.start_slug(model, "final")
        if verbose:
            print(f"  ▶ [{model}] 最終統合（軸{len(axis_summaries)}本）…")
        sys_p, usr_p = build_crossaxis_final_prompt(
            axis_summaries, facts, consultation, target_date)
        # mts5.58/5.60: 指示レンジ（4,800〜5,200字）に合わせ、試行の選択は帯の中央
        # （5,000字）に。再生成の指示も同じ明示レンジを使う。max_tokens は上限 5,200字で
        # 切れないよう 5,600 → 6,400（文字数ベース＝内部で1.6倍のマージン）
        final = _gen_c(
            sys_p=sys_p, usr_p=usr_p, temp=0.65, temp2=0.45, max_tokens=6400,
            seed=seed, band=FINAL_CHARS, target_mid=5000, retry=retry,
            instruct_band=FINAL_INSTRUCT_CHARS)
        path = write_synthesis_file(
            out_dir, final, facts, consultation, target_date,
            per_axis, axis_summaries)
        if verbose:
            print(f"    → {len(final)}字  {path}")
        prog.finish_slug_named(model, "final", "ok")

        deities_info = None
        if ctx is not None:
            prog.start_slug(d_model, "deities")
            if verbose:
                print(f"  ▶ [{d_model}] 御縁のある神さま（統合レポートを踏まえて選定）…")
            from .calc.deities import draw_deities
            f = dict(facts)
            f["_consultation"] = consultation or ""
            calc = draw_deities(f, seed=seed, synthesis_text=final)
            ctx.calc_results["deities"] = calc
            r = None
            last_d = None
            for m in d_chain:
                try:
                    if verbose and m != d_model:
                        print(f"    ↪ deities 移譲 → {m}")
                    r = run_divination(
                        "deities", ctx, force=True, backend=_pick_be(m),
                        model_hint=m)
                    last_d = None
                    break
                except Exception as e:
                    last_d = e
                    if not _is_stealable(None, e):
                        raise
            if r is None:
                if last_d:
                    raise last_d
                r = {"status": "error", "reason": "deities 全モデル失敗"}
            text = ""
            raw = Path(ctx.results_dir) / "M31_deities_raw.json"
            if raw.exists():
                try:
                    text = json.loads(raw.read_text(encoding="utf-8"))["result"]["text"]
                except Exception:
                    text = ""
            append_deities_section(path, calc, text)
            deities_info = {"status": r.get("status"), "calc": calc,
                            "chars": len(text)}
            if verbose:
                cov = calc.get("pantheon_coverage", {})
                print(f"    → {len(text)}字／カバレッジ {cov}")
            prog.finish_slug_named(
                d_model, "deities", r.get("status") or "error",
                error=r.get("reason") or "")
        prog.wait_all(timeout=1.0)
    finally:
        for _be, _prev in _to_prev:                    # mts5.68: 打ち切り設定を戻す
            _be.response_timeout_s = _prev
        if mon is not None:
            mon.stop()

    if deities_info is None and ctx is None:
        deities_info = {"status": "skipped", "reason": "ctx is None"}

    return {
        "axes": list(per_axis.keys()),
        "per_axis": per_axis,
        "axis_summaries": axis_summaries,
        "final_report": final,
        "file": str(path),
        "deities": deities_info,
        "progress": prog.snapshot(),
    }