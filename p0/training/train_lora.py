"""Offline, decoder-only LoRA experiment; never promotes a model into NoteVive.

Heavy libraries are imported only when a verified local experiment is launched.
The default eight updates are a mechanics check, not a sufficient adaptation.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import shutil
import sys
import tempfile
import time

from p0.bench.scoring import edit_distance, words
from p0.training.drug_objective import training_drug_positions
from p0.training.prepare_px import RATE, PX_SHA256, read_pcm, safe_artifact, sha256, verify_export
from p0.training.shadow_optimizer import cpu_shadow_adamw


REPO = Path(__file__).resolve().parents[2]
SOT, EOS, FRENCH, TRANSCRIBE, NO_TIMESTAMPS = 50258, 50257, 50265, 50360, 50364
PREFIX = [SOT, FRENCH, TRANSCRIBE, NO_TIMESTAMPS]
TARGET_RE = r"model\.decoder\.layers\.[0-3]\.(self_attn|encoder_attn)\.(q_proj|v_proj)"
TARGETS = sorted(f"model.decoder.layers.{layer}.{attention}.{projection}"
                 for layer in range(4) for attention in ("self_attn", "encoder_attn")
                 for projection in ("q_proj", "v_proj"))
LORA_PARAMETERS = 327680
SELECTION_KEY = "notevive-px-lora-validation-v1"
REQUIRED_VERSIONS = {"torch": "2.9.1", "transformers": "4.57.3", "peft": "0.18.0",
                     "numpy": "2.2.6", "safetensors": "0.6.2"}
GENERATION = {"language": "fr", "task": "transcribe", "return_timestamps": False,
              "do_sample": False, "num_beams": 1, "max_new_tokens": 444, "use_cache": True}


def json_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def atomic_json(path: Path, value) -> None:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".json-",
                                     dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def private_directory(path: Path) -> Path:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("Un répertoire privé ne doit pas être un lien")
    result = path.expanduser().resolve(strict=True)
    if not result.is_dir() or result.is_relative_to(REPO):
        raise ValueError("Choisir un répertoire local hors du dépôt")
    return result


def output_path(path: Path, inputs: list[Path], minimum_free: int) -> Path:
    if path.is_symlink() or path.exists():
        raise ValueError("La sortie doit être un nouveau répertoire ; aucune reprise implicite")
    result = path.expanduser().resolve()
    if result.is_relative_to(REPO):
        raise ValueError("La sortie privée doit rester hors du dépôt Git")
    if not result.parent.is_dir():
        raise ValueError("Créer le répertoire parent local avant le lancement")
    if any(result.is_relative_to(source) or source.is_relative_to(result) for source in inputs):
        raise ValueError("Séparer la sortie, le corpus, les poids et les adaptateurs")
    if shutil.disk_usage(result.parent).free < minimum_free:
        raise ValueError("Espace libre insuffisant avant lancement ; aucun résultat créé")
    return result


def label_ids(input_ids: list[int], attention_mask: list[int], maximum: int = 448) -> list[int]:
    """Strip only SOT; retain EOS even though Whisper uses EOS as its pad id."""
    if len(input_ids) != len(attention_mask) or not input_ids:
        raise ValueError("Texte et masque désalignés")
    if any(value not in (0, 1) for value in attention_mask):
        raise ValueError("Masque texte invalide")
    if any(type(token) is not int or not 0 <= token < 51866 for token in input_ids):
        raise ValueError("Identifiant de jeton invalide")
    real = sum(attention_mask)
    if attention_mask != [1] * real + [0] * (len(input_ids) - real):
        raise ValueError("Seul le remplissage à droite est accepté")
    if input_ids[:4] != PREFIX or real < 6 or input_ids[real - 1] != EOS:
        raise ValueError("Préfixe français/transcription ou fin de texte incorrect")
    if len(input_ids) - 1 > maximum:
        raise ValueError("Référence trop longue : aucune troncature du texte n’est permise")
    result = [token if present else -100 for token, present in zip(input_ids[1:], attention_mask[1:])]
    if (any(token == SOT for token in result)
            or any(token in PREFIX[1:] + [EOS] for token in result[3:real - 2])):
        raise ValueError("Jeton de commande inattendu dans la référence")
    return result


def shift_labels(labels: list[int]) -> list[int]:
    if not labels:
        raise ValueError("Cible vide")
    return [SOT] + [EOS if value == -100 else value for value in labels[:-1]]


def validate_architecture(config: dict) -> None:
    expected = {"d_model": 1280, "encoder_layers": 32, "decoder_layers": 4,
                "num_mel_bins": 128, "max_target_positions": 448,
                "max_source_positions": 1500, "vocab_size": 51866,
                "decoder_start_token_id": SOT, "eos_token_id": EOS, "pad_token_id": EOS}
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError("Architecture différente du Whisper Turbo verrouillé")


def verify_partition_contract(partitions: dict[str, list[dict]]) -> None:
    """Secondary guard after archive verification, also used by unit fixtures."""
    seen = {name: set() for name in ("id", "speaker_id", "pcm_sha256", "text")}
    for name in ("train", "validation"):
        rows = partitions[name]
        if not rows or any(row.get("partition") != name for row in rows):
            raise ValueError("Partition vide ou étiquette de partition incorrecte")
        current = {key: {row[key] for row in rows} for key in seen}
        if len(current["id"]) != len(rows) or len(current["pcm_sha256"]) != len(rows):
            raise ValueError("Identifiants ou audio dupliqués")
        if any(seen[key] & current[key] for key in seen):
            raise ValueError("Fuite entre les partitions")
        for key in seen:
            seen[key].update(current[key])


def validation_selection(rows: list[dict], count: int) -> list[dict]:
    """Round robin over voices, ordered only by immutable ids, never by text."""
    if not rows or len({row["id"] for row in rows}) != len(rows) or count < 0:
        raise ValueError("Sélection de validation invalide")
    if count == 0:
        count = len(rows)
    if count > len(rows):
        raise ValueError("La sélection dépasse la validation disponible")
    def rank(value):
        return hashlib.sha256((SELECTION_KEY + "\0" + value).encode()).digest()
    groups = {}
    for row in rows:
        if row.get("partition") != "validation":
            raise ValueError("La génération doit utiliser exclusivement la validation")
        groups.setdefault(row["speaker_id"], []).append(row)
    for items in groups.values():
        items.sort(key=lambda row: rank(row["id"]))
    selected, speakers, position = [], sorted(groups, key=rank), 0
    while len(selected) < count:
        for speaker in speakers:
            if position < len(groups[speaker]) and len(selected) < count:
                selected.append(groups[speaker][position])
        position += 1
    return selected


def validation_window(rows: list[dict], count: int, offset: int = 0) -> list[dict]:
    """Slice the same voice-balanced ranking without changing historical selection."""
    if type(offset) is not int or not 0 <= offset < len(rows) or type(count) is not int or count < 0:
        raise ValueError("Fenêtre de validation invalide")
    end = offset + count if count else 0
    return validation_selection(rows, end)[offset:]


def accumulation_groups(rows: list, size: int):
    if size < 1:
        raise ValueError("Accumulation positive requise")
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def learning_rate(update: int, total: int, peak: float) -> float:
    if not 1 <= update <= total:
        raise ValueError("Étape de planification invalide")
    warmup = max(1, math.ceil(total * 0.1))
    if update <= warmup:
        return peak * update / warmup
    # Keep a positive final learning rate; decay is applied before each update.
    return peak * (total - update + 1) / max(1, total - warmup)


def prepare(args):
    corpus, source = private_directory(args.corpus), private_directory(args.model)
    inputs = [corpus, source]
    adapter = private_directory(args.adapter) if getattr(args, "adapter", None) else None
    if adapter:
        inputs.append(adapter)
    minimum_free = int(args.min_free_gib * 1024 ** 3)
    output = output_path(args.output, inputs, minimum_free)
    print("Vérification de l’archive, du corpus et des poids locaux…", flush=True)
    summary = verify_export(corpus, args.px_archive)
    from p0.training.fetch_model import verify_model
    provenance = verify_model(source)
    partitions = {name: [json.loads(line) for line in safe_artifact(corpus, f"{name}.jsonl")
                        .read_text(encoding="utf-8").splitlines()]
                  for name in ("train", "validation")}
    verify_partition_contract(partitions)
    manifest_hashes = {name: sha256(corpus / f"{name}.jsonl") for name in partitions}
    output_path(output, inputs, minimum_free)  # Recheck after source verification.
    return corpus, source, adapter, output, summary, provenance, partitions, manifest_hashes


def load_runtime(device: str):
    # No downloads, remote code, hub telemetry or CPU fallback during a run.
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                       "HF_DATASETS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
    if device == "mps" and os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK", "0") != "0":
        raise ValueError("Désactiver le repli CPU MPS pour mesurer un essai explicite")
    versions = {name: importlib.metadata.version(name) for name in REQUIRED_VERSIONS}
    if any(versions[name].split("+")[0] != wanted for name, wanted in REQUIRED_VERSIONS.items()):
        raise ValueError(f"Versions différentes du protocole verrouillé : {versions}")
    import numpy as np
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor
    from peft import LoraConfig, PeftModel, get_peft_model, get_peft_model_state_dict
    if device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS indisponible ; aucun repli CPU implicite")
    return {"torch": torch, "np": np, "Whisper": WhisperForConditionalGeneration,
            "Processor": WhisperProcessor, "LoraConfig": LoraConfig, "PeftModel": PeftModel,
            "get_peft_model": get_peft_model, "state": get_peft_model_state_dict, "versions": versions}


def model_setup(rt, source: Path, device: str, dtype_name: str, train: bool, adapter=None):
    torch = rt["torch"]
    dtype = getattr(torch, dtype_name)
    if device == "cpu" and dtype_name != "float32":
        raise ValueError("Le repli CPU explicite exige float32")
    processor = rt["Processor"].from_pretrained(str(source), local_files_only=True,
                                               language="fr", task="transcribe")
    processor.tokenizer.set_prefix_tokens(language="fr", task="transcribe", predict_timestamps=False)
    if processor.tokenizer.prefix_tokens != PREFIX:
        raise ValueError("Préfixe tokenizer inattendu")
    base = rt["Whisper"].from_pretrained(str(source), local_files_only=True, use_safetensors=True,
                                       torch_dtype=dtype, attn_implementation="sdpa").to(device)
    validate_architecture(base.config.to_dict())
    base.config.use_cache = False
    # Do not set config.max_length: the whisper.cpp converter reads it as context size.
    base.generation_config.forced_decoder_ids = None
    base.generation_config.language, base.generation_config.task = "fr", "transcribe"
    for parameter in base.parameters():
        parameter.requires_grad_(False)
    if train:
        matched = sorted(name for name, module in base.named_modules() if re.fullmatch(TARGET_RE, name))
        if matched != TARGETS:
            raise ValueError("Les 16 projections attendues ne sont pas présentes")
        config = rt["LoraConfig"](r=8, lora_alpha=16, lora_dropout=0.05, bias="none",
                                  target_modules=TARGET_RE, task_type=None, inference_mode=False,
                                  init_lora_weights=True)
        model = rt["get_peft_model"](base, config, autocast_adapter_dtype=True)
        parameters = [(name, value) for name, value in model.named_parameters() if value.requires_grad]
        if (sum(value.numel() for name, value in parameters) != LORA_PARAMETERS
                or len(parameters) != 32 or any("lora_" not in name or value.dtype != torch.float32
                                               for name, value in parameters)):
            raise ValueError("Seuls les 327 680 paramètres LoRA FP32 doivent être entraînables")
        if any(bool(torch.count_nonzero(value).item()) for name, value in parameters if ".lora_B." in name):
            raise ValueError("L’adaptateur neuf doit avoir un effet initial nul")
    elif adapter:
        model = load_existing_adapter(rt, base, adapter)
    else:
        model = base
    model.to(device)  # Preserve FP32 adapters: never call .half() after their creation.
    model.eval()
    return model, base, processor


def load_existing_adapter(rt, base, adapter: Path):
    """Allocate FP32 LoRA before copying weights, including on an FP16 base."""
    from safetensors.torch import load_file
    config = rt["LoraConfig"].from_pretrained(str(adapter), local_files_only=True)
    model = rt["get_peft_model"](base, config, autocast_adapter_dtype=True)
    for name, parameter in model.named_parameters():
        if "lora_" in name:
            parameter.data = parameter.data.to(dtype=rt["torch"].float32)
    model.load_adapter(str(adapter), adapter_name="default", is_trainable=False,
                       local_files_only=True, autocast_adapter_dtype=True,
                       torch_device="cpu")  # safetensors 0.6.2 rejects the spelling mps:0.
    expected = load_file(str(adapter / "adapter_model.safetensors"), device="cpu")
    actual = rt["state"](model)
    if expected.keys() != actual.keys() or any(
            actual[name].dtype != rt["torch"].float32 or not rt["torch"].equal(value, actual[name].detach().cpu())
            for name, value in expected.items()):
        raise ValueError("Le chargement de l’adaptateur a changé ses valeurs FP32")
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model


def tensor_digest(model, adapter: bool) -> str:
    result = hashlib.sha256()
    for name, parameter in sorted(model.named_parameters()):
        if ("lora_" in name) != adapter:
            continue
        tensor = parameter.detach().cpu().contiguous()
        result.update(json.dumps([name, list(tensor.shape), str(tensor.dtype)]).encode())
        result.update(tensor.numpy().tobytes())
        del tensor
    return result.hexdigest()


def resources(rt, output: Path, device: str) -> dict:
    result = {"disk_free_bytes": shutil.disk_usage(output).free}
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["process_peak_rss_bytes"] = int(rss if sys.platform == "darwin" else rss * 1024)
    except (ImportError, OSError):
        result["process_peak_rss_bytes"] = None
    if device == "mps":
        result.update({"mps_current_allocated_bytes": rt["torch"].mps.current_allocated_memory(),
                       "mps_driver_allocated_bytes": rt["torch"].mps.driver_allocated_memory(),
                       "mps_recommended_max_bytes": rt["torch"].mps.recommended_max_memory()})
    return result


def event(output: Path, value: dict, echo: bool = True) -> None:
    # Aggregate events only: no transcript, audio, speaker or patient identifiers.
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(payload + "\n")
        stream.flush()
    if echo:
        print(payload, flush=True)


def encode_labels(processor, partitions: dict) -> dict[str, list[int]]:
    encoded = {}
    for rows in partitions.values():
        for row in rows:
            value = processor.tokenizer(row["text"], add_special_tokens=True,
                                        return_attention_mask=True, truncation=False)
            encoded[row["id"]] = label_ids(value["input_ids"], value["attention_mask"])
    return encoded


def audio_features(rt, processor, corpus: Path, row: dict, device: str, dtype_name: str):
    raw = safe_artifact(corpus, row["audio_filepath"]).read_bytes()
    pcm = read_pcm(raw)
    if (hashlib.sha256(raw).hexdigest() != row["audio_sha256"]
            or hashlib.sha256(pcm).hexdigest() != row["pcm_sha256"]):
        raise ValueError("Audio changé après la vérification initiale")
    waveform = rt["np"].frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
    values = processor.feature_extractor(waveform, sampling_rate=RATE, return_tensors="pt",
                                         padding="max_length", max_length=30 * RATE,
                                         truncation=False, return_attention_mask=True)
    features = values.input_features
    if tuple(features.shape) != (1, 128, 3000):
        raise ValueError("Dimensions mel inattendues ; aucune troncature audio implicite")
    return (features.to(device=device, dtype=getattr(rt["torch"], dtype_name)),
            values.attention_mask.to(device=device))


def token_retention(torch, student, teacher, real_tokens: int):
    """KL(base || adapter), averaged over lexical tokens and EOS, not vocabulary."""
    begin = len(PREFIX) - 1  # Do not distil the three forced task/language tokens.
    if student.shape != teacher.shape or len(student.shape) != 3 or student.shape[0] == 0 \
            or not begin < real_tokens <= student.shape[1]:
        raise ValueError("Dimensions de la rétention par jeton invalides")
    logits = student[:, begin:real_tokens].float()
    target = teacher.detach()[:, begin:real_tokens].float()
    return torch.nn.functional.kl_div(
        torch.log_softmax(logits, dim=-1), torch.log_softmax(target, dim=-1),
        reduction="sum", log_target=True) / (student.shape[0] * (real_tokens - begin))


def cross_entropy(torch, logits, targets, drug_positions: list[int] | None, drug_weight: float):
    flat_logits, flat_targets = logits.float().reshape(-1, logits.shape[-1]), targets.reshape(-1)
    if not drug_positions or drug_weight == 1.0:
        return torch.nn.functional.cross_entropy(flat_logits, flat_targets, ignore_index=-100)
    # A full-target mean by total weight keeps clips comparable in scale.
    losses = torch.nn.functional.cross_entropy(flat_logits, flat_targets, ignore_index=-100, reduction="none")
    indices = torch.tensor(drug_positions, device=logits.device, dtype=torch.long)
    weighted = losses.sum() + (drug_weight - 1.0) * losses.index_select(0, indices).sum()
    return weighted / ((flat_targets != -100).sum() + (drug_weight - 1.0) * len(drug_positions))


def forward_loss(rt, model, base, features, labels: list[int], device: str, dtype_name: str,
                 retention_weight: float = 0.0, drug_positions: list[int] | None = None, drug_weight: float = 1.0):
    torch = rt["torch"]
    targets = torch.tensor([labels], dtype=torch.long, device=device)
    decoder = torch.tensor([shift_labels(labels)], dtype=torch.long, device=device)
    real_tokens = sum(value != -100 for value in labels)
    # The frozen encoder never retains a backward graph. Decoder LoRA does.
    with torch.no_grad(), torch.autocast(device_type=device, dtype=torch.float16,
                                         enabled=dtype_name == "float16"):
        encoded = base.get_encoder()(input_features=features, return_dict=True)
    teacher = None
    if retention_weight:
        # PEFT toggles `requires_grad` when disabling adapters. Run the frozen
        # teacher first so this never touches an existing student graph.
        was_training, encoder_training = model.training, base.get_encoder().training
        try:
            model.eval()
            with model.disable_adapter(), torch.no_grad(), torch.autocast(
                    device_type=device, dtype=torch.float16, enabled=dtype_name == "float16"):
                teacher = model(encoder_outputs=encoded, decoder_input_ids=decoder,
                                use_cache=False, return_dict=True).logits
        finally:
            model.train(was_training)
            base.get_encoder().train(encoder_training)
    with torch.autocast(device_type=device, dtype=torch.float16, enabled=dtype_name == "float16"):
        logits = model(encoder_outputs=encoded, decoder_input_ids=decoder,
                       use_cache=False, return_dict=True).logits
    # Explicit FP32 CE: transformers 4.57.3's Whisper loss itself does not cast.
    ce = cross_entropy(torch, logits, targets, drug_positions, drug_weight)
    kl = token_retention(torch, logits, teacher, real_tokens) if teacher is not None else None
    loss = ce if kl is None else ce + retention_weight * kl
    if not bool(torch.isfinite(loss).item()):
        raise ValueError("Perte non finie : essai interrompu")
    return loss, real_tokens, ce.detach(), kl.detach() if kl is not None else None


def validation_loss(rt, model, base, processor, corpus, rows, labels, args, output) -> dict:
    torch = rt["torch"]
    model.eval()
    numerator, tokens = 0.0, 0
    started = time.monotonic()
    with torch.no_grad():
        for index, row in enumerate(rows, 1):
            features, _ = audio_features(rt, processor, corpus, row, args.device, args.dtype)
            loss, length, _, _ = forward_loss(rt, model, base, features, labels[row["id"]], args.device, args.dtype)
            numerator += float(loss.item()) * length
            tokens += length
            del loss, features
            if index % 32 == 0:
                event(output, {"phase": "validation_loss", "clips_done": index, "clips_total": len(rows)})
    result = {"clips": len(rows), "speakers": len({row["speaker_id"] for row in rows}),
              "tokens": tokens, "token_weighted_cross_entropy": numerator / tokens,
              "elapsed_seconds": time.monotonic() - started}
    return result


def require_finite_adapters(rt, tensors) -> None:
    torch = rt["torch"]
    with torch.no_grad():
        if not tensors or any(tensor.dtype != torch.float32 or not torch.isfinite(tensor).all().item()
                              for tensor in tensors):
            raise ValueError("Poids LoRA absents, de type inattendu ou non finis ; sauvegarde refusée")


def checkpoint(rt, model, output: Path, update: int, contract_hash: str, validation=None) -> Path:
    require_finite_adapters(rt, list(rt["state"](model).values()))
    checkpoints = output / "checkpoints"
    checkpoints.mkdir(exist_ok=True)
    destination = checkpoints / f"update-{update:06d}"
    if destination.exists():
        return destination
    with tempfile.TemporaryDirectory(prefix=".adapter-", dir=checkpoints) as temporary:
        stage = Path(temporary) / "complete"
        model.save_pretrained(str(stage), safe_serialization=True, save_embedding_layers=False)
        allowed = {"adapter_model.safetensors", "adapter_config.json", "README.md"}
        files = {path.name for path in stage.iterdir()}
        if not {"adapter_model.safetensors", "adapter_config.json"} <= files or files - allowed:
            raise ValueError("Sauvegarde non limitée aux adaptateurs")
        if sum(path.stat().st_size for path in stage.iterdir()) > 16 * 1024 ** 2:
            raise ValueError("Adaptateur anormalement volumineux")
        metadata = {"schema": 1, "actual_optimizer_updates": update,
                    "contract_sha256": contract_hash, "validation_loss": validation,
                    "adapter_parameters_sha256": tensor_digest(model, True),
                    "files_sha256": {path.name: sha256(path) for path in sorted(stage.iterdir())}}
        atomic_json(stage / "checkpoint.json", metadata)
        stage.rename(destination)
    atomic_json(output / "last.json", {"checkpoint": destination.relative_to(output).as_posix(),
                                        "actual_optimizer_updates": update})
    return destination


def reload_check(rt, model, checkpoint_path: Path) -> None:
    expected = {name: tensor.detach().cpu().clone() for name, tensor in rt["state"](model).items()}
    # PEFT 0.18 load_adapter casts a NEW adapter only after copying its weights.
    # On an FP16 base that round-trips trained FP32 values through FP16. Create
    # and promote just this adapter first, so the equality check is meaningful.
    config = rt["LoraConfig"].from_pretrained(str(checkpoint_path), local_files_only=True)
    model.add_adapter("reload_check", config)
    for name, parameter in model.named_parameters():
        if ".reload_check." in name and "lora_" in name:
            parameter.data = parameter.data.to(dtype=rt["torch"].float32)
    model.load_adapter(str(checkpoint_path), adapter_name="reload_check", is_trainable=False,
                       local_files_only=True, autocast_adapter_dtype=True,
                       torch_device="cpu")
    try:
        actual = rt["state"](model, adapter_name="reload_check")
        if expected.keys() != actual.keys() or any(not rt["torch"].equal(tensor, actual[name].detach().cpu())
                                                   for name, tensor in expected.items()):
            raise ValueError("Les adaptateurs rechargés diffèrent de ceux entraînés")
    finally:
        model.delete_adapter("reload_check")
        model.set_adapter("default")


def train(args):
    corpus, source, _, output, summary, provenance, partitions, hashes = prepare(args)
    rt = load_runtime(args.device)
    torch = rt["torch"]
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    if args.device == "mps":
        torch.mps.manual_seed(args.seed)
    selected = validation_selection(partitions["validation"], args.validation_limit)
    total = min(args.max_updates, args.epochs * math.ceil(len(partitions["train"]) / args.accumulation))
    # Resolve the exact training subsets once for both the objective and loop.
    train_epochs, remaining = [], total
    for epoch in range(args.epochs):
        if not remaining:
            break
        ordered = list(partitions["train"])
        random.Random(args.seed + epoch).shuffle(ordered)
        selected_train = ordered[:remaining * args.accumulation]
        train_epochs.append(selected_train)
        remaining -= math.ceil(len(selected_train) / args.accumulation)
    contract = {"schema": 1, "base": provenance, "corpus_source_sha256": PX_SHA256,
                "manifest_sha256": hashes, "partitions": summary, "seed": args.seed,
                "versions": rt["versions"], "platform": platform.platform(),
                "device": args.device, "dtype": args.dtype, "threads": args.threads,
                "target_modules": TARGETS, "rank": 8, "alpha": 16, "lora_dropout": 0.05,
                "trainable_parameters": LORA_PARAMETERS, "base_and_encoder_frozen": True,
                "batch_size": 1, "accumulation": args.accumulation, "epochs_requested": args.epochs,
                "optimizer_updates_planned": total, "peak_learning_rate": args.lr,
                "warmup_fraction": 0.1, "optimizer": "AdamW", "weight_decay": 0.01,
                "adamw_backend": args.adamw_backend,
                "training_rows_sha256": json_digest([[row["id"] for row in rows] for rows in train_epochs]),
                "max_grad_norm": 1.0, "validation_selection_key": SELECTION_KEY,
                "validation_rows_sha256": json_digest([row["id"] for row in selected]),
                "validation_rows": len(selected), "validation_choice": "token_weighted_cross_entropy",
                "development_only": True, "upstream_pretraining_overlap": "unknown",
                "starts_from": "verified_original_base_plus_new_zero_effect_LoRA",
                "resume": False, "micro_trial": total <= 8,
                "training_objective": {"cross_entropy_weight": 1.0,
                                       "base_retention_kl_weight": args.retention_weight,
                                       "drug_subtoken_weight": args.drug_weight,
                                       "drug_annotation_source": "locked train-only PxSLU BIO",
                                       "kl_tokens": "lexical_and_eos_no_forced_prefix_or_padding",
                                       "teacher": "same_frozen_base_eval_no_grad_adapter_disabled",
                                       "teacher_inputs": "same_train_audio_and_shifted_train_reference",
                                       "validation_loss_uses_teacher": False},
                "trainer_source_sha256": sha256(Path(__file__)),
                "validate_finite_adapter_weights_after_step_and_before_save": True,
                "bitwise_MPS_reproducibility_validated": False}
    output.mkdir(mode=0o700)
    atomic_json(output / "contract.json", contract)
    contract_hash = json_digest(contract)
    started = time.monotonic()
    actual = {"updates": 0}
    try:
        model, base, processor = model_setup(rt, source, args.device, args.dtype, True)
        labels = encode_labels(processor, partitions)
        drug_positions, drug_stats = {}, None
        if args.drug_weight != 1.0:
            selected_rows = {row["id"]: row for rows in train_epochs for row in rows}
            drug_positions, drug_stats = training_drug_positions(
                args.px_archive, processor.tokenizer, list(selected_rows.values()), labels, PREFIX, EOS)
            event(output, {"phase": "drug_weights", "unique_training_rows": len(selected_rows), **drug_stats})
        initial_base, initial_adapter = tensor_digest(model, False), tensor_digest(model, True)
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        optimizer = (cpu_shadow_adamw(torch, trainable, lr=args.lr, weight_decay=0.01)
                     if args.adamw_backend == "cpu-shadow"
                     else torch.optim.AdamW(trainable, lr=args.lr, weight_decay=0.01, foreach=False))
        def stepped(optimizer, positional, keywords):
            actual["updates"] += 1
        handle = optimizer.register_step_post_hook(stepped)
        scaler = torch.amp.GradScaler(args.device, enabled=args.dtype == "float16", init_scale=1024.0)
        consumed, best, final_validation = 0, math.inf, None
        last_path = None
        event(output, {"phase": "ready", "updates_planned": total, "trainable_parameters": LORA_PARAMETERS,
                       "base_parameters_sha256": initial_base, "adapter_parameters_sha256": initial_adapter,
                       **resources(rt, output, args.device)})
        for epoch, ordered in enumerate(train_epochs):
            for group in accumulation_groups(ordered, args.accumulation):
                if actual["updates"] >= total:
                    break
                model.train()
                base.get_encoder().eval()
                optimizer.zero_grad(set_to_none=True)
                step_started, loss_sum, ce_sum, kl_sum = time.monotonic(), 0.0, 0.0, 0.0
                for row in group:
                    features, _ = audio_features(rt, processor, corpus, row, args.device, args.dtype)
                    loss, _, ce, kl = forward_loss(rt, model, base, features, labels[row["id"]],
                                                   args.device, args.dtype, args.retention_weight,
                                                   drug_positions.get(row["id"]), args.drug_weight)
                    ce_value = float(ce.item())
                    ce_sum += ce_value
                    loss_sum += ce_value if kl is None else float(loss.item())
                    if kl is not None:
                        kl_sum += float(kl.item())
                    scaler.scale(loss / len(group)).backward()
                    consumed += 1
                    del loss, ce, kl, features
                if any(parameter.grad is not None for name, parameter in model.named_parameters() if "lora_" not in name):
                    raise ValueError("Un paramètre de base gelé a reçu un gradient")
                scaler.unscale_(optimizer)
                if any(parameter.grad is None or not bool(torch.isfinite(parameter.grad).all().item())
                       for parameter in trainable):
                    raise ValueError("Gradient LoRA absent ou non fini ; aucun pas ignoré silencieusement")
                norm = torch.nn.utils.clip_grad_norm_(trainable, 1.0, error_if_nonfinite=True, foreach=False)
                if float(norm.item()) <= 0:
                    raise ValueError("Gradient global nul : aucun apprentissage mesurable")
                next_update = actual["updates"] + 1
                rate = learning_rate(next_update, total, args.lr)
                for group_config in optimizer.param_groups:
                    group_config["lr"] = rate
                scaler.step(optimizer)
                scaler.update()
                if actual["updates"] != next_update:
                    raise ValueError("L’optimiseur a ignoré une mise à jour")
                require_finite_adapters(rt, trainable)
                aggregate = {"phase": "train", "update": actual["updates"], "epoch": epoch + 1,
                             "clips_consumed": consumed, "clips_in_update": len(group),
                             "mean_clip_loss": loss_sum / len(group), "learning_rate": rate,
                             "unclipped_gradient_norm": float(norm.item()), "gradient_scale": scaler.get_scale(),
                             "update_seconds": time.monotonic() - step_started,
                             "elapsed_seconds": time.monotonic() - started}
                if args.retention_weight:
                    aggregate.update({"mean_clip_cross_entropy": ce_sum / len(group),
                                      "mean_clip_base_retention_kl": kl_sum / len(group)})
                echo = actual["updates"] == 1 or actual["updates"] % 5 == 0 or actual["updates"] == total
                if echo:
                    aggregate.update(resources(rt, output, args.device))
                    if aggregate["disk_free_bytes"] < int(args.min_free_gib * 1024 ** 3):
                        raise ValueError("La marge de disque est passée sous le seuil fixé")
                event(output, aggregate, echo)
                if args.checkpoint_every and actual["updates"] % args.checkpoint_every == 0 and actual["updates"] < total:
                    last_path = checkpoint(rt, model, output, actual["updates"], contract_hash)
            final_validation = validation_loss(rt, model, base, processor, corpus, selected, labels, args, output)
            last_path = checkpoint(rt, model, output, actual["updates"], contract_hash, final_validation)
            score = final_validation["token_weighted_cross_entropy"]
            if score < best:
                best = score
                atomic_json(output / "best.json", {"checkpoint": last_path.relative_to(output).as_posix(),
                                                    "actual_optimizer_updates": actual["updates"],
                                                    "selection": "validation_token_weighted_cross_entropy",
                                                    "validation": final_validation})
            event(output, {"phase": "validation_complete", "update": actual["updates"], **final_validation})
            if actual["updates"] >= total:
                break
        handle.remove()
        final_base, final_adapter = tensor_digest(model, False), tensor_digest(model, True)
        if final_base != initial_base or final_adapter == initial_adapter or actual["updates"] != total:
            raise ValueError("Contrôle final des poids ou des mises à jour échoué")
        reload_check(rt, model, last_path)
        result = {"schema": 1, "status": "completed", "training_performed": True,
                  "mechanics_only_micro_trial": total <= 8, "promoted_to_application": False,
                  "actual_optimizer_updates": actual["updates"], "clips_consumed": consumed,
                  "base_weights_unchanged": True, "adapter_weights_changed": True,
                  "adapter_reload_exact": True, "base_parameters_sha256": final_base,
                  "adapter_initial_sha256": initial_adapter, "adapter_final_sha256": final_adapter,
                  "contract_sha256": contract_hash, "last_validation": final_validation,
                  "elapsed_seconds": time.monotonic() - started, **resources(rt, output, args.device)}
        atomic_json(output / "report.json", result)
        event(output, result)
        return result
    except BaseException as error:
        atomic_json(output / "report.json", {"schema": 1, "status": "failed", "training_performed": actual["updates"] > 0,
                    "actual_optimizer_updates": actual["updates"], "promoted_to_application": False,
                    "contract_sha256": contract_hash,
                    "error_type": type(error).__name__, "elapsed_seconds": time.monotonic() - started})
        raise


def verify_adapter(adapter: Path, provenance: dict, manifest_hashes: dict) -> dict:
    metadata = json.loads(safe_artifact(adapter, "checkpoint.json").read_text(encoding="utf-8"))
    run = adapter.parent.parent
    contract = json.loads(safe_artifact(run, "contract.json").read_text(encoding="utf-8"))
    report = json.loads(safe_artifact(run, "report.json").read_text(encoding="utf-8"))
    if (metadata.get("schema") != 1 or metadata.get("contract_sha256") != json_digest(contract)
            or contract.get("base") != provenance or contract.get("manifest_sha256") != manifest_hashes
            or contract.get("corpus_source_sha256") != PX_SHA256
            or contract.get("target_modules") != TARGETS or contract.get("rank") != 8
            or metadata.get("actual_optimizer_updates", 0) < 1
            or report.get("status") != "completed" or report.get("base_weights_unchanged") is not True
            or report.get("adapter_reload_exact") is not True
            or report.get("contract_sha256") != metadata["contract_sha256"]
            or metadata["actual_optimizer_updates"] > report.get("actual_optimizer_updates", 0)):
        raise ValueError("Provenance ou contrat d’adaptateur incompatible")
    expected = {"adapter_model.safetensors", "adapter_config.json", "README.md"}
    if set(metadata["files_sha256"]) - expected or not {"adapter_model.safetensors", "adapter_config.json"} <= set(metadata["files_sha256"]):
        raise ValueError("Fichiers d’adaptateur non conformes")
    if {path.name for path in adapter.iterdir()} != set(metadata["files_sha256"]) | {"checkpoint.json"}:
        raise ValueError("Fichier supplémentaire dans l’adaptateur ; chargement refusé")
    for name, digest in metadata["files_sha256"].items():
        if sha256(safe_artifact(adapter, name)) != digest:
            raise ValueError("Adaptateur modifié après sauvegarde")
    return metadata


def generated_sequence(generated) -> tuple[list[int], bool]:
    """Inspect the raw sequence; Whisper's default tensor return strips EOS."""
    sequences = getattr(generated, "sequences", None)
    if sequences is None or len(sequences) != 1:
        raise ValueError("Résultat de génération structuré attendu pour un seul clip")
    token_ids = sequences[0].tolist()
    if (not isinstance(token_ids, list) or token_ids[:len(PREFIX)] != PREFIX
            or any(type(value) is not int or not 0 <= value < 51866 for value in token_ids)):
        raise ValueError("Séquence de génération française inattendue")
    return token_ids, EOS in token_ids[len(PREFIX):]


def evaluate(args):
    corpus, source, adapter, output, summary, provenance, partitions, hashes = prepare(args)
    selected = validation_window(partitions["validation"], args.count, args.offset)
    metadata = verify_adapter(adapter, provenance, hashes) if adapter else None
    rt = load_runtime(args.device)
    torch = rt["torch"]
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    output.mkdir(mode=0o700)
    model, base, processor = model_setup(rt, source, args.device, args.dtype, False, adapter)
    model.eval()
    methods = ("base", "adapter") if adapter else ("base",)
    aggregate = {name: {"reference_words": 0, "word_errors": 0, "clips": 0,
                        "generation_without_eos": 0, "inference_seconds": 0.0} for name in methods}
    contract = {"schema": 1, "base": provenance, "adapter": metadata,
                "manifest_sha256": hashes, "validation_selection_key": SELECTION_KEY,
                "selected_rows_sha256": json_digest([row["id"] for row in selected]),
                "validation_offset": args.offset,
                "selected_clips": len(selected), "selected_speakers": len({r["speaker_id"] for r in selected}),
                "generation": GENERATION, "dtype": args.dtype, "device": args.device,
                "return_dict_in_generate": True,
                "eos_observation": "raw sequences after decoder prefix, before Whisper strips special tokens",
                "versions": rt["versions"], "seed": args.seed, "development_only": True,
                "references_never_passed_to_generate": True,
                "scoring": "p0.bench.scoring.words + edit_distance; corpus-weighted WER",
                "safety_metrics": "WER alone does not validate drugs, doses, fractions or negations"}
    atomic_json(output / "contract.json", contract)
    started = time.monotonic()
    with torch.inference_mode(), (output / "predictions.local.jsonl").open("x", encoding="utf-8") as stream:
        for index, row in enumerate(selected, 1):
            features, mask = audio_features(rt, processor, corpus, row, args.device, args.dtype)
            result = {"id": row["id"], "speaker_id": row["speaker_id"], "reference": row["text"]}
            for method in methods:
                context = model.disable_adapter() if adapter and method == "base" else nullcontext()
                if args.device == "mps":
                    torch.mps.synchronize()
                begin = time.monotonic()
                with context, torch.autocast(device_type=args.device, dtype=torch.float16,
                                             enabled=args.dtype == "float16"):
                    generated = model.generate(input_features=features, attention_mask=mask,
                                               return_dict_in_generate=True, **GENERATION)
                if args.device == "mps":
                    torch.mps.synchronize()
                elapsed = time.monotonic() - begin
                token_ids, eos_present = generated_sequence(generated)
                text = processor.tokenizer.decode(token_ids, skip_special_tokens=True).strip()
                errors, count = edit_distance(words(row["text"]), words(text)), len(words(row["text"]))
                result[method] = {"text": text, "inference_seconds": elapsed, "word_errors": errors,
                                  "reference_words": count, "eos_present": eos_present}
                metrics = aggregate[method]
                metrics["clips"] += 1
                metrics["reference_words"] += count
                metrics["word_errors"] += errors
                metrics["generation_without_eos"] += int(not eos_present)
                metrics["inference_seconds"] += elapsed
                del generated
            stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            del features, mask
            if index % 5 == 0 or index == len(selected):
                event(output, {"phase": "generate", "clips_done": index, "clips_total": len(selected),
                               "elapsed_seconds": time.monotonic() - started, **resources(rt, output, args.device)})
    for values in aggregate.values():
        values["wer"] = values["word_errors"] / values["reference_words"]
    report = {"schema": 1, "status": "completed", "development_only": True,
              "promoted_to_application": False, "paired_same_audio": bool(adapter),
              "scores": aggregate, "selected_clips": len(selected),
              "selected_speakers": len({row["speaker_id"] for row in selected}),
              "audio_seconds": sum(row["duration"] for row in selected),
              "contract_sha256": json_digest(contract), "elapsed_seconds": time.monotonic() - started,
              "limitation": "Validation used for development, not independent clinical or Windows qualification",
              **resources(rt, output, args.device)}
    atomic_json(output / "report.json", report)
    event(output, report)
    return report


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train", help="Nouvel essai LoRA hors ligne ; défaut : huit mises à jour")
    evaluation = commands.add_parser("evaluate", help="Génération libre de validation, base et adaptateur appariés")
    for command in (training, evaluation):
        command.add_argument("--model", type=Path, required=True)
        command.add_argument("--corpus", type=Path, required=True)
        command.add_argument("--px-archive", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--device", choices=("mps", "cpu"), default="mps")
        command.add_argument("--dtype", choices=("float16", "float32"), default="float16")
        command.add_argument("--seed", type=int, default=20261114)
        command.add_argument("--threads", type=int, default=4)
        command.add_argument("--min-free-gib", type=float, default=2.0)
    training.add_argument("--max-updates", type=int, default=8)
    training.add_argument("--epochs", type=int, default=1)
    training.add_argument("--accumulation", type=int, default=4)
    training.add_argument("--lr", type=float, default=1e-4)
    training.add_argument("--retention-weight", type=float, default=0.0,
                          help="Coefficient KL vers la base gelée ; 0 conserve la perte historique")
    training.add_argument("--adamw-backend", choices=("native", "cpu-shadow"), default="native",
                          help="Essai explicite : conserver le calcul MPS, effectuer le pas LoRA AdamW sur CPU")
    training.add_argument("--drug-weight", type=float, default=1.0,
                          help="Poids CE des seuls jetons médicament PxSLU train ; 1 laisse la CE inchangée")
    training.add_argument("--validation-limit", type=int, default=0, help="0 = les 282 clips ; 8 pour un mini-essai")
    training.add_argument("--checkpoint-every", type=int, default=50)
    evaluation.add_argument("--adapter", type=Path)
    evaluation.add_argument("--count", type=int, default=32, help="Clips de validation ; 0 = tous")
    evaluation.add_argument("--offset", type=int, default=0, help="Clips classés à écarter au début de la validation")
    return result


def main():
    command = parser()
    args = command.parse_args()
    try:
        if not 1 <= args.threads <= 16 or not math.isfinite(args.min_free_gib) or args.min_free_gib < 1:
            raise ValueError("Threads entre 1 et 16 et marge disque d’au moins 1 Gio requis")
        if args.command == "train":
            if (min(args.max_updates, args.epochs, args.accumulation) < 1
                    or args.validation_limit < 0 or args.checkpoint_every < 0
                    or not math.isfinite(args.lr) or not 0 < args.lr <= 1e-3
                    or not math.isfinite(args.retention_weight) or not 0 <= args.retention_weight <= 1
                    or not math.isfinite(args.drug_weight) or not 1 <= args.drug_weight <= 4
                    or args.drug_weight != 1 and args.retention_weight != 0):
                raise ValueError("Paramètres d’entraînement invalides")
            train(args)
        else:
            evaluate(args)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, ImportError) as error:
        command.exit(1, f"Essai refusé ou interrompu : {error}\n")


if __name__ == "__main__":
    main()
