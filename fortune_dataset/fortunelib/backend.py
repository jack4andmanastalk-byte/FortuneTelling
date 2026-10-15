# -*- coding: utf-8 -*-
"""
LLMバックエンド抽象化
- LLMBackend: インターフェース
- MockBackend: ローカルテスト用（決定的・応答キュー対応）
- GeminiBackend: Google Gemini API（Flash系・Kaggle の無料枠で運用）

★ 2026-08-26 Gemini API移行（MTS-only運用）
  旧 KaggleBackend（Transformers系のローカルモデル実行）は削除。
  これに伴い、モデルロード系の不具合（BUG-04/09/10: chat_template・MoE量子化・
  VRAM上限）は原理的に発生しなくなった。

  Gemini API運用で管理すること:
  1. 無料枠のレート制限（Flash系でおおむね10〜15回/分・250〜1,500回/日）
     → 呼び出し間隔の下限（スロットリング）と 429 の指数バックオフリトライで対処
  2. 出力トークン上限は「文字数」ではなく「トークン」で効く
     → 日本語は1トークン≈1字未満になるため、max_tokens にマージン（既定1.6倍）を掛ける
  3. 安全フィルタでブロックされることがある
     → "" を返して検証→再生成（BUG-05 の経路）に委ねる。例外で止めない
"""
from __future__ import annotations

import json
import os
import threading
import time
from abc import ABC, abstractmethod


class ResponseTimeoutError(RuntimeError):
    """応答が制限時間を超えた（mts5.11）。

    503 とは違い、**サーバは応答を返している途中で遅いだけ**なので、この
    バックエンドでは再試行せず即座に上位（MTS の別レーンへの移譲）へ返す。
    mts5.9 の実測では、エラーを伴わない 77 秒の応答が Stage A（264秒）の
    律速になっていた（docs/architecture.md「信頼性の仕組み」）。
    """


class LLMBackend(ABC):
    """LLM生成バックエンドの共通インターフェース"""

    #: 本物の LLM を呼ばない（ローカル確認・テスト用）バックエンドかどうか。
    #: mts5.56: Stage D の口調の弁別チェックで、モック（demo・単体テスト）に対しては
    #: **再試行も警告も出さない**（規則置換のダミーは構造的に指定を満たせないため）。
    is_mock: bool = False

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.7, max_tokens: int = 1000,
                 seed: int | None = None) -> str:
        """システム＋ユーザープロンプト → 生成テキスト"""


class MockBackend(LLMBackend):
    """
    ローカルテスト用バックエンド。
    - responses: 応答キューのリスト（順に消費・最後の要素を使い続ける）
    - 既定では決定的な鑑定文風テキストを返す
    """

    #: モック（mts5.56: 口調の弁別チェックの再試行・警告を抑止する）
    is_mock = True

    DEFAULT_TEXT = (
        "あなたは静かな力強い性質を持ち、物事を着実に進める傾向があります。"
        "今年はこれまでの努力が形になり始める時期です。焦らず、一歩ずつ歩むことが大切でしょう。"
        "周囲からの信頼も厚く、相談ごとを持ちかけられる機会が増えます。"
        "特に仕事においては、地道な積み重ねが評価される年となります。"
        "ただし、無理をしすぎないよう注意してください。休息をしっかり取りながら、"
        "自分のペースを守ることが幸運を引き寄せる鍵となります。"
        "この時期の選択は、将来にとって意味のあるものになる可能性が高いでしょう。"
        "人間関係では、誠実さと寛容さが試される場面があります。"
        "相手の立場に立って考えることで、より深い信頼を築くことができるでしょう。"
        "金銭面では、無駄遣いを避け、計画的なやりくりを心がけると安定します。"
        "健康面では、適度な運動とバランスの良い食事が運気を支えます。"
        "特に秋口以降は、新しい出会いやチャンスが訪れる兆しがあります。"
        "その波に乗るためにも、日頃から準備を怠らないことが重要です。"
        "最終的には、あなたの持つ穏やかさと粘り強さが、"
        "周囲の人々の信頼を得て、目標達成へと導いてくれるでしょう。"
    )

    def __init__(self, responses: list | None = None):
        self._responses = list(responses) if responses else []
        self.calls = []  # (system_prompt, user_prompt, temperature, max_tokens, seed) のログ
        # mts5.11: GeminiBackend と同じ契約（未設定は None＝制限なし）。
        # MTS の段階 A が実行直前にレーンごとに設定し、終わったら戻す。
        self.response_timeout_s = None

    def generate(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.7, max_tokens: int = 1000,
                 seed: int | None = None) -> str:
        self.calls.append({
            "system": system_prompt, "user": user_prompt,
            "temperature": temperature, "max_tokens": max_tokens, "seed": seed,
        })
        if self._responses:
            resp = self._responses[0]
            if len(self._responses) > 1:
                self._responses.pop(0)
            return resp
        return self.DEFAULT_TEXT


class LazyBackend(LLMBackend):
    """初回 generate 時にバックエンドを遅延ロード（APIクライアント初期化を初回占術実行時に実施）"""

    def __init__(self, factory):
        self._factory = factory
        self._backend = None

    @property
    def is_mock(self) -> bool:            # mts5.56: 包んでいるバックエンドの性質を引き継ぐ
        inner = self._backend
        return bool(getattr(inner, "is_mock", False)) if inner is not None else False

    def generate(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.7, max_tokens: int = 1000,
                 seed: int | None = None) -> str:
        if self._backend is None:
            self._backend = self._factory()
        return self._backend.generate(system_prompt, user_prompt,
                                      temperature=temperature,
                                      max_tokens=max_tokens, seed=seed)


# ============================================================
# Gemini API バックエンド（2026-08-26 移行）
# ============================================================

def _resolve_gemini_api_key() -> str | None:
    """Gemini APIキーを3段階で解決（環境変数 → kaggle_secrets → None）。

    Kaggle の公式 Gemini モデルカードと同じ手順:
      Google AI Studio (https://aistudio.google.com) で無料発行し、
      Kaggle Notebook の Secrets に "GOOGLE_API_KEY" の名前で登録する。

    ★クロスチェック改善（2026-08-26・他AI実装A/D/E方式を吸収）:
      Secrets の名前は GOOGLE_API_KEY が公式だが、GEMINI_API_KEY と登録する
      ユーザーも多いため、両方の名前を試行する。
    """
    key = (os.environ.get("GEMINI_API_KEY")
           or os.environ.get("GOOGLE_API_KEY")
           or os.environ.get("KAGGLE_SECRET_GOOGLE_API_KEY"))
    if key:
        return key
    try:
        from kaggle_secrets import UserSecretsClient
        client = UserSecretsClient()
        for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
            try:
                v = client.get_secret(name)
                if v:
                    return v
            except Exception:
                continue
        return None
    except Exception:
        return None


def normalize_gemini_model_name(name: str) -> str:
    """Gemini のモデル名を google-genai 向けに正規化する。

    ★クロスチェック改善（2026-08-26・他AI実装A方式を吸収）:
      Kaggle のモデルカードには "models/gemini-2.5-flash-preview-04-17" のように
      models/ 接頭辞付きで載っている。そのままコピペしても動くように接頭辞を除去する。
      また "gemini-3.0-flash" 等の "3.0" 表記を公式ID "gemini-3-flash" に正規化する。
    """
    n = (name or "").strip()
    if not n:
        return GeminiBackend.DEFAULT_MODEL
    if n.startswith("models/"):
        n = n[len("models/"):]
    if n in ("gemini-3.0-flash", "gemini-3.0-flash-001"):
        return "gemini-3-flash"
    if n in ("gemini-3.0-flash-preview", "gemini-3.0-flash-preview-001"):
        return "gemini-3-flash-preview"
    return n


def _api_error_code(exc: Exception) -> int | None:
    """google-genai の例外（ClientError/ServerError 等）からHTTPコードを取り出す。"""
    code = getattr(exc, "code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def _is_network_error(exc: Exception) -> bool:
    """ネットワーク系（タイムアウト・接続断）かどうかの緩い判定。"""
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    s = str(exc).lower()
    return "timeout" in s or "connection" in s or "timed out" in s


def _is_rate_limited(exc: BaseException) -> bool:
    """429/クォータ枯渇系かどうかの判定。

    ★第2回クロスチェック改善（2026-08-26・修正版A方式を吸収）:
      google-genai の例外は code 属性を持つが、proxy・retry ラッパー等を
      介すると生の Exception に message だけ残る場合がある。
      code 属性が無い例外も文字列から判定できるようにする。
    """
    if _api_error_code(exc) == 429:
        return True
    s = str(exc).lower()
    name = type(exc).__name__.lower()
    if "429" in s or "resource_exhausted" in s:
        return True
    if "rate" in s and "limit" in s:
        return True
    if "quota" in s or "too many requests" in s:
        return True
    return "resourceexhausted" in name or "ratelimit" in name


def _is_not_found(exc: BaseException) -> bool:
    """モデル不在（404）系かどうかの判定。

    ★第2回クロスチェック改善（2026-08-26・修正版A方式を吸収）:
      _is_rate_limited と同様に、code 属性が無い例外も文字列から判定する。
      APIキー・権限系の「not found」はモデル切替では解決しない除外対象。
    """
    if _api_error_code(exc) == 404:
        return True
    s = str(exc).lower()
    if "api key" in s or "api_key" in s or "permission" in s:
        return False
    return ("not found" in s or "not_found" in s or "unknown model" in s
            or "404" in s)


def _is_server_error_text(exc: BaseException) -> bool:
    """code 属性を持たない例外を5xx相当と推定する判定（保守的なキーワード）。"""
    s = str(exc).lower()
    return any(k in s for k in (
        "internal error", "backend error", "bad gateway",
        "overloaded", "unavailable", "temporarily", "server error"))


def _is_daily_quota(exc: BaseException) -> bool:
    """429 が日次クォータ（RPD）枯渇かどうか（分単位の429と区別する）。

    ★12回目実機（2026-08-27）で判明: 無料枠は日次リクエスト上限が
      実質的な律速（gemini-3.5-flash で20回/日）。日次クォータの429は
      待機しても解除されないため、リトライせず即停止する必要がある。
      エラー本文の quotaId（GenerateRequestsPerDayPerProjectPerModel）で
      分単位（PerMinute）の429と区別する。
    """
    s = str(exc)
    return ("RequestsPerDay" in s or "PerDayPerProject" in s
            or "per day" in s.lower()
            or "daily limit" in s.lower() or "daily quota" in s.lower())


# mts5.67（2026-10-14・ユーザー決定）: 上位（flash）レーンの順序の正本。
#   model_plan.json の stage_c / fallback と video.SCRIPT_MODELS もこの順に揃える
#   （テスト `test_model_migration.py` が突合）。非推奨の gemini-3.5-flash／
#   gemini-3.7-flash はここにも 404 候補にも入れない。
FLASH_UPPER_ORDER = ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview")
DEPRECATED_MODELS = ("gemini-3.5-flash", "gemini-3.7-flash")


def gemini_model_candidates(name: str) -> list:
    """モデル404時のフォールバック候補リスト。

    ★第2回クロスチェック改善（2026-08-26・修正版A方式を吸収）:
      Google はモデルIDを改廃するため（例: 無印→preview のみ公開等）、
      指定IDが404になった場合に備えて代替候補を順に試す。
      既定モデルは安定板を維持し、404の時だけ切替える。

    ★モデル切替（2026-08-26）: gemini-2.5-flash は 2026-10-16 以降（最早日）
      にシャットダウン予定のため、既定を gemini-3.5-flash へ変更。
      2.5系を手動指定した場合の最後の保険も生きている既定モデルへ繋ぐ。
    ★mts5.67（2026-10-14・ユーザー決定）: gemini-3.5-flash と gemini-3.7-flash が
      **非推奨**になったため、既定を **gemini-3.8-flash** へ変更し、上位（flash）の
      候補順は **3.8 → 3.6 → 3-flash-preview**（ご指定の順）。非推奨の2モデルは
      候補からも外す（停止後の無駄打ちを避ける）。旧IDを手動指定した場合は
      一般則（`-preview` → 既定モデル）で生きている既定モデルへ繋ぐ。
    """
    primary = normalize_gemini_model_name(name)

    # ★枠ファミリー管理（2026-08-27・AI Studio 実測表で確定）:
    #   モデルごとに無料枠が大きく違い、誤った家族へ落ちると枯渇する。
    #   flash系とflash-lite系で無料枠が異なるため、家族を跨ぐ
    #   フォールバックは行わない。
    if "flash-lite" in primary:
        # flash-lite系: flash（20RPD）へは絶対に落ちない
        out = [primary]
        if "-preview" not in primary:
            out.append(primary + "-preview")
        if primary.startswith("gemini-3.5"):
            out.append("gemini-3.1-flash-lite")
        elif primary.startswith("gemini-3.1"):
            out.append("gemini-3.5-flash-lite")
        return _dedupe(out)

    out = [primary]
    # 明示的な preview 指定でなければ、preview 接尾辞を次点に
    if "-preview" not in primary:
        out.append(primary + "-preview")
    # よくある公式プレビュー ID / 後継モデル（mts5.67: 3.8 → 3.6 → 3-flash-preview）
    if primary == "gemini-3.8-flash":
        out.extend(FLASH_UPPER_ORDER[1:])         # 3.6-flash → 3-flash-preview
    elif primary == "gemini-3.6-flash":
        out.append("gemini-3-flash-preview")      # 次点（ご指定の順）
    elif primary == "gemini-2.5-flash":
        out.append("gemini-2.5-flash-preview-04-17")
    elif primary == "gemini-2.5-flash-lite":
        out.append("gemini-2.5-flash-lite-preview-06-17")
    elif primary in ("gemini-3-flash", "gemini-3.0-flash"):
        out.append("gemini-3-flash-preview")
        if primary == "gemini-3.0-flash":
            out.append("gemini-3-flash")
    # 最後の保険: 既定モデル（同一 flash ファミリー内のみ）
    if primary != GeminiBackend.DEFAULT_MODEL:
        out.append(GeminiBackend.DEFAULT_MODEL)
    return _dedupe(out)


def _dedupe(items: list) -> list:
    seen, uniq = set(), []
    for m in items:
        if m and m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq



class GeminiBackend(LLMBackend):
    """
    Google Gemini API（Flash系）で鑑定文を生成するバックエンド。

    設計メモ:
    - 無料枠は Flash 系のみ（2026-04 に Pro は無料枠から除外）で、
      レート制限は概ね 10〜15回/分。既定 10回/分のスロットリングを入れる。
      1回の完走は 53＋11＋2＋1＝約67呼び出しなので、日次上限にも余裕がある。
    - 429/5xx/ネットワーク断 → 指数バックオフでリトライ（既定5回・計約10分）。
      打ち切った場合は RuntimeError で止める。MTSは完了済みの結果ファイルを再利用できるため、再実行すれば続きから再開できる。
      ★ただし日次クォータ（RPD）枯渇の429だけは待機しても解除されないため
      即停止し「翌日の再実行」を促す（12回目実機・2026-08-27対応）。
    - 4xx（認証・権限・モデル名誤り等）はリトライしても無駄なので即停止。
      ただし 404（モデル不在）だけは候補モデルへの切替を先に試す
      （★第2回クロスチェック改善・修正版A方式の吸収。gemini_model_candidates）。
      一度成功したモデルは記憶し、毎回のgenerateで404を再試行しない。
    - 安全フィルタでブロックされた場合は "" を返す（例外にしない）。
      パイプラインの検証→再生成（BUG-05 の経路）に自然に乗る。
    - thinking は既定で最小化。鑑定文生成に思考は不要で、出力トークンを
      消費して字数指定を圧迫するため。制御パラメータは**モデル世代で別物**:
      2.5系＝thinking_budget=0（完全無効）、3系＝thinking_level="minimal"
      （「多くのクエリで思考オフ相当」・完全無効は不可能）。
      切替はモデル名から自動判別する（★落とし穴F-3対策・404フォールバックで
      モデルが変わっても追従）。None でSDK既定に戻せる。
      なお 3.7 Flash は minimal 廃止（low/medium/high）かつ無料枠がないため
      指定しないこと（誤指定時は low へ読み替えて送る）。
      ★mts5.67: thinking 系パラメータが 400 で拒否されたら **minimal → low → 除去**
      の順に1段ずつ下げて再送する（リトライ枠は消費しない）。従来は「除去して再試行」と
      表示しながら同じ設定を再送していた（フラグを _thinking_kwargs が見ていなかった）。
      ★mts5.68: 既定 gemini-3.8-flash は実機（2026-10-14）で minimal が拒否されたため
      `_minimal_unsupported` に加え、最初から low で送る（3.6-flash は未確定＝従来どおり）。
    - max_tokens は「文字数ベース」で渡されてくる（pipeline.py が char_max+250 を
      渡す）ため、日本語のトークン比率（1トークン≈1字未満）を見込んで
      token_margin 倍して max_output_tokens に変換する。
    """

    DEFAULT_MODEL = "gemini-3.8-flash"   # mts5.67: 3.5-flash／3.7-flash の非推奨化に伴い変更
                                         # （旧既定 gemini-3.5-flash＝GA 2026-05-19 → 非推奨 2026-10。
                                         #   さらに前の gemini-2.5-flash は2026-10-16以降に廃止予定）

    def __init__(self, model_name: str = DEFAULT_MODEL,
                 api_key: str | None = None,
                 requests_per_minute: float = 10.0,
                 token_margin: float | None = None,
                 max_retries: int = 5,
                 backoff_base_s: float = 20.0,
                 response_timeout_s: float | None = None,
                 thinking_budget: int | None = 0,
                 thinking_level: str | None = "minimal",
                 verbose: bool = True):
        self.model_name = normalize_gemini_model_name(model_name)
        self.api_key = api_key or _resolve_gemini_api_key()
        self.requests_per_minute = requests_per_minute
        self._min_interval = 60.0 / max(float(requests_per_minute), 0.1)
        if token_margin is None:
            token_margin = 1.6
        self.token_margin = token_margin
        self.max_retries = max_retries
        # 503 の待機（mts5.11 で 20 → 5秒。model_plan.json の reliability が正）
        self.backoff_base_s = backoff_base_s
        # 1回の生成の制限時間（秒）。None なら無制限＝従来どおり。
        # MTS の段階 A が実行直前にレーンごとに設定し、終わったら戻す。
        self.response_timeout_s = response_timeout_s
        self.thinking_budget = thinking_budget    # 2.5系用（0=完全無効）
        self.thinking_level = thinking_level      # 3系用（"minimal"等・Noneで無指定）
        # mts5.67: 400（thinking 拒否）のときの段階的な緩和の状態
        self._thinking_downgraded = False         # minimal → low へ下げた
        self._thinking_unsupported = False        # thinking 系パラメータを送らない
        self.verbose = verbose
        self._client = None            # genai.Client（初回 generate 時に生成）
        self._last_call_monotonic = None
        self._active_model = self.model_name   # 直近で成功したモデル（404切替用）
        self.calls = []                # 呼び出しログ（デバッグ・テスト用）

    @property
    def resolved_model_name(self) -> str:
        """実際に応答したモデルID（404フォールバック後は指定と異なる場合がある）。"""
        return self._active_model

    # --- 差し替え用フック（テストでモックする） ---
    def _now(self) -> float:
        return time.monotonic()

    def _sleep(self, seconds: float) -> None:
        """スロットリング（RPM制限）用の待機。"""
        if seconds > 0:
            time.sleep(seconds)

    def _backoff_sleep(self, seconds: float) -> None:
        """エラー再試行用のバックオフ待機（スロットリングと区別する）。"""
        if seconds > 0:
            time.sleep(seconds)

    # --- クライアント ---

    def _get_client(self):
        """genai.Client を遅延生成する。APIキーが無い時は具体的な案内とともに停止。"""
        if self._client is None:
            if not self.api_key:
                raise RuntimeError(
                    "Gemini APIキーが設定されていません。\n"
                    "対応方法:\n"
                    "  ① https://aistudio.google.com にアクセスし「Get API key」で"
                    "無料のAPIキーを発行（クレジットカード不要）\n"
                    "  ② Kaggle Notebook の右側パネル → Add-ons → Secrets で\n"
                    "     「GOOGLE_API_KEY」という名前で登録\n"
                    "  ③ Cell 0 を再実行（Secrets は環境変数としても展開されます）"
                )
            from google import genai   # 遅延import（ローカルテストでは不要なため）
            self._client = genai.Client(api_key=self.api_key)
            if self.verbose:
                print(f"✅ Gemini API クライアント初期化: {self.model_name}")
        return self._client

    # --- 設定組み立て ---

    def _build_config_kwargs(self, system_prompt: str, temperature: float,
                             max_tokens: int, seed: int | None) -> dict:
        """GenerateContentConfig へ渡す基本 kwargs を組み立てる。"""
        # 日本語は1トークン≈1字未満 → 文字数ベースの max_tokens では足りなくなる。
        # 余裕を持たせた上限を設定する（上限であって目標値ではないため、
        # 大きくてもコスト・品質への影響は無い）。
        out_tokens = int(max_tokens * self.token_margin) + 100
        kwargs = {
            "temperature": temperature,
            "top_p": 0.9,
            "max_output_tokens": out_tokens,
            "seed": seed,                      # None なら後段で除去
        }
        if (system_prompt or "").strip():
            kwargs["system_instruction"] = system_prompt
        return kwargs

    def _thinking_kwargs(self, model: str) -> dict:
        """モデル世代に応じた thinking 制御の kwargs を返す。

        ★落とし穴F-3対策（2026-08-26モデル切替）: thinking 系パラメータは
          世代で別物（2.5系=thinking_budget / 3系=thinking_level）。
          404フォールバックでモデルが変わっても対になる制御へ自動追従する。
        """
        m = model or self.model_name
        if getattr(self, "_thinking_unsupported", False):
            return {}                      # mts5.67: 400 で拒否された後は送らない
        if m.startswith("gemini-3"):
            level = self.thinking_level
            if level == "minimal" and (self._minimal_unsupported(m)
                                       or getattr(self, "_thinking_downgraded", False)):
                # 3.7系・3系Proは minimal 非対応（送ると400）→ 最低レベルへ。
                # mts5.67: 実機で minimal が拒否されたモデルも同様に low へ。
                level = "low"
            return {"thinking_level": level} if level else {}
        if self.thinking_budget is not None:
            return {"thinking_budget": self.thinking_budget}
        return {}

    @staticmethod
    def _minimal_unsupported(model: str) -> bool:
        """thinking_level="minimal" を送ると400になるモデル（公式対応表＋実機で確定した分）。

        mts5.68: **gemini-3.8-flash を追加**。mts5.67 の初回実機（2026-10-14）で
        「thinking_level=minimal が拒否されました。low に下げて再試行します」が出て
        minimal 非対応が確定した（拒否された 400 も RPM の枠を 1 回消費するため、
        最初から low で送って無駄な 1 往復＋待ち時間を無くす）。3.6-flash は実機で
        本応答まで届いておらず未確定＝従来どおり拒否されたら段階的に緩める。
        """
        return model.startswith(("gemini-3.7", "gemini-3.8", "gemini-3-pro",
                                 "gemini-3.1-pro", "gemini-3.7-pro"))

    def _make_config(self, system_prompt: str, temperature: float,
                     max_tokens: int, seed: int | None, model: str | None = None):
        """google.genai.types.GenerateContentConfig を生成（オプション項目は段階的に除去）。"""
        from google.genai import types

        base = self._build_config_kwargs(system_prompt, temperature,
                                         max_tokens, seed)
        use_seed = base.pop("seed")
        thinking_kwargs = self._thinking_kwargs(model or self.model_name)

        def _with(extra: dict):
            return types.GenerateContentConfig(**base, **extra)

        if use_seed is not None and thinking_kwargs:
            try:
                return _with({"seed": use_seed,
                              "thinking_config": types.ThinkingConfig(
                                  **thinking_kwargs)})
            except TypeError:
                pass
        if use_seed is not None:
            try:
                return _with({"seed": use_seed})
            except TypeError:
                pass
        if thinking_kwargs:
            try:
                return _with({"thinking_config": types.ThinkingConfig(
                    **thinking_kwargs)})
            except TypeError:
                pass
        return _with({})

    # --- 生成 ---

    def _throttle(self) -> None:
        """無料枠の RPM 制限を超えないよう、呼び出し開始の最小間隔を守る。"""
        if self._last_call_monotonic is None:
            return
        wait = self._min_interval - (self._now() - self._last_call_monotonic)
        if wait > 0:
            if self.verbose:
                print(f"   （RPM制限待ち: {wait:.1f}秒）")
            self._sleep(wait)

    def _extract_text(self, resp) -> str:
        """応答からテキストを取り出す。ブロック/空の場合は "" を返す（例外にしない）。"""
        text = None
        try:
            text = resp.text
        except (ValueError, AttributeError):
            text = None
        if text:
            return text

        # --- ブロック・空応答の診断（表示するだけ） ---
        why = []
        try:
            pf = getattr(resp, "prompt_feedback", None)
            block = getattr(pf, "block_reason", None)
            if block:
                why.append(f"プロンプトがブロック: {block}")
        except Exception:                                   # noqa: BLE001
            pass
        try:
            cands = getattr(resp, "candidates", None)
            if cands:
                fr = getattr(cands[0], "finish_reason", None)
                if fr is not None and str(fr) not in ("STOP", "FinishReason.STOP"):
                    why.append(f"finish_reason: {fr}")
        except Exception:                                   # noqa: BLE001
            pass
        if self.verbose:
            reason = "／".join(why) or "理由不明（空応答）"
            print(f"   ⚠ Gemini が空の応答を返しました（{reason}）。"
                  "検証→再生成の経路で対処します")
        return ""

    def _generate_with_timeout(self, timeout_s: float,
                               system_prompt: str, user_prompt: str,
                               temperature: float, max_tokens: int,
                               seed: int | None, model: str | None = None) -> str:
        """制限時間つきの生成（mts5.11）。

        生成は**デーモン・スレッド**で回し、時間内に返らなければ
        `ResponseTimeoutError` を送出する。待ち続けないのが目的なので、
        遅れた側のスレッドはそのまま（デーモン）捨てる。API は1回ぶん消費する。
        """
        box: dict = {}

        def _call() -> None:
            try:
                box["text"] = self._generate_once(
                    system_prompt, user_prompt, temperature, max_tokens, seed,
                    model=model)
            except BaseException as e:                    # noqa: BLE001
                box["exc"] = e

        th = threading.Thread(target=_call, name="gemini-gen", daemon=True)
        th.start()
        th.join(timeout_s)
        if th.is_alive():
            raise ResponseTimeoutError(
                f"応答が{timeout_s:g}秒を超えました（打ち切り・別モデルへ回します）")
        if "exc" in box:
            raise box["exc"]
        return box.get("text") or ""

    def _generate_once(self, system_prompt: str, user_prompt: str,
                       temperature: float, max_tokens: int,
                       seed: int | None, model: str | None = None) -> str:
        """リトライなしの1回の生成（テストでモックして使う）。"""
        client = self._get_client()
        m = model or self._active_model
        config = self._make_config(system_prompt, temperature, max_tokens, seed,
                                    model=m)
        resp = client.models.generate_content(
            model=model or self.model_name, contents=user_prompt, config=config)
        return self._extract_text(resp)

    def generate(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.7, max_tokens: int = 1000,
                 seed: int | None = None) -> str:
        self.calls.append({
            "system_len": len(system_prompt or ""),
            "user_len": len(user_prompt or ""),
            "temperature": temperature, "max_tokens": max_tokens, "seed": seed,
        })
        # 404時は候補モデルへ切替える。前回成功したモデルから開始し、
        # 毎回の generate で無駄な 404 を再試行しない。
        models = gemini_model_candidates(self.model_name)
        if self._active_model in models:
            model_i = models.index(self._active_model)
        else:
            model_i = 0
        last_exc: Exception | None = None
        attempt = 0
        n_503 = 0
        while attempt <= self.max_retries:
            model = models[min(model_i, len(models) - 1)]
            self._throttle()
            self._last_call_monotonic = self._now()
            try:
                timeout_s = getattr(self, "response_timeout_s", None)
                if timeout_s:
                    text = self._generate_with_timeout(
                        float(timeout_s), system_prompt, user_prompt,
                        temperature, max_tokens, seed, model=model)
                else:
                    text = self._generate_once(system_prompt, user_prompt,
                                               temperature, max_tokens, seed,
                                               model=model)
                self._active_model = model
                return text
            except Exception as e:                           # noqa: BLE001
                last_exc = e
                # ★mts5.11: 打ち切り（遅いだけ）はこのモデルでは再試行しない。
                #   上位（MTS の別レーン移譲）へそのまま返す。
                if isinstance(e, ResponseTimeoutError):
                    if self.verbose:
                        print(f"   ⏱ [{self.model_name}] {e}")
                    raise
                code = _api_error_code(e)
                # モデル不在 → 次の候補へ（リトライ枠を消費しない）
                if _is_not_found(e) and model_i + 1 < len(models):
                    nxt = models[model_i + 1]
                    if self.verbose:
                        print(f"   ※ モデル {model} が見つかりません（404）。"
                              f"{nxt} に切り替えて再試行します")
                    model_i += 1
                    continue
                # ★thinking 系パラメータを400で拒否された場合（mts5.67 で段階化）:
                #   minimal → low → 除去 の順に1段ずつ緩めてもう1度
                #   （リトライ枠は消費しない。それでも 400 なら致命エラーとして停止）
                if (code == 400 and "thinking" in str(e).lower()
                        and self._thinking_kwargs(model)):
                    sent = self._thinking_kwargs(model)
                    if (sent.get("thinking_level") == "minimal"
                            and not getattr(self, "_thinking_downgraded", False)):
                        self._thinking_downgraded = True
                        if self.verbose:
                            print("   ※ thinking_level=minimal が拒否されました。"
                                  "low に下げて再試行します")
                        continue
                    if not getattr(self, "_thinking_unsupported", False):
                        self._thinking_unsupported = True
                        if self.verbose:
                            print("   ※ thinking 系パラメータが拒否されました。"
                                  "除去して再試行します")
                        continue
                # 4xx（429/408以外）はリトライしても絶対に直らない → 即停止
                # ★2026-08-28: 408 Request Timeout は一時障害（実機で HD が欠落）。
                #   致命 4xx から外す。★mts5.68: 再試行は 503 と同じ「1回だけ待つ」
                #   （下の 503/408 分岐）＝指数バックオフで同じ混雑モデルを粘らない。
                if (code is not None and 400 <= code < 500
                        and code not in (408, 429)):
                    raise RuntimeError(self._fatal_message(e, code)) from e
                # 日次クォータ（RPD）枯渇は待機しても解除されない
                # → リトライせず即停止し、翌日の再開を促す（★12回目実機対応）
                if (code == 429 or code is None) and _is_daily_quota(e):
                    raise RuntimeError(self._daily_quota_message(e)) from e
                retryable = (code in (408, 429, 500, 502, 503, 504)
                             or code is None
                             and (_is_network_error(e) or _is_rate_limited(e)
                                  or _is_server_error_text(e)))
                if not retryable:
                    # 分類不能な予期せぬ例外。中身を出して即停止（握り潰さない）
                    raise RuntimeError(self._fatal_message(e, code)) from e
                # ★2026-08-28 実機: 3.7-flash の 503 high demand で
                #   20+40+80+160+320 秒待っても復旧せず約21分律速。
                #   503 は 20秒を1回だけ待ち、だめなら上位（MTS 移譲）へ返す。
                # ★mts5.68（2026-10-14 実機）: 408（Request Timeout）も同じ扱いにする。
                #   3.8-flash が 503 のあと「約100秒の無応答 → 408」を指数バックオフで
                #   叩き直し、段階 C の 1 ジョブで約 250 秒を失った。408 は混雑の別の顔
                #   なので 1 回だけ短く待って再試行し、2 回目は諦めて別モデルへ渡す
                #   （MTS 側は 408 を 503 と同じく移譲対象にする）。
                if code in (503, 408):
                    if n_503 >= 1:
                        raise RuntimeError(self._giveup_message(e, code)) from e
                    n_503 += 1
                    wait = self.backoff_base_s  # 既定 20秒・指数にしない
                    if self.verbose:
                        print(f"   ⚠ Gemini API 一時エラー（{code}）:"
                              f"{wait:.0f}秒待って再試行 "
                              f"（1/1・以降は別モデルへ）")
                    self._backoff_sleep(wait)
                    attempt += 1
                    continue
                if attempt >= self.max_retries:
                    raise RuntimeError(self._giveup_message(e, code)) from e
                wait = self.backoff_base_s * (2 ** attempt)
                if self.verbose:
                    print(f"   ⚠ Gemini API 一時エラー（{code or 'network'}）:"
                          f"{wait:.0f}秒待って再試行 "
                          f"（{attempt + 1}/{self.max_retries}）")
                self._backoff_sleep(wait)
                attempt += 1
        raise RuntimeError(self._giveup_message(last_exc, None)) from last_exc

    # --- エラーメッセージ ---

    def _fatal_message(self, exc: Exception, code: int | None) -> str:
        s = str(exc)[:400]
        hint = ""
        if code in (401, 403):
            hint = ("APIキーが無効か権限がありません。Kaggle の Secrets"
                    "「GOOGLE_API_KEY」を確認してください。")
        elif code == 404:
            tried = " → ".join(gemini_model_candidates(self.model_name))
            hint = (f"モデル {self.model_name} が見つかりません"
                    f"（試行: {tried}）。Cell 0 の MODEL_NAME を確認してください"
                    f"（例: '{GeminiBackend.DEFAULT_MODEL}'）。")
        elif code == 400:
            hint = "リクエストが拒否されました（モデル名・パラメータを確認）。"
        return f"Gemini API エラー（HTTP {code}）: {hint}\n（詳細: {s}）"

    def _daily_quota_message(self, exc: Exception) -> str:
        """日次クォータ（RPD）枯渇時のメッセージ（リトライせず即停止する）。"""
        return (
            "Gemini API の無料枠（1日あたりのリクエスト上限）を使い切りました。\n"
            "対処: 翌日（太平洋時間の深夜0時にリセット）にこのノートブックを再実行"
            "してください。\n"
            "完了済みのMTS結果は再利用され、続きから再開できます。\n"
            f"（詳細: {str(exc)[:300]}）"
        )

    def _giveup_message(self, exc: Exception, code: int | None) -> str:
        s = str(exc)[:400]
        if code == 429:
            return (
                "Gemini API のレート制限（429）が解除されず、リトライ上限に達しました。\n"
                "考えられる原因:\n"
                "  ・無料枠の1日あたりリクエスト上限に達した（→ 翌日以降に再実行）\n"
                "  ・他のノートブック・アプリで同じキーを使い果たしている\n"
                "対処: このまま再実行すれば、完了済みのMTS結果は再利用され、\n"
                "続きから再開できます。"
                f"\n（詳細: {s}）"
            )
        if code in (503, 408):
            # mts5.68: 混雑（503）・無応答（408）は 1 回だけ待って諦める。MTS 側が
            # 文字列からも判定できるようコードを明示する（_is_stealable）。
            return (f"Gemini API が混雑しています（{code}）。1回待っても回復しなかった"
                    f"ため、このモデルでは諦めます（別モデルへ移譲）。\n（詳細: {s}）")
        return (f"Gemini API への接続が {self.max_retries + 1} 回連続で失敗しました"
                f"（ネットワーク不良の可能性）。\n（詳細: {s}）")



# ============================================================
# 疎通確認（Cell 0.1 が本番の前に 1〜3 リクエストだけ使う）
# ------------------------------------------------------------
# ★v1.0.0 公開前の実機（2026-10-15）: 疎通に使っていた gemini-3.1-flash-lite が
#   Gemini 側の混雑（503 "This model is currently experiencing high demand"）を
#   3 回連続で返し、セルフテストが止まって本番に進めなかった。503 は**キー・
#   Dataset・Notebook の異常ではない**（キー不正は 400/403、モデル名違いは 404、
#   日次枠切れは 429 になる）。本番の MTS は混雑したモデルを別モデルへ移譲する
#   （mts._is_stealable）のに、疎通だけが 1 モデルで諦めていたので、疎通も同じ
#   思想で軽量モデルを順に試す。上位 gemini-3.8-flash は日次枠を守るため使わない。
PING_MODELS = ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite",
               "gemini-3-flash-preview")
PING_SYSTEM_PROMPT = "あなたは疎通確認用の応答装置です。"
PING_USER_PROMPT = "「API OK」とだけ返してください。"


def is_congestion_error(exc: BaseException) -> bool:
    """混雑（503）／無応答（408）由来の失敗か（backend の諦め文言・原因例外の両方で判定）。"""
    for e in (exc, getattr(exc, "__cause__", None)):
        if e is None:
            continue
        if isinstance(e, ResponseTimeoutError):
            return True
        if _api_error_code(e) in (503, 408):
            return True
        s = str(e)
        if ("混雑しています（503）" in s or "混雑しています（408）" in s
                or "503" in s or "UNAVAILABLE" in s or "high demand" in s.lower()):
            return True
    return False


class PingResult:
    """`ping_gemini` の結果。status は ok / congested / fatal / empty / no_key。"""

    def __init__(self, status: str, model: str = "", reply: str = "",
                 seconds: float = 0.0, error: str = ""):
        self.status = status
        self.model = model
        self.reply = reply
        self.seconds = seconds
        self.error = error
        self.tried: list = []          # [(モデル名, 1 行の結果)]

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def __repr__(self) -> str:  # pragma: no cover - デバッグ用
        return (f"PingResult(status={self.status!r}, model={self.model!r}, "
                f"tried={self.tried!r})")


def ping_gemini(api_key: str | None = None, models=PING_MODELS,
                backend_factory=None, backoff_base_s: float = 10.0,
                max_tokens: int = 64, log=print) -> PingResult:
    """軽量モデルを順に 1 回ずつ叩き、最初に応答したモデルを返す。

    - 混雑（503/408）だけ次のモデルへ進む。致命エラー（400/403/404・日次 429 など）は
      別モデルでも直らないので、その場で `fatal` として返す（旧挙動と同じ）。
    - 全モデルが混雑なら `congested`（＝Gemini 側の都合。時間をおいて再実行）。
    - 例外は投げない（呼び出し側の Cell 0.1 が except の外で SystemExit できるように）。
    """
    api_key = api_key or _resolve_gemini_api_key()
    res = PingResult("no_key")
    if not api_key:
        return res
    if backend_factory is None:
        def backend_factory(model: str):
            # 疎通は長く粘らない: 503/408 は 1 回だけ待つ（backend の規則）、
            # 429（分）・ネットワーク系も 2 回まで（10 + 20 秒）で諦めて分類する。
            return GeminiBackend(model_name=model, api_key=api_key,
                                 requests_per_minute=60.0, max_retries=2,
                                 backoff_base_s=backoff_base_s, verbose=False)
    res.status = "congested"
    for model in models:
        be = backend_factory(model)
        t0 = time.time()
        try:
            text = be.generate(PING_SYSTEM_PROMPT, PING_USER_PROMPT,
                               temperature=0.0, max_tokens=max_tokens)
        except Exception as e:  # noqa: BLE001 - 分類して返す（握り潰さない）
            first = str(e).splitlines()[0] if str(e) else type(e).__name__
            if is_congestion_error(e):
                res.tried.append((model, f"混雑: {first}"))
                log(f"   ⚠ {model} は混雑中（Gemini 側の 503/408）"
                    "→ 次の軽量モデルで疎通を試します")
                continue
            res.status = "fatal"
            res.error = first
            res.tried.append((model, first))
            return res
        dt = time.time() - t0
        resolved = getattr(be, "resolved_model_name", model) or model
        if not text or not str(text).strip():
            res.status = "empty"
            res.model = resolved
            res.seconds = dt
            res.error = "Gemini API が空の応答を返しました"
            res.tried.append((model, "空応答"))
            return res
        res.status = "ok"
        res.model = resolved
        res.reply = str(text).strip()
        res.seconds = dt
        res.tried.append((model, "OK"))
        return res
    res.error = ("軽量モデル（" + "・".join(models) + "）がすべて混雑（503/408）"
                 "でした。Gemini 側の一時的な混雑で、API キー・Dataset・Notebook は正常です。")
    return res
