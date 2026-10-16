"""Build-time asset prefetch for the pinned batch worker; no inference or media input."""

# Match the headless-run defaults at the Dockerfile's pinned FaceFusion commit.
# face_swapper.pre_check() also checks its seven get_common_modules(), including
# voice_extractor even when the input has no audio. Do not use force-download:
# that command enumerates unrelated processors and their model sets.
MODEL_STATE = {
    "face_swapper_model": "ghost_1_256",
    "face_detector_model": "yolo_face",
    "face_landmarker_model": "2dfan4",
    "face_occluder_model": "xseg_1",
    "face_parser_model": "bisenet_resnet_34",
    "voice_extractor_model": "kim_vocal_2",
}


def prefetch_models() -> None:
    # Imports stay here so local tests need neither FaceFusion nor GPU packages.
    from facefusion import choices, state_manager
    from facefusion.download import validate_hash_paths, validate_source_paths
    from facefusion.processors.core import load_processor_module

    for key, value in MODEL_STATE.items():
        state_manager.init_item(key, value)
    state_manager.init_item("processors", ["face_swapper"])
    state_manager.init_item("download_providers", list(choices.download_providers))
    state_manager.init_item("log_level", "error")

    processor = load_processor_module("face_swapper")
    if not processor.pre_check():
        raise RuntimeError("Required model prefetch failed.")

    # Revalidate the selected assets after prefetch. The pinned common modules
    # expose either collect_model_downloads() or get_model_options(); the latter
    # returns only the configured model, not the entire static catalogue.
    for module in [*processor.get_common_modules(), processor]:
        if hasattr(module, "collect_model_downloads"):
            hashes, sources = module.collect_model_downloads()
        else:
            options = module.get_model_options()
            hashes, sources = options["hashes"], options["sources"]
        if not hashes or not sources:
            raise RuntimeError("Required model assets are unavailable.")
        hash_paths = [asset["path"] for asset in hashes.values()]
        source_paths = [asset["path"] for asset in sources.values()]
        valid_hashes, invalid_hashes = validate_hash_paths(hash_paths)
        valid_sources, invalid_sources = validate_source_paths(source_paths)
        if (
            invalid_hashes
            or invalid_sources
            or len(valid_hashes) != len(hash_paths)
            or len(valid_sources) != len(source_paths)
        ):
            raise RuntimeError("Required model assets are unavailable.")


def main() -> None:
    try:
        prefetch_models()
    except Exception:
        raise SystemExit("Required FaceFusion model prefetch failed.") from None


if __name__ == "__main__":
    main()
