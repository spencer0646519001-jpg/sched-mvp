# core/ui_views.py
import json
from datetime import date

from django.shortcuts import render
from django.test.client import RequestFactory
from django.views.decorators.http import require_http_methods

from app import generate_day as gd
from core.api_views import api_monthly_export_csv, api_monthly_preview_mirror, api_monthly_refine_mirror


UI_TRANSLATIONS = {
    "ja": {
        "page_title": "月間シフト作成ワークスペース",
        "hero_desc": "プレビューとCSV出力は同じペイロードを使います:",
        "controls": "コントロール",
        "year_month": "年月",
        "language": "言語",
        "leave_requests": "休暇申請",
        "leave_help": "スタッフと日付を選択して追加。対象日はプレビュー/出力で OFF になります。",
        "person": "スタッフ",
        "date": "日付",
        "add_leave": "休暇を追加",
        "no_leave_selected": "まだ休暇日は選択されていません。",
        "actions": "アクション",
        "preview": "プレビュー",
        "download_csv": "CSVをダウンロード",
        "refine_title": "シフト調整",
        "refine_help": "自然言語で調整指示を入力し、差分プレビュー後に Apply / Save してください。",
        "refine_text_label": "調整テキスト",
        "refine_preview": "調整プレビュー",
        "apply_save": "適用 / 保存",
        "diff_preview": "差分プレビュー",
        "no_diff": "差分はありません。",
        "no_refine_result_yet": "まだ調整結果はありません。",
        "refine_parse_failed": "調整テキストの解析に失敗しました。",
        "apply_succeeded": "適用が完了しました。",
        "refine_failed": "調整プレビューに失敗しました。",
        "request_error": "リクエストエラー",
        "weekly_rest_warnings": "週休チェック警告",
        "weekly_ok": "OK: 週休チェックを満たしています。",
        "run_preview_hint": "プレビューを実行して週休制約を確認してください。",
        "explain_trace": "Explain / Decision Trace",
        "summary_with_warnings_prefix": "概要:",
        "summary_with_warnings_suffix": "件の警告。フルISO週でOFFが2日未満のスタッフが表示されます。",
        "summary_no_warnings": "概要: このプレビューではフルISO週の週休警告はありません。",
        "summary_waiting_preview": "概要はプレビュー後に表示されます。",
        "explain_date": "Explain 日付",
        "generate_explanation": "説明を生成",
        "explain_optional_endpoint": "任意連携エンドポイント",
        "explain_unavailable_until_generated": "生成されるまで Explain は利用できません。",
        "people_grid": "スタッフグリッド",
        "name": "名前",
        "role_chef": "シェフ",
        "role_staff": "スタッフ",
        "role_unknown": "不明",
        "invalid_leave_json": "leave_requests のJSONが不正です。dict[str, list[str]] を指定してください。",
        "preview_failed": "プレビューに失敗しました。",
        "csv_export_failed": "CSV出力に失敗しました。",
        "explain_choose_valid_date": "Explain は現在利用できません: 有効な日付を選択してください。",
        "generating_explanation": "説明を生成中...",
        "explanation_generated_for": "説明を生成しました: ",
        "explain_unavailable": "Explain は現在利用できません。",
    },
    "en": {
        "page_title": "Monthly Scheduling Workspace",
        "hero_desc": "Preview and export use the same payload:",
        "controls": "Controls",
        "year_month": "Year Month",
        "language": "Language",
        "leave_requests": "Leave Requests",
        "leave_help": "Select person + date, then add. Each date becomes OFF in preview/export.",
        "person": "Person",
        "date": "Date",
        "add_leave": "Add Leave",
        "no_leave_selected": "No leave dates selected yet.",
        "actions": "Actions",
        "preview": "Preview",
        "download_csv": "Download CSV",
        "refine_title": "Refine Schedule",
        "refine_help": "Input natural-language schedule adjustments, then preview diff before apply/save.",
        "refine_text_label": "Refine Text",
        "refine_preview": "Refine Preview",
        "apply_save": "Apply / Save",
        "diff_preview": "Diff Preview",
        "no_diff": "No changes detected.",
        "no_refine_result_yet": "No refine result yet",
        "refine_parse_failed": "Refine parse failed",
        "apply_succeeded": "Apply succeeded",
        "refine_failed": "Refine preview failed.",
        "request_error": "Request Error",
        "weekly_rest_warnings": "Weekly Rest Warnings",
        "weekly_ok": "OK: weekly rest checks passed.",
        "run_preview_hint": "Run Preview to evaluate weekly rest constraints.",
        "explain_trace": "Explain / Decision Trace",
        "summary_with_warnings_prefix": "Summary:",
        "summary_with_warnings_suffix": "warning(s). People with <2 OFF days in a full ISO week are highlighted.",
        "summary_no_warnings": "Summary: no weekly rest warnings for full ISO weeks in this preview.",
        "summary_waiting_preview": "Summary will appear after preview.",
        "explain_date": "Explain Date",
        "generate_explanation": "Generate Explanation",
        "explain_optional_endpoint": "Optional integration endpoint",
        "explain_unavailable_until_generated": "Explain currently unavailable until generated.",
        "people_grid": "People Grid",
        "name": "Name",
        "role_chef": "chef",
        "role_staff": "staff",
        "role_unknown": "unknown",
        "invalid_leave_json": "Invalid JSON in leave_requests. Expected dict[str, list[str]].",
        "preview_failed": "Preview failed.",
        "csv_export_failed": "CSV export failed.",
        "explain_choose_valid_date": "Explain currently unavailable: choose a valid date.",
        "generating_explanation": "Generating explanation...",
        "explanation_generated_for": "Explanation generated for ",
        "explain_unavailable": "Explain currently unavailable.",
    },
    "zh": {
        "page_title": "月度排班工作台",
        "hero_desc": "預覽與匯出使用同一個 payload：",
        "controls": "控制項",
        "year_month": "年月",
        "language": "語言",
        "leave_requests": "請假申請",
        "leave_help": "選擇人員與日期後新增。該日期在預覽/匯出會標記為 OFF。",
        "person": "人員",
        "date": "日期",
        "add_leave": "新增請假",
        "no_leave_selected": "尚未選擇請假日期。",
        "actions": "操作",
        "preview": "預覽",
        "download_csv": "下載 CSV",
        "refine_title": "調整排班",
        "refine_help": "輸入自然語言調整指令，先看差異預覽，再 Apply / Save。",
        "refine_text_label": "調整文字",
        "refine_preview": "調整預覽",
        "apply_save": "套用 / 儲存",
        "diff_preview": "差異預覽",
        "no_diff": "沒有偵測到變更。",
        "no_refine_result_yet": "尚未有調整結果。",
        "refine_parse_failed": "調整文字解析失敗。",
        "apply_succeeded": "套用成功。",
        "refine_failed": "調整預覽失敗。",
        "request_error": "請求錯誤",
        "weekly_rest_warnings": "每週休息警示",
        "weekly_ok": "OK：每週休息檢查通過。",
        "run_preview_hint": "請先執行預覽以檢查每週休息限制。",
        "explain_trace": "Explain / 決策軌跡",
        "summary_with_warnings_prefix": "摘要：",
        "summary_with_warnings_suffix": "筆警示。完整 ISO 週中 OFF 少於 2 天的人員會被標示。",
        "summary_no_warnings": "摘要：本次預覽在完整 ISO 週沒有每週休息警示。",
        "summary_waiting_preview": "摘要會在預覽後顯示。",
        "explain_date": "Explain 日期",
        "generate_explanation": "產生說明",
        "explain_optional_endpoint": "可選整合端點",
        "explain_unavailable_until_generated": "尚未產生前，Explain 暫時不可用。",
        "people_grid": "人員排班表",
        "name": "姓名",
        "role_chef": "主廚",
        "role_staff": "員工",
        "role_unknown": "未知",
        "invalid_leave_json": "leave_requests JSON 格式錯誤，預期為 dict[str, list[str]]。",
        "preview_failed": "預覽失敗。",
        "csv_export_failed": "CSV 匯出失敗。",
        "explain_choose_valid_date": "Explain 暫時不可用：請選擇有效日期。",
        "generating_explanation": "正在產生說明...",
        "explanation_generated_for": "說明已產生：",
        "explain_unavailable": "Explain 暫時不可用。",
    },
}

VOICE_UI_TRANSLATIONS = {
    "ja": {
        "voice_input": "音声入力",
        "listening": "聞き取り中...",
        "stop": "停止",
        "voice_unsupported": "このブラウザは音声入力に対応していません。",
        "voice_failed": "音声認識に失敗しました。",
        "voice_status_idle": "待機中",
        "voice_status_listening": "聞き取り中",
        "voice_status_transcribing": "文字起こし中",
        "voice_status_unsupported": "未対応",
        "voice_status_error": "エラー",
        "voice_transcribing": "音声を文字起こし中...",
        "voice_transcribe_failed_fallback": "文字起こしに失敗しました。ブラウザ音声認識に切り替えます。",
        "voice_recording_start_failed": "録音を開始できませんでした。ブラウザ音声認識に切り替えます。",
        "voice_recording_unsupported_fallback": "録音が使えないため、ブラウザ音声認識を使います。",
    },
    "en": {
        "voice_input": "Voice Input",
        "listening": "Listening...",
        "stop": "Stop",
        "voice_unsupported": "Voice input not supported in this browser.",
        "voice_failed": "Voice recognition failed.",
        "voice_status_idle": "Idle",
        "voice_status_listening": "Listening",
        "voice_status_transcribing": "Transcribing",
        "voice_status_unsupported": "Unsupported",
        "voice_status_error": "Error",
        "voice_transcribing": "Transcribing audio...",
        "voice_transcribe_failed_fallback": "Transcription failed. Falling back to browser speech recognition.",
        "voice_recording_start_failed": "Unable to start recording. Falling back to browser speech recognition.",
        "voice_recording_unsupported_fallback": "Audio recording unsupported. Falling back to browser speech recognition.",
    },
    "zh": {
        "voice_input": "語音輸入",
        "listening": "聆聽中...",
        "stop": "停止",
        "voice_unsupported": "這個瀏覽器不支援語音輸入。",
        "voice_failed": "語音辨識失敗。",
        "voice_status_idle": "閒置",
        "voice_status_listening": "聆聽中",
        "voice_status_transcribing": "轉寫中",
        "voice_status_unsupported": "不支援",
        "voice_status_error": "錯誤",
        "voice_transcribing": "正在將語音轉為文字...",
        "voice_transcribe_failed_fallback": "轉寫失敗，已切換到瀏覽器語音辨識。",
        "voice_recording_start_failed": "無法開始錄音，已切換到瀏覽器語音辨識。",
        "voice_recording_unsupported_fallback": "錄音不可用，改用瀏覽器語音辨識。",
    },
}


def _voice_translation_pack(language: str) -> dict:
    merged = dict(VOICE_UI_TRANSLATIONS["en"])
    merged.update(VOICE_UI_TRANSLATIONS.get(language, {}))
    return merged


def _translation_pack(language: str) -> dict:
    lang = language if language in UI_TRANSLATIONS else "ja"
    return {
        "lang": lang,
        "t": UI_TRANSLATIONS[lang],
        "translations_json": json.dumps(UI_TRANSLATIONS, ensure_ascii=False),
    }


@require_http_methods(["GET"])
def ui_home(request):
    return render(request, "ui/home.html")


@require_http_methods(["GET", "POST"])
def ui_monthly(request):
    year_month = request.POST.get("year_month") if request.method == "POST" else date.today().strftime("%Y-%m")
    language = request.POST.get("language", "ja")
    leave_requests_raw = request.POST.get("leave_requests", "{}")
    refine_text = request.POST.get("refine_text", "")
    refine_preview_raw = request.POST.get("refine_preview_json", "")
    action = request.POST.get("action", "")

    tr = _translation_pack(language)
    t_pack = dict(tr["t"])
    t_pack.setdefault("refine_title", "Refine Schedule")
    t_pack.setdefault("refine_help", "Input natural-language schedule adjustments, then preview diff before apply/save.")
    t_pack.setdefault("refine_text_label", "Refine Text")
    t_pack.setdefault("refine_preview", "Refine Preview")
    t_pack.setdefault("apply_save", "Apply / Save")
    t_pack.setdefault("diff_preview", "Diff Preview")
    t_pack.setdefault("apply_succeeded", "Apply succeeded")
    t_pack.setdefault("apply_done", t_pack["apply_succeeded"])
    t_pack.setdefault("refine_failed", "Refine preview failed.")
    t_pack.setdefault("refine_parse_failed", "Refine parse failed")
    t_pack.setdefault("no_diff", "No changes detected.")
    t_pack.setdefault("no_refine_result_yet", "No refine result yet")
    for key, value in _voice_translation_pack(tr["lang"]).items():
        t_pack.setdefault(key, value)

    ui_translations = json.loads(tr["translations_json"])
    for lang, pack in ui_translations.items():
        pack.setdefault("refine_title", "Refine Schedule")
        pack.setdefault("refine_help", "Input natural-language schedule adjustments, then preview diff before apply/save.")
        pack.setdefault("refine_text_label", "Refine Text")
        pack.setdefault("refine_preview", "Refine Preview")
        pack.setdefault("apply_save", "Apply / Save")
        pack.setdefault("diff_preview", "Diff Preview")
        pack.setdefault("apply_succeeded", "Apply succeeded")
        pack.setdefault("apply_done", pack["apply_succeeded"])
        pack.setdefault("refine_failed", "Refine preview failed.")
        pack.setdefault("refine_parse_failed", "Refine parse failed")
        pack.setdefault("no_diff", "No changes detected.")
        pack.setdefault("no_refine_result_yet", "No refine result yet")
        for key, value in _voice_translation_pack(lang).items():
            pack.setdefault(key, value)

    context = {
        "year_month": year_month,
        "language": tr["lang"],
        "leave_requests_raw": leave_requests_raw,
        "refine_text": refine_text,
        "refine_preview_json": refine_preview_raw,
        "worker_names": _load_worker_names(),
        "preview_data": None,
        "refine_data": None,
        "apply_notice": "",
        "error_message": "",
        "t": t_pack,
        "ui_translations_json": json.dumps(ui_translations, ensure_ascii=False),
    }

    if request.method == "POST":
        try:
            leave_requests = json.loads(leave_requests_raw or "{}")
        except json.JSONDecodeError:
            context["error_message"] = context["t"]["invalid_leave_json"]
            return render(request, "ui/monthly.html", context)
        context["leave_requests_raw"] = json.dumps(leave_requests, ensure_ascii=False)

        payload = {
            "year_month": year_month,
            "language": context["language"],
            "leave_requests": leave_requests,
        }

        rf = RequestFactory()

        if action == "preview":
            internal_request = rf.post(
                "/api/monthly/preview",
                data=json.dumps(payload),
                content_type="application/json",
            )
            api_response = api_monthly_preview_mirror(internal_request)
            if api_response.status_code == 200:
                context["preview_data"] = json.loads(api_response.content.decode("utf-8"))
            else:
                try:
                    err = json.loads(api_response.content.decode("utf-8"))
                    context["error_message"] = err.get("detail") or context["t"]["preview_failed"]
                except json.JSONDecodeError:
                    context["error_message"] = f"Preview failed (HTTP {api_response.status_code})."

        if action == "download":
            internal_request = rf.post(
                "/api/monthly/export.csv",
                data=json.dumps(payload),
                content_type="application/json",
            )
            api_response = api_monthly_export_csv(internal_request)
            if api_response.status_code == 200:
                return api_response
            try:
                err = json.loads(api_response.content.decode("utf-8"))
                context["error_message"] = err.get("detail") or context["t"]["csv_export_failed"]
            except json.JSONDecodeError:
                context["error_message"] = f"CSV export failed (HTTP {api_response.status_code})."

        if action == "refine_preview":
            refine_payload = dict(payload)
            refine_payload["refine_text"] = refine_text
            internal_request = rf.post(
                "/api/monthly/refine",
                data=json.dumps(refine_payload),
                content_type="application/json",
            )
            api_response = api_monthly_refine_mirror(internal_request)
            if api_response.status_code == 200:
                refine_data = json.loads(api_response.content.decode("utf-8"))
                context["refine_data"] = refine_data
                context["refine_preview_json"] = json.dumps(refine_data, ensure_ascii=False)
                parse_errors = refine_data.get("parse_errors") if isinstance(refine_data, dict) else None
                if isinstance(parse_errors, list) and parse_errors:
                    messages = [
                        str(item.get("message", "")).strip()
                        for item in parse_errors
                        if isinstance(item, dict) and str(item.get("message", "")).strip()
                    ]
                    message = "; ".join(messages[:3]).strip()
                    if message:
                        context["error_message"] = f"{context['t']['refine_parse_failed']}: {message}"
                    else:
                        context["error_message"] = context["t"]["refine_parse_failed"]
            else:
                try:
                    err = json.loads(api_response.content.decode("utf-8"))
                    parse_errors = err.get("parse_errors") if isinstance(err, dict) else None
                    if isinstance(parse_errors, list) and parse_errors:
                        messages = [
                            str(item.get("message", "")).strip()
                            for item in parse_errors
                            if isinstance(item, dict) and str(item.get("message", "")).strip()
                        ]
                        message = "; ".join(messages[:3]).strip()
                        if message:
                            context["error_message"] = f"{context['t']['refine_parse_failed']}: {message}"
                        else:
                            context["error_message"] = context["t"]["refine_parse_failed"]
                    else:
                        context["error_message"] = err.get("detail") or context["t"]["refine_failed"]
                except json.JSONDecodeError:
                    context["error_message"] = f"Refine failed (HTTP {api_response.status_code})."

        if action == "apply_refine":
            try:
                refine_data = json.loads(refine_preview_raw or "{}")
            except json.JSONDecodeError:
                refine_data = {}

            preview_people_grid = refine_data.get("preview_people_grid")
            if isinstance(preview_people_grid, dict):
                context["preview_data"] = {
                    "people_grid": preview_people_grid,
                    "weekly_rest_warnings": refine_data.get("weekly_rest_warnings", []),
                    "warnings": refine_data.get("warnings", []),
                }
                context["refine_data"] = refine_data
                context["refine_preview_json"] = json.dumps(refine_data, ensure_ascii=False)
                context["apply_notice"] = context["t"]["apply_succeeded"]
            else:
                context["error_message"] = context["t"]["refine_failed"]

    return render(request, "ui/monthly.html", context)


def _load_worker_names():
    try:
        workers = gd.load_json("workers.json").get("people", [])
    except Exception:
        workers = []
    return [person.get("name") for person in workers if isinstance(person, dict) and person.get("name")]
