import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NpxCacheCompatibilityTests(unittest.TestCase):
    def test_package_runs_cache_compatibility_postinstall(self):
        manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["scripts"]["postinstall"],
            "node scripts/npx-cache-compat.mjs",
        )

    def test_compatibility_script_only_writes_inside_npx_cache(self):
        source = (ROOT / "scripts" / "npx-cache-compat.mjs").read_text(encoding="utf-8")
        self.assertIn('pathParts.includes("_npx")', source)
        self.assertIn('resolve(npxCacheRoot, "package.json")', source)
        self.assertIn('writeFileSync(packageJsonPath', source)

    def test_runtime_subprocesses_receive_persistent_storage_environment(self):
        source = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
        self.assertIn('THUNDERBOLT_STORAGE_DIR: storageDir', source)
        self.assertIn('"worker de automação", runtimeEnv', source)
        self.assertIn('"worker do pipeline de vídeos", runtimeEnv', source)

    def test_launcher_detects_pipeline_tasks_in_configured_storage(self):
        source = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
        self.assertIn('const storageDir = process.env.THUNDERBOLT_STORAGE_DIR || join(thunderboltHome, "storage");', source)
        self.assertIn('readFileSync(join(storageDir, "state", filename)', source)
        self.assertNotIn('readFileSync(join(thunderboltHome, "storage", "state", filename)', source)

    def test_pipeline_worker_stays_available_for_manual_start(self):
        source = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
        start_block = source.split("function startPipelineWorker()", 1)[1].split("function monitorWorkers()", 1)[0]
        monitor_block = source.split("function monitorWorkers()", 1)[1].split("function startStreamlit()", 1)[0]
        self.assertIn('if (shuttingDown || pipelineWorker) return;', start_block)
        self.assertNotIn('!hasPendingPipelineWork()', start_block)
        self.assertIn('startPipelineWorker();', monitor_block)
        self.assertNotIn('stopPipelineWorker();', monitor_block)

    def test_install_recovers_ai_influencer_database_from_previous_npx_cache(self):
        source = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
        self.assertIn('function migrateLegacyNpxStorage()', source)
        self.assertIn('ai_influencers.db', source)
        self.assertIn('copyMissingTree(join(candidate, "storage"), targetStorage)', source)
        self.assertIn('migrateLegacyNpxStorage();', source)

    def test_install_persists_dependency_hash_inside_venv_and_checks_growth_dependencies(self):
        source = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
        self.assertIn('const markerPath = join(venvPath, `.${stateKey}.sha256`);', source)
        self.assertIn('const persistedHashMatches = hashMatches || markerHash === currentHash;', source)
        self.assertIn('"yt_dlp"', source)
        self.assertIn('"youtube_transcript_api"', source)

    def test_ffmpeg_seed_install_reuses_existing_binary(self):
        source = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
        self.assertIn("function findFileRecursive(directory, filename)", source)
        self.assertIn('const existingBinary = findFileRecursive(destination, "ffmpeg.exe");', source)
        self.assertIn("FFmpeg 7.1 já instalado; será reutilizado", source)
        self.assertIn("if (existingBinary) {", source)

    def test_npx_storage_migration_is_one_time(self):
        source = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
        self.assertIn('npx-storage-migration-v1.json', source)
        self.assertIn('if (existsSync(migrationMarker)) return;', source)

    def test_required_commands_remain_documented_without_extra_flags(self):
        source = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
        self.assertIn('args[0] === "install"', source)
        self.assertIn('args[0] === "worker"', source)
        self.assertIn('"3030"', source)

    def test_streamlit_uses_preimport_encoding_bootstrap(self):
        source = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
        bootstrap = (ROOT / "scripts" / "streamlit_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn('const streamlitBootstrap = resolve(root, "scripts", "streamlit_bootstrap.py");', source)
        self.assertIn('[streamlitBootstrap, "run", main', source)
        self.assertIn('from streamlit.web.cli import main', bootstrap)
        self.assertLess(bootstrap.index('os.environ["PYTHONIOENCODING"]'), bootstrap.index('from streamlit.web.cli import main'))

    def test_dynamic_chunk_recovery_does_not_reset_its_session_guard(self):
        source = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
        recovery = source.split("const dynamicChunkRecoveryScript", 1)[1].split("const proxy", 1)[0]
        self.assertIn('sessionStorage.setItem(key, String(now));', recovery)
        self.assertNotIn('sessionStorage.removeItem(key)', recovery)

    def test_proxy_requests_uncompressed_html_for_chunk_recovery_injection(self):
        source = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
        self.assertIn('"accept-encoding": "identity"', source)

    def test_proxy_disables_cache_only_for_dynamic_html(self):
        source = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
        cache_block = source.split("const isHtml", 1)[1].split("if (!isHtml)", 1)[0]
        self.assertIn("if (isHtml)", cache_block)
        self.assertIn('responseHeaders["cache-control"] = "no-store', cache_block)

    def test_streamlit_bootstrap_owns_sigint_without_click_shutdown(self):
        bootstrap = (ROOT / "scripts" / "streamlit_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("def _custom_sigint_handler", bootstrap)
        self.assertIn("SIGINT ignorado", bootstrap)
        self.assertNotIn("os._exit(0)", bootstrap)
        self.assertIn("_original_signal(signal.SIGINT, _custom_sigint_handler)", bootstrap)
        self.assertIn("signal.signal = _protected_signal", bootstrap)
        self.assertNotIn("server.stop()", bootstrap)

    def test_package_manifest_includes_python_streamlit_bootstrap(self):
        manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("scripts/*.py", manifest["files"])


if __name__ == "__main__":
    unittest.main()
