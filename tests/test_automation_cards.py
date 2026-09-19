from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


class AutomationCardsTests(unittest.TestCase):
    def test_automation_video_cards_have_start_and_stop_controls(self):
        self.assertIn('key=f"automation_start_{task[\'id\']}"', MAIN_SOURCE)
        self.assertIn('key=f"automation_stop_{task[\'id\']}"', MAIN_SOURCE)
        self.assertIn('key=f"automation_delete_{task[\'id\']}"', MAIN_SOURCE)
        self.assertIn('delete_task(task["id"])', MAIN_SOURCE)
        self.assertIn('st.button("Apagar"', MAIN_SOURCE)
        self.assertIn('def _start_pipeline_task(task_id: str, state: str) -> bool:', MAIN_SOURCE)
        self.assertIn('_start_pipeline_task(str(task["id"]), state)', MAIN_SOURCE)
        self.assertIn('if not updated:', MAIN_SOURCE)
        self.assertIn('stop_task_by_user(task["id"])', MAIN_SOURCE)
        self.assertIn('Stoped by User', MAIN_SOURCE)
        self.assertIn("a nova tentativa lê as chaves, prioridades e configurações actualmente guardadas", MAIN_SOURCE)

    def test_manual_stop_has_distinct_user_label_and_preserves_internal_blocked_state(self):
        self.assertIn('def stop_task_by_user(task_id: str)', (ROOT / "hermes_ui" / "domain.py").read_text(encoding="utf-8"))
        self.assertIn('task.get("stop_reason") == "user"', MAIN_SOURCE)
        self.assertIn('persisted["stop_reason"] = "user"', (ROOT / "hermes_ui" / "domain.py").read_text(encoding="utf-8"))

    def test_automation_video_cards_do_not_render_channel_schedule(self):
        self.assertNotIn('st.caption("Horário do canal")', MAIN_SOURCE)
        self.assertIn('st.text_input("Horário (HH:MM)"', MAIN_SOURCE)

    def test_youtube_video_cards_refresh_every_five_seconds_in_fragment(self):
        self.assertIn('@st.fragment(run_every=5.0)\ndef _render_youtube_automation_cards():', MAIN_SOURCE)
        self.assertNotIn('@st.fragment\ndef _render_youtube_automation_cards():', MAIN_SOURCE)
        youtube_block = MAIN_SOURCE.split('def _render_youtube_automation_cards():', 1)[1].split('def _facebook_pages_for_automation():', 1)[0]
        self.assertIn('if not _has_script_context():', youtube_block)

    def test_youtube_channel_settings_use_independent_fragment_and_local_rerun(self):
        self.assertIn('@st.fragment\ndef _render_youtube_automation_channel_cards():', MAIN_SOURCE)
        self.assertIn('st.rerun(scope="fragment")', MAIN_SOURCE)
        page_block = MAIN_SOURCE.split('def render_automation():', 1)[1].split('def render_upload_direct():', 1)[0]
        self.assertIn('_render_youtube_automation_channel_cards()', page_block)

    def test_youtube_channel_save_consolidates_configuration_payload(self):
        channel_block = MAIN_SOURCE.split('def _render_youtube_automation_channel_cards():', 1)[1].split('def render_automation():', 1)[0]
        save_block = channel_block.split('if st.button("Guardar"', 1)[1].split('st.success("Agendamento guardado.")', 1)[0]
        self.assertEqual(save_block.count('update_channel(channel_id, {'), 1)
        for field in ('"automation_time"', '"average_video_time"', '"default_blueprint_id"', '"default_voice"', '"default_thumbnail_blueprint_id"'):
            self.assertIn(field, save_block)

    def test_automation_cards_expose_remake_action_for_both_platforms(self):
        self.assertIn('"Refazer Vídeo"', MAIN_SOURCE)
        self.assertIn('tiktok_automation_remake_video_', MAIN_SOURCE)
        self.assertIn('automation_remake_video_', MAIN_SOURCE)
        self.assertIn('remake_video_task(task_id)', MAIN_SOURCE)

    def test_bilibili_automation_cards_expose_the_same_remake_action(self):
        self.assertIn('def _render_bilibili_automation_cards()', MAIN_SOURCE)
        self.assertIn('bilibili_automation_remake_video_', MAIN_SOURCE)
        self.assertIn('"Automação Bilibili": render_bilibili_automation', MAIN_SOURCE)
        self.assertIn('classify_channel_platform(channel)', MAIN_SOURCE)
        self.assertIn('return "bilibili"', MAIN_SOURCE)

    def test_remake_operation_preserves_creative_artifacts_and_clears_only_video_upload(self):
        domain_source = (ROOT / "hermes_ui" / "domain.py").read_text(encoding="utf-8")
        self.assertIn('def remake_video_task(task_id: str)', domain_source)
        self.assertIn('artifacts.pop("video", None)', domain_source)
        self.assertIn('artifacts.pop("upload", None)', domain_source)
        self.assertIn('"stage": "video"', domain_source)
        self.assertIn('"state": "to_do"', domain_source)


if __name__ == "__main__":
    unittest.main()
