"""Streamlit UI for the AI Influencers domain."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
from pathlib import Path
from typing import Any, Mapping

import streamlit as st

from hermes_ui.influencers import (
    BACKEND_OPTIONS,
    InfluencerBackendError,
    STANDALONE_CONTENT_INFLUENCER_ID,
    backend_name,
    backend_status,
    ensure_standalone_content_owner,
    get_repository,
    test_backend,
)
from hermes_ui.media_generation import (
    MediaGenerationError,
    generate_image_for_card,
    generate_motion_control_video,
    generate_ugc_product_video,
    generate_video_for_card,
    validate_motion_control_file,
)
from hermes_ui.creative_generation import generate_ugc_segment_prompts
from hermes_ui.media_providers import media_cards_for_pool, media_provider_definition
from hermes_ui.notifications import record_notification
from hermes_ui.storage import STORAGE, ensure_storage


CONTENT_STATES = {
    "queued": "Na fila",
    "image_queued": "Na fila de imagens",
    "running": "Em execução",
    "completed": "Concluído",
    "failed": "Falha",
    "cancelled": "Cancelado",
    "blocked": "Bloqueado",
}
PLATFORM_OPTIONS = ["Instagram", "TikTok", "YouTube Shorts", "Facebook"]


def _repository(settings: Mapping[str, Any]):
    try:
        return get_repository(settings)
    except InfluencerBackendError as exc:
        st.warning(str(exc))
        return None


def _influencer_options(items: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("id") or "") for item in items if str(item.get("id") or "").strip()]


def _influencer_label(items: list[dict[str, Any]], value: str) -> str:
    item = next((item for item in items if str(item.get("id") or "") == str(value)), None)
    return str(item.get("name") or value) if item else value


def _asset_label(asset: Mapping[str, Any]) -> str:
    kind = "Imagem" if str(asset.get("asset_type") or "") == "image" else "Documento"
    return f"{kind} · {asset.get('original_name') or 'asset'}"


def _local_asset_path(asset: Mapping[str, Any]) -> Path | None:
    raw = str(asset.get("stored_path") or "").strip()
    path = Path(raw).expanduser() if raw else None
    return path if path and path.is_file() else None


def _image_input(asset: Mapping[str, Any]) -> str:
    """Create a provider-safe URL/data URL for local image-to-video inputs."""
    public_url = str(asset.get("public_url") or "").strip()
    if public_url.startswith(("http://", "https://")):
        return public_url
    path = _local_asset_path(asset)
    if not path:
        return ""
    data = path.read_bytes()
    mime = str(asset.get("mime_type") or "image/jpeg")
    if len(data) > 220 * 1024:
        try:
            from PIL import Image
            image = Image.open(io.BytesIO(data)).convert("RGB")
            for quality in (78, 68, 58, 48):
                buffer = io.BytesIO()
                image.thumbnail((1600, 1600))
                image.save(buffer, format="JPEG", quality=quality, optimize=True)
                if buffer.tell() <= 220 * 1024:
                    data = buffer.getvalue()
                    mime = "image/jpeg"
                    break
        except Exception:
            return ""
    if len(data) > 256 * 1024:
        return ""
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _provider_options(settings: Mapping[str, Any], pool: str) -> tuple[list[dict[str, Any]], list[str]]:
    cards = media_cards_for_pool(settings, pool)
    return cards, [str(card.get("id") or "") for card in cards]


def _provider_label(card: Mapping[str, Any]) -> str:
    definition = media_provider_definition(card.get("provider"))
    model = str(card.get("model") or "modelo não configurado").strip()
    return f"{definition.label} · {model}"


def _ugc_duration_seconds(value: str) -> int:
    """Parse the UGC duration field as minutes:seconds with a safe default."""
    try:
        minutes_text, seconds_text = str(value or "1:20").strip().split(":", 1)
        minutes = max(0, int(minutes_text))
        seconds = int(seconds_text)
        if 0 <= seconds < 60:
            return max(1, min(3600, minutes * 60 + seconds))
    except (TypeError, ValueError):
        pass
    return 80


def _content_metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    raw = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else item.get("metadata_json")
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _ugc_media_records(repository: Any) -> list[dict[str, Any]]:
    try:
        records = repository.list_content("", limit=200)
    except Exception:
        return []
    return [item for item in records if _content_metadata(item).get("workflow") == "ugc_products"]


def render_ai_influencers_api_status(settings: dict[str, Any]) -> None:
    """Show the effective backend status after selector and credentials are loaded."""
    status = backend_status(settings)
    cols = st.columns(3)
    with cols[0]:
        st.metric("Backend activo", status["backend"])
    with cols[1]:
        st.metric("Configurado", "Sim" if status["configured"] else "Não")
    with cols[2]:
        st.metric("Schema", "Verificar" if status["backend"] == "Supabase" else "Automático")
    if status["configured"]:
        st.info(f"{status['message']} Destino: `{status['target']}`")
    else:
        st.warning(status["message"])
    st.markdown("A migração SQL idempotente está disponível em `seed/references/ai_influencers_schema.sql`. No Supabase, aplique-a no SQL Editor e confirme as políticas RLS.")
    if st.button("Testar backend AI Influencers", key="influencers_api_status_test"):
        result = test_backend(settings)
        if result.get("ok"):
            st.success(result.get("message") or "Backend disponível.")
        else:
            st.error(result.get("message") or "O backend não está disponível.")


def render_ai_influencer_characters(
    settings: dict[str, Any],
    *,
    language_options: list[str] | None = None,
    language_formatter: Any = None,
    language_normalizer: Any = None,
) -> None:
    st.title("Personagens")
    language_options = list(language_options or ["pt"])
    language_formatter = language_formatter or (lambda value: value)
    language_normalizer = language_normalizer or (lambda value, default="pt": str(value or default))

    def language_index(value: Any) -> int:
        try:
            normalized = language_normalizer(value, default="pt")
        except TypeError:
            normalized = language_normalizer(value)
        if normalized in language_options:
            return language_options.index(normalized)
        return language_options.index("pt") if "pt" in language_options else 0

    st.caption("Crie personagens virtuais com várias imagens de referência e documentos Markdown/JSON. Os assets ficam associados ao personagem e não são enviados para IA sem uma acção de geração.")
    repository = _repository(settings)
    if repository is None:
        return

    new_character_tab, created_characters_tab = st.tabs(["Novo personagem", "Personagens criados"])

    with new_character_tab:
        with st.form("influencer_create_form", clear_on_submit=True):
            st.subheader("Novo personagem")
            cols = st.columns(3)
            with cols[0]:
                name = st.text_input("Nome do personagem", key="influencer_new_name")
            with cols[1]:
                language = st.selectbox(
                    "Idioma",
                    language_options,
                    index=language_index(st.session_state.get("influencer_new_language", "pt")),
                    format_func=language_formatter,
                    key="influencer_new_language",
                )
            with cols[2]:
                instagram_id = st.text_input("Instagram Business ID (opcional)", key="influencer_new_instagram_id")
            bio = st.text_area("Biografia e instruções", height=130, key="influencer_new_bio")
            files = st.file_uploader(
                "Imagens e documentos de referência",
                type=[item.lstrip(".") for item in sorted({".png", ".jpg", ".jpeg", ".webp", ".gif", ".md", ".json"})],
                accept_multiple_files=True,
                key="influencer_new_assets",
                help="Pode seleccionar várias imagens e ficheiros .md/.json no mesmo upload.",
            )
            create = st.form_submit_button("Guardar personagem", type="primary", width="stretch")
        if create:
            try:
                record = repository.create_influencer({"name": name, "bio": bio, "language": language, "instagram_business_id": instagram_id})
                saved_assets = 0
                for uploaded in files or []:
                    repository.save_asset(record["id"], uploaded.name, uploaded.getvalue())
                    saved_assets += 1
                st.session_state["influencer_selected_id"] = record["id"]
                st.success(f"Personagem guardado com {saved_assets} asset(s) de referência.")
                st.rerun()
            except (ValueError, InfluencerBackendError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("Não foi possível guardar o personagem ou os assets seleccionados.")

    with created_characters_tab:
        try:
            influencers = [item for item in repository.list_influencers() if str(item.get("id") or "") != STANDALONE_CONTENT_INFLUENCER_ID]
        except Exception:
            st.error("Não foi possível consultar os personagens no backend seleccionado.")
            return
        if not influencers:
            st.info("Ainda não existem personagens. Crie o primeiro na subaba Novo personagem.")
            return

        options = _influencer_options(influencers)
        current = str(st.session_state.get("influencer_selected_id") or options[0])
        selected_id = st.selectbox("Personagem seleccionado", options, index=options.index(current) if current in options else 0, format_func=lambda value: _influencer_label(influencers, value), key="influencer_selected_id")
        selected = next(item for item in influencers if str(item.get("id")) == selected_id)

        with st.expander(f"Card do personagem · {selected.get('name') or selected_id}", expanded=False):
            with st.form(f"influencer_edit_form_{selected_id}"):
                edit_name = st.text_input("Nome", value=str(selected.get("name") or ""), key=f"influencer_edit_name_{selected_id}")
                edit_language = st.selectbox(
                    "Idioma",
                    language_options,
                    index=language_index(selected.get("language") or "pt"),
                    format_func=language_formatter,
                    key=f"influencer_edit_language_{selected_id}",
                )
                edit_instagram = st.text_input("Instagram Business ID", value=str(selected.get("instagram_business_id") or ""), key=f"influencer_edit_instagram_{selected_id}")
                edit_bio = st.text_area("Biografia e instruções", value=str(selected.get("bio") or ""), height=130, key=f"influencer_edit_bio_{selected_id}")
                save_edit = st.form_submit_button("Guardar alterações", type="primary")
            if save_edit:
                try:
                    repository.update_influencer(selected_id, {"name": edit_name, "language": edit_language, "instagram_business_id": edit_instagram, "bio": edit_bio})
                    st.success("Perfil do personagem actualizado.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            with st.form(f"influencer_append_assets_form_{selected_id}"):
                more_files = st.file_uploader(
                    "Adicionar imagens/documentos de referência",
                    type=[item.lstrip(".") for item in sorted({".png", ".jpg", ".jpeg", ".webp", ".gif", ".md", ".json"})],
                    accept_multiple_files=True,
                    key=f"influencer_append_assets_{selected_id}",
                )
                append_assets = st.form_submit_button("Adicionar assets ao personagem", width="stretch")
            if append_assets:
                try:
                    saved_assets = 0
                    for uploaded in more_files or []:
                        repository.save_asset(selected_id, uploaded.name, uploaded.getvalue())
                        saved_assets += 1
                    st.success(f"{saved_assets} asset(s) adicionado(s).")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            try:
                assets = repository.list_assets(selected_id)
            except Exception:
                assets = []
            st.subheader(f"Assets de referência · {selected.get('name') or selected_id}")
            if not assets:
                st.info("Este personagem ainda não tem imagens ou documentos de referência.")
            else:
                cols = st.columns(min(4, max(1, len(assets))))
                for index, asset in enumerate(assets):
                    with cols[index % len(cols)]:
                        st.caption(_asset_label(asset))
                        path = _local_asset_path(asset)
                        if str(asset.get("asset_type") or "") == "image" and path:
                            st.image(str(path), width="stretch")
                        elif str(asset.get("asset_type") or "") == "document":
                            raw = str(asset.get("document_json") or "")
                            try:
                                preview = json.loads(raw) if raw else {}
                                st.json(preview, expanded=False)
                            except (TypeError, json.JSONDecodeError):
                                st.code(raw[:1600], language="markdown")
                        st.caption(f"{asset.get('size_bytes', 0)} bytes · {asset.get('mime_type') or 'unknown'}")


def _render_content_history(repository: Any, influencer_id: str = "") -> None:
    try:
        records = repository.list_content(influencer_id, limit=50)
    except Exception:
        records = []
    if not records:
        return
    st.subheader("Conteúdos gerados")
    for item in records:
        content_id = str(item.get("id") or "content")
        content_type = str(item.get("content_type") or "").strip().lower()
        artifact = Path(str(item.get("artifact_path") or ""))
        state = str(item.get("state") or "")
        type_label = "Imagem" if content_type == "image" else "Vídeo" if content_type == "video" else "Conteúdo"
        with st.container(border=True):
            preview_col, detail_col = st.columns([1.25, 2.75])
            with preview_col:
                if artifact.is_file() and content_type == "image":
                    st.image(str(artifact), caption=f"{type_label} gerada", width="stretch")
                elif artifact.is_file() and content_type == "video":
                    st.video(str(artifact))
                else:
                    st.caption("Artefacto indisponível")
            with detail_col:
                st.write(f"**{type_label} · {CONTENT_STATES.get(state, state or '—')}**")
                st.caption(f"Provider: {item.get('provider') or '—'} · {item.get('model') or '—'}")
                st.caption(f"Plataforma: {item.get('platform') or '—'} · Criado: {item.get('created_at') or '—'}")
                if item.get("error"):
                    st.error(str(item.get("error") or "")[:700])
                if artifact.is_file() and state == "completed" and content_type in {"image", "video"}:
                    fallback_mime = "image/png" if content_type == "image" else "video/mp4"
                    mime = mimetypes.guess_type(artifact.name)[0] or fallback_mime
                    st.download_button(
                        f"Descarregar {type_label.casefold()}",
                        data=artifact.read_bytes(),
                        file_name=artifact.name,
                        mime=mime,
                        key=f"influencer_content_download_{content_type}_{content_id}",
                        width="stretch",
                    )


def _store_uploaded_file(uploaded: Any, folder: str) -> Path:
    """Persist an uploaded Streamlit file under storage without trusting its filename."""
    ensure_storage()
    original = Path(str(getattr(uploaded, "name", "upload.bin") or "upload.bin")).name
    safe_name = "".join(char if char.isalnum() or char in ".-_" else "_" for char in original).strip("._") or "upload.bin"
    content = uploaded.getvalue()
    if not content:
        raise MediaGenerationError(f"O ficheiro {safe_name} está vazio.")
    digest = hashlib.sha256(content).hexdigest()[:16]
    destination = STORAGE / "influencer_workflows" / folder / f"{digest}-{safe_name}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_bytes(content)
    return destination


def _workflow_owner(repository: Any) -> str:
    return ensure_standalone_content_owner(repository)


def _workflow_provider_cards(settings: Mapping[str, Any], *, provider: str | None = "kie_ai") -> list[dict[str, Any]]:
    cards = media_cards_for_pool(settings, "video")
    if provider is None:
        return cards
    normalized_provider = str(provider).strip().lower()
    return [card for card in cards if str(card.get("provider") or "").strip().lower() == normalized_provider]


def render_motion_control(settings: dict[str, Any]) -> None:
    """Render Kling 2.6 Motion Control creation only; no social delivery is exposed."""
    st.title("Motion Control")
    st.caption("Crie um vídeo Kling 2.6 a partir de um vídeo de movimento e de uma imagem de referência. O resultado é descarregado para o storage local; não há Telegram, Postiz, Drive ou publicação social.")
    repository = _repository(settings)
    if repository is None:
        return
    cards = _workflow_provider_cards(settings)
    if not cards:
        st.warning("Active e configure pelo menos um cartão KIE AI no pool de vídeo em Configuração API > API Keys > Imagem e Video IA.")
        return
    card_options = [str(card.get("id") or "") for card in cards]
    with st.form("influencer_motion_control_form"):
        video_upload = st.file_uploader("Vídeo original de movimento", type=["mp4", "mov"], key="motion_control_video")
        image_upload = st.file_uploader("Imagem de referência", type=["jpg", "jpeg", "png"], key="motion_control_image")
        prompt = st.text_area("Prompt (opcional)", height=120, max_chars=2500, placeholder="Descreva como preservar a identidade da imagem e aplicar o movimento…", key="motion_control_prompt")
        provider_id = st.selectbox("Provider / modelo", card_options, format_func=lambda value: _provider_label(next(card for card in cards if str(card.get("id")) == value)), key="motion_control_provider")
        generate = st.form_submit_button("Gerar Motion Control", type="primary", width="stretch")
    if generate:
        if video_upload is None or image_upload is None:
            st.error("Seleccione o vídeo original e a imagem de referência.")
            return
        card = next(card for card in cards if str(card.get("id")) == provider_id)
        try:
            video_path = _store_uploaded_file(video_upload, "motion-control-inputs")
            image_path = _store_uploaded_file(image_upload, "motion-control-inputs")
            video_info = validate_motion_control_file(video_path, kind="vídeo")
            image_info = validate_motion_control_file(image_path, kind="imagem")
            owner_id = _workflow_owner(repository)
            record = repository.create_content(
                {
                    "influencer_id": owner_id,
                    "content_type": "video",
                    "prompt": prompt,
                    "caption": "",
                    "provider": card.get("provider"),
                    "model": "kling-2.6/motion-control",
                    "platform": "",
                    "state": "running",
                    "metadata": {
                        "workflow": "motion_control",
                        "input_video_path": str(video_path),
                        "reference_image_path": str(image_path),
                        "input_video_duration_seconds": video_info.get("duration_seconds"),
                        "input_video_size_bytes": video_info.get("size_bytes"),
                        "reference_image_size_bytes": image_info.get("size_bytes"),
                    },
                }
            )
            with st.spinner("A enviar os inputs para KIE e a aguardar o Kling Motion Control…"):
                try:
                    image_url = upload_kie_file(image_path, card, upload_path="thunderbolt/motion-control")
                    video_url = upload_kie_file(video_path, card, upload_path="thunderbolt/motion-control")
                    output, task_id = generate_motion_control_video(settings, card, image_url=image_url, video_url=video_url, prompt=prompt)
                    metadata = {"workflow": "motion_control", "input_video_path": str(video_path), "reference_image_path": str(image_path), "kie_input_urls_temporary": True}
                    repository.update_content(record["id"], {"state": "completed", "artifact_path": str(output), "provider_request_id": task_id, "metadata": metadata})
                    record_notification("influencer_content_completed", "Motion Control concluído", "O vídeo Motion Control foi gerado e guardado localmente.", metadata={"content_id": record["id"], "workflow": "motion_control", "provider": card.get("provider")}, dedupe_key=f"influencer-workflow:{record['id']}:completed")
                    st.success("Motion Control concluído. O vídeo está disponível no histórico local abaixo.")
                except Exception as exc:
                    repository.update_content(record["id"], {"state": "failed", "error": str(exc)[:1000]})
                    record_notification("influencer_content_failed", "Motion Control falhou", f"A criação Motion Control falhou: {str(exc)[:240]}", metadata={"content_id": record["id"], "workflow": "motion_control", "provider": card.get("provider")}, dedupe_key=f"influencer-workflow:{record['id']}:failed")
                    st.error(f"Não foi possível gerar o Motion Control: {exc}")
        except (MediaGenerationError, ValueError, OSError) as exc:
            st.error(str(exc))
    _render_content_history(repository, STANDALONE_CONTENT_INFLUENCER_ID)


def render_ugc_products(settings: dict[str, Any]) -> None:
    """Create portrait UGC photos or videos from a product and a saved character."""
    st.title("UGC Products")
    st.caption("Crie fotos ou vídeos UGC em formato vertical 9:16 para TikTok e Instagram usando um produto e um personagem cadastrado.")
    repository = _repository(settings)
    if repository is None:
        return
    media_tab, ready_tab = st.tabs(["Criar UGC", "Midias Prontas"])
    try:
        influencers = [item for item in repository.list_influencers() if str(item.get("id") or "") != STANDALONE_CONTENT_INFLUENCER_ID]
    except Exception:
        influencers = []

    with media_tab:
        if not influencers:
            influencers = [{"id": "", "name": "", "bio": ""}]
        influencer_options = _influencer_options(influencers)
        if not influencer_options:
            influencer_options = [""]
        selected_influencer = st.selectbox(
            "Personagem",
            influencer_options,
            format_func=lambda value: _influencer_label(influencers, value),
            key="ugc_products_character",
        )
        selected_character = next(
            (item for item in influencers if str(item.get("id") or "") == str(selected_influencer or "")),
            influencers[0],
        )
        selected_influencer = str(selected_character.get("id") or "")
        try:
            character_assets = repository.list_assets(selected_influencer)
        except Exception:
            character_assets = []
        character_images = [item for item in character_assets if str(item.get("asset_type") or "") == "image"]
        product_name = st.text_input("Nome do produto", key="ugc_products_name", placeholder="Ex.: Sérum facial hidratante")
        product_info = st.text_area("Informação do Produto ou link do produto", key="ugc_products_info", height=110, placeholder="Descreva benefícios, características, oferta ou cole o link do produto…")
        product_uploads = st.file_uploader(
            "Imagem do produto (fotos/vídeos)",
            type=["jpg", "jpeg", "png", "webp", "mp4", "mov", "webm"],
            accept_multiple_files=True,
            key="ugc_products_inputs",
            help="Anexe uma ou mais referências do produto. Para geração, a primeira imagem será usada como referência visual principal.",
        )
        generation_col, duration_col = st.columns([2, 1])
        with generation_col:
            generation_mode = st.selectbox("Tipo de geração", ["Gerar Foto", "Gerar Video"], key="ugc_products_generation_mode")
        duration_text = "1:20"
        if generation_mode == "Gerar Video":
            with duration_col:
                duration_text = st.text_input("Duração de cada clip (MM:SS)", value="1:20", max_chars=5, key="ugc_products_duration_text", width=120)
        duration = _ugc_duration_seconds(duration_text)
        image_cards, image_options = _provider_options(settings, "image")
        video_cards = _workflow_provider_cards(settings, provider=None)
        video_options = [str(card.get("id") or "") for card in video_cards]
        image_provider_id = ""
        video_provider_id = ""
        if generation_mode == "Gerar Foto":
            image_provider_id = st.selectbox("Provider / modelo de imagem", image_options, format_func=lambda value: _provider_label(next(card for card in image_cards if str(card.get("id")) == value)), key="ugc_products_image_provider") if image_cards else ""
        else:
            video_provider_id = st.selectbox("Provider / modelo de vídeo", video_options, format_func=lambda value: _provider_label(next(card for card in video_cards if str(card.get("id")) == value)), key="ugc_products_video_provider") if video_cards else ""
        script = st.text_area("Roteiro de vídeo (UGC)", height=150, key="ugc_products_script", placeholder="O roteiro gerado pela IA aparecerá aqui; também pode editá-lo antes de gerar.")
        generate_script = st.button("Gerar roteiro com IA", width="stretch", key="ugc_products_generate_script")
        generate = st.button("Gerar Mídia (Foto/Vídeo)", type="primary", width="stretch", key="ugc_products_generate")
        if generate_script:
            context = "\n".join(
                item for item in [
                    f"Produto: {product_name.strip()}" if product_name.strip() else "",
                    f"Informação/link: {product_info.strip()}" if product_info.strip() else "",
                    f"Personagem: {selected_character.get('name') or selected_influencer}",
                    f"Biografia do personagem: {selected_character.get('bio') or ''}",
                ] if item
            )
            prompts = generate_ugc_segment_prompts(settings, context or "Criar uma demonstração UGC natural do produto.")
            st.session_state["ugc_products_script"] = "\n---\n".join(prompts)
            st.rerun()
        if generate:
            if not product_name.strip():
                st.error("Informe o nome do produto.")
            elif not product_info.strip() and not product_uploads:
                st.error("Informe os dados/link do produto ou anexe pelo menos uma mídia.")
            elif not script.strip():
                st.error("Escreva o roteiro ou use o botão Gerar roteiro com IA.")
            elif generation_mode == "Gerar Foto" and not image_provider_id:
                st.error("Active um provider de imagem antes de gerar a foto.")
            elif generation_mode == "Gerar Video" and not video_provider_id:
                st.error("Active um provider de vídeo antes de gerar o vídeo.")
            else:
                image_upload = next((item for item in product_uploads or [] if Path(str(getattr(item, "name", ""))).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}), None)
                if image_upload is None:
                    st.error("Anexe pelo menos uma imagem do produto para usar como referência visual.")
                else:
                    try:
                        product_path = _store_uploaded_file(image_upload, "ugc-products-inputs")
                        character_path = _local_asset_path(character_images[0]) if character_images else None
                        prompts = [part.strip() for part in script.split("\n---\n") if part.strip()]
                        if len(prompts) != 2:
                            prompts = generate_ugc_segment_prompts(settings, script)
                        card = next((item for item in (image_cards if generation_mode == "Gerar Foto" else video_cards) if str(item.get("id")) == (image_provider_id if generation_mode == "Gerar Foto" else video_provider_id)), None)
                        character_name = str(selected_character.get("name") or selected_influencer)
                        enriched_prompts = [f"Personagem: {character_name}. Produto: {product_name.strip()}. Informação: {product_info.strip()}. {item} Formato vertical 9:16, enquadramento para telemóvel, TikTok e Instagram." for item in prompts]
                        owner_id = selected_influencer or _workflow_owner(repository)
                        ugc_metadata = {"workflow": "ugc_products", "product_name": product_name.strip(), "product_info": product_info.strip(), "character_name": character_name, "character_asset_path": str(character_path or ""), "product_image_path": str(product_path), "generation_mode": generation_mode, "duration_seconds": int(duration), "aspect_ratio": "9:16", "segment_prompts": enriched_prompts, "telegram": False, "social_publish": False, "provider_card_id": str((card or {}).get("id") or "")}
                        if generation_mode == "Gerar Foto":
                            # 1.0.11: fotos UGC vão para a FILA DE IMAGENS de
                            # produção — a UI responde instantâneo e o
                            # image_worker gera em background (backoff em 429).
                            repository.create_content({
                                "influencer_id": owner_id,
                                "content_type": "image",
                                "prompt": script,
                                "caption": f"{product_name.strip()} + {character_name}",
                                "provider": card.get("provider") if card else "",
                                "model": str(card.get("model") or "") if card else "",
                                "platform": "TikTok, Instagram",
                                "state": "image_queued",
                                "metadata": ugc_metadata,
                            })
                            st.success("Foto UGC na fila de produção do Motor — a geração corre em background; consulte Midias Prontas.")
                        else:
                            record = repository.create_content({
                                "influencer_id": owner_id,
                                "content_type": "video",
                                "prompt": script,
                                "caption": f"{product_name.strip()} + {character_name}",
                                "provider": card.get("provider") if card else "",
                                "model": str(card.get("model") or "") if card else "",
                                "platform": "TikTok, Instagram",
                                "state": "running",
                                "metadata": ugc_metadata,
                            })
                            with st.spinner("A gerar a mídia UGC em formato vertical 9:16…"):
                                output = generate_ugc_product_video(settings, card, image_url=_image_input({"stored_path": str(product_path), "mime_type": mimetypes.guess_type(product_path.name)[0] or "image/jpeg"}), prompts=enriched_prompts, duration=int(duration))[0]
                                task_ids = []
                            repository.update_content(record["id"], {"state": "completed", "artifact_path": str(output), "provider_request_id": ",".join(task_ids)})
                            st.success("Mídia UGC criada e guardada em Midias Prontas.")
                    except Exception as exc:
                        record_id = None
                        try:
                            record_id = record["id"]
                        except NameError:
                            record_id = None
                        if record_id:
                            repository.update_content(record_id, {"state": "failed", "error": str(exc)[:1000]})
                        st.error(f"Não foi possível gerar a mídia UGC: {exc}")
        if not image_cards and not video_cards:
            st.warning("Configure pelo menos um provider de imagem ou vídeo em Configuração API > API Keys > Imagem e Video IA.")

    with ready_tab:
        st.subheader("Midias Prontas")
        records = _ugc_media_records(repository)
        if not records:
            st.info("Ainda não existem mídias UGC prontas.")
        for item in records:
            metadata = _content_metadata(item)
            artifact = Path(str(item.get("artifact_path") or ""))
            content_id = str(item.get("id") or "content")
            title = str(item.get("caption") or f"{metadata.get('product_name') or 'Produto'} + {metadata.get('character_name') or 'Personagem'}")
            with st.container(border=True):
                preview_col, detail_col, edit_col, download_col = st.columns([1.2, 2.7, 0.35, 0.9])
                with preview_col:
                    if artifact.is_file() and str(item.get("content_type") or "") == "image":
                        st.image(str(artifact), width="stretch")
                    elif artifact.is_file():
                        st.video(str(artifact))
                    else:
                        st.caption("Artefacto indisponível")
                with detail_col:
                    st.write(f"**{title}**")
                    st.caption(f"{metadata.get('product_name') or 'Produto'} · {metadata.get('character_name') or 'Personagem'} · {metadata.get('generation_mode') or 'UGC'} · 9:16")
                    st.caption(f"Criado: {item.get('created_at') or '—'}")
                with edit_col:
                    if st.button("", icon=":material/edit:", help="Renomear mídia", key=f"ugc_ready_rename_{content_id}"):
                        st.session_state[f"ugc_ready_editing_{content_id}"] = True
                with download_col:
                    if artifact.is_file() and str(item.get("state") or "") == "completed":
                        mime = mimetypes.guess_type(artifact.name)[0] or ("image/png" if str(item.get("content_type") or "") == "image" else "video/mp4")
                        st.download_button("Download", data=artifact.read_bytes(), file_name=artifact.name, mime=mime, key=f"ugc_ready_download_{content_id}", width="stretch")
                if st.session_state.get(f"ugc_ready_editing_{content_id}"):
                    with st.form(f"ugc_ready_rename_form_{content_id}"):
                        renamed = st.text_input("Nome da mídia", value=title, key=f"ugc_ready_name_{content_id}")
                        if st.form_submit_button("Guardar nome"):
                            repository.update_content(content_id, {"caption": renamed.strip() or title})
                            st.session_state.pop(f"ugc_ready_editing_{content_id}", None)
                            st.rerun()

def render_ai_influencer_content(settings: dict[str, Any]) -> None:
    st.title("Geração de Conteúdo IA")
    st.caption("Gere conteúdos para redes sociais a partir de um personagem e dos seus assets. A publicação permanece separada e exige uma acção explícita.")
    repository = _repository(settings)
    if repository is None:
        return
    try:
        influencers = [item for item in repository.list_influencers() if str(item.get("id") or "") != STANDALONE_CONTENT_INFLUENCER_ID]
    except Exception:
        st.error("Não foi possível consultar os personagens.")
        return
    images_tab, videos_tab = st.tabs(["Imagens", "Vídeos"])

    with images_tab:
        st.subheader("Gerar imagem para redes sociais")
        if not influencers:
            st.info("Crie um personagem em AI Influencers > Personagens antes de gerar conteúdo.")
        else:
            options = _influencer_options(influencers)
            current = str(st.session_state.get("influencer_selected_id") or options[0])
            cards, provider_options = _provider_options(settings, "image")
            if not cards:
                st.warning("Não existem providers activos no pool de imagem. Configure um provider em Configuração API > API Keys > Imagem e Video IA.")
            with st.form("influencer_image_content_form"):
                influencer_id = st.selectbox("Personagem", options, index=options.index(current) if current in options else 0, format_func=lambda value: _influencer_label(influencers, value), key="content_image_influencer")
                assets = repository.list_assets(influencer_id)
                image_assets = [item for item in assets if str(item.get("asset_type") or "") == "image"]
                asset_options = [""] + [str(item.get("id") or "") for item in image_assets]
                reference_id = st.selectbox("Imagem de referência (opcional)", asset_options, format_func=lambda value: "Sem imagem base" if not value else next((_asset_label(item) for item in image_assets if str(item.get("id")) == value), value), key="content_image_reference")
                prompt = st.text_area("Prompt da imagem", height=130, placeholder="Descreva a cena, pose, ambiente e estilo do personagem…", key="content_image_prompt")
                caption = st.text_area("Legenda/caption (opcional)", height=90, key="content_image_caption")
                platforms = st.multiselect("Redes sociais de destino", PLATFORM_OPTIONS, default=["Instagram"], key="content_image_platforms")
                provider_id = st.selectbox("Provider / modelo", provider_options, format_func=lambda value: _provider_label(next(card for card in cards if str(card.get("id")) == value)), key="content_image_provider") if cards else ""
                generate = st.form_submit_button("Gerar imagem", type="primary", width="stretch")
            if generate:
                if not prompt.strip():
                    st.error("Informe o prompt da imagem.")
                elif not platforms:
                    st.error("Seleccione pelo menos uma rede social de destino.")
                elif not provider_id:
                    st.error("Configure e active um provider de imagem antes de gerar.")
                else:
                    card = next(card for card in cards if str(card.get("id")) == provider_id)
                    reference = next((item for item in image_assets if str(item.get("id")) == reference_id), None)
                    reference_path = _local_asset_path(reference) if reference else None
                    # 1.0.11: fila de imagens de produção — a UI marca e responde
                    # instantâneo; o image_worker gera em background (mesmo pool
                    # de imagem), com backoff em Rate Limit 429.
                    record = repository.create_content({
                        "influencer_id": influencer_id,
                        "content_type": "image",
                        "prompt": prompt,
                        "caption": caption,
                        "provider": card.get("provider"),
                        "model": card.get("model"),
                        "platform": ", ".join(platforms),
                        "state": "image_queued",
                        "metadata": {
                            "reference_asset_id": reference_id,
                            "provider_card_id": str(card.get("id") or ""),
                            "reference_path": str(reference_path or ""),
                            "queued_by": "motor_image_queue",
                        },
                    })
                    record_notification(
                        "influencer_content_queued",
                        "Imagem na fila de produção",
                        f"A imagem de {_influencer_label(influencers, influencer_id)} entrou na fila do Motor e será gerada em background.",
                        metadata={"content_id": record["id"], "content_type": "image", "provider": card.get("provider")},
                        dedupe_key=f"influencer-content:{record['id']}:queued",
                    )
                    st.success("Imagem na fila de produção do Motor — a geração corre em background; consulte o histórico abaixo.")
                    _render_content_history(repository, influencer_id)
            else:
                selected_id = str(st.session_state.get("content_image_influencer") or options[0])
                _render_content_history(repository, selected_id)

    with videos_tab:
        st.subheader("Gerar vídeo para redes sociais")
        if not influencers:
            st.info("Crie um personagem em AI Influencers > Personagens antes de gerar conteúdo.")
        else:
            options = _influencer_options(influencers)
            current = str(st.session_state.get("influencer_selected_id") or options[0])
            cards, provider_options = _provider_options(settings, "video")
            if not cards:
                st.warning("Não existem providers activos no pool de vídeo. Configure KIE AI, Replicate, FAL AI ou outro provider compatível em Configuração API > API Keys > Imagem e Video IA.")
            with st.form("influencer_video_content_form"):
                influencer_id = st.selectbox("Personagem", options, index=options.index(current) if current in options else 0, format_func=lambda value: _influencer_label(influencers, value), key="content_video_influencer")
                assets = repository.list_assets(influencer_id)
                image_assets = [item for item in assets if str(item.get("asset_type") or "") == "image"]
                asset_options = [str(item.get("id") or "") for item in image_assets]
                reference_id = st.selectbox("Imagem inicial", asset_options, format_func=lambda value: next((_asset_label(item) for item in image_assets if str(item.get("id")) == value), value), key="content_video_reference") if image_assets else ""
                prompt = st.text_area("Prompt de movimento", height=130, placeholder="Descreva movimento de câmara, expressão, gesto e ambiente…", key="content_video_prompt")
                caption = st.text_area("Legenda/caption (opcional)", height=90, key="content_video_caption")
                platforms = st.multiselect("Redes sociais de destino", PLATFORM_OPTIONS, default=["Instagram", "TikTok"], key="content_video_platforms")
                provider_id = st.selectbox("Provider / modelo de vídeo", provider_options, format_func=lambda value: _provider_label(next(card for card in cards if str(card.get("id")) == value)), key="content_video_provider") if cards else ""
                generate = st.form_submit_button("Gerar vídeo", type="primary", width="stretch")
            if generate:
                if not prompt.strip():
                    st.error("Informe o prompt de movimento.")
                elif not reference_id:
                    st.error("Seleccione uma imagem inicial para a conversão image-to-video.")
                elif not platforms:
                    st.error("Seleccione pelo menos uma rede social de destino.")
                elif not provider_id:
                    st.error("Configure e active um provider de vídeo antes de gerar.")
                else:
                    card = next(card for card in cards if str(card.get("id")) == provider_id)
                    reference = next((item for item in image_assets if str(item.get("id")) == reference_id), None)
                    image_url = _image_input(reference or {})
                    if not image_url:
                        st.error("A imagem inicial local deve ter até 256 KB ou ter um URL público no backend para ser enviada ao provider de vídeo.")
                    else:
                        record = repository.create_content({"influencer_id": influencer_id, "content_type": "video", "prompt": prompt, "caption": caption, "provider": card.get("provider"), "model": card.get("model"), "platform": ", ".join(platforms), "state": "running", "metadata": {"reference_asset_id": reference_id}})
                        with st.spinner("A gerar e descarregar o vídeo…"):
                            try:
                                output = generate_video_for_card(settings, card, prompt, image_url=image_url)
                                repository.update_content(record["id"], {"state": "completed", "artifact_path": str(output)})
                                record_notification("influencer_content_completed", "Conteúdo de Influencer concluído", f"O vídeo de {_influencer_label(influencers, influencer_id)} foi gerado e guardado.", metadata={"content_id": record["id"], "content_type": "video", "provider": card.get("provider")}, dedupe_key=f"influencer-content:{record['id']}:completed")
                                st.success(f"Vídeo gerado por {media_provider_definition(card.get('provider')).label}.")
                            except Exception as exc:
                                repository.update_content(record["id"], {"state": "failed", "error": str(exc)[:1000]})
                                record_notification("influencer_content_failed", "Conteúdo de Influencer falhou", f"O vídeo de {_influencer_label(influencers, influencer_id)} falhou. Consulte o histórico para ver o erro.", metadata={"content_id": record["id"], "content_type": "video", "provider": card.get("provider")}, dedupe_key=f"influencer-content:{record['id']}:failed")
                                st.error(f"Não foi possível gerar o vídeo: {exc}")
                        _render_content_history(repository, influencer_id)
            else:
                selected_id = str(st.session_state.get("content_video_influencer") or options[0])
                _render_content_history(repository, selected_id)


__all__ = [
    "render_ai_influencer_characters",
    "render_ai_influencer_content",
    "render_motion_control",
    "render_ugc_products",
    "render_ai_influencers_api_status",
]
