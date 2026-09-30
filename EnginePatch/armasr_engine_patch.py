#!/usr/bin/env python3
#
"""Apply / revert the Arm ASR VR engine patch on an Unreal Engine source tree.

The patch lets the Arm ASR plugin upscale on the mobile renderer of the Meta
(oculus-5.5) engine fork, with or without Mobile HDR. Every change is gated by
the console variable r.ArmASR.MobileUpscale (registered by the plugin), so a
patched engine behaves exactly like the original one while it is 0.

    python armasr_engine_patch.py status  [--engine <root>]
    python armasr_engine_patch.py apply   [--engine <root>] [--dry-run]
    python armasr_engine_patch.py revert  [--engine <root>] [--force]

Original files are copied to EnginePatch/Backups/<engine>/ before being
modified, and restored byte for byte by `revert`. A manifest with the SHA-256
of the original and patched files is used to detect files that were changed
by someone else after patching.
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import stat
import sys

PATCH_ID = "ARMASR_VR_PATCH"
PATCH_VERSION = 2
DEFAULT_ENGINE = r"J:\_AtlasXRInc\Unreality"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def helper(suffix):
    """File-local accessor for r.ArmASR.MobileUpscale.

    The name is unique per file so that unity builds never see two definitions.
    The variable is looked up by name because it is registered by the plugin,
    which may not be loaded (the helper then returns false).
    """
    return (
        "// BEGIN ARMASR_VR_PATCH - Arm ASR mobile temporal upscale (see r.ArmASR.MobileUpscale)\n"
        "static bool ArmASRVR_IsMobileUpscaleEnabled_{0}()\n"
        "{{\n"
        "\tstatic const TConsoleVariableData<int32>* CVar = nullptr;\n"
        "\tif (!CVar)\n"
        "\t{{\n"
        "\t\tCVar = IConsoleManager::Get().FindTConsoleVariableDataInt(TEXT(\"r.ArmASR.MobileUpscale\"));\n"
        "\t}}\n"
        "\treturn CVar && CVar->GetValueOnAnyThread() != 0;\n"
        "}}\n"
        "// END ARMASR_VR_PATCH\n"
        "\n"
    ).format(suffix)


# Each edit is (kind, anchor, text):
#   "before"  inserts text before the anchor,
#   "after"   inserts text after the anchor,
#   "replace" replaces the anchor with text.
# Anchors must match exactly once in the file (after newline normalisation).
PATCHES = [
    {
        "file": "Engine/Source/Runtime/Engine/Private/SceneUtils.cpp",
        "why": "Disable the Meta tonemap subpass so the regular mobile post-process chain (which runs the temporal upscaler) is used, in HDR and LDR.",
        "edits": [
            ("before",
             "// BEGIN META SECTION 5.5 intead of checking bMultiViewRendering",
             helper("SceneUtils")),
            ("after",
             "ENGINE_API bool IsMobileTonemapSubpassEnabled(EShaderPlatform Platform, bool)\n// END META SECTION\n{\n",
             "\t// BEGIN ARMASR_VR_PATCH - the tonemap subpass replaces the post-process chain, which the temporal upscaler needs.\n"
             "\tif (ArmASRVR_IsMobileUpscaleEnabled_SceneUtils())\n"
             "\t{\n"
             "\t\treturn false;\n"
             "\t}\n"
             "\t// END ARMASR_VR_PATCH\n"),
        ],
    },
    {
        "file": "Engine/Source/Runtime/Engine/Private/SceneView.cpp",
        "why": "Allow screen percentage with Mobile LDR.",
        "edits": [
            ("before",
             "bool FSceneViewFamily::SupportsScreenPercentage() const\n",
             helper("SceneView")),
            ("replace",
             "!IsMobileHDR() && !bMobileLDRDynamicResolution)",
             "!IsMobileHDR() && !bMobileLDRDynamicResolution && !ArmASRVR_IsMobileUpscaleEnabled_SceneView() /* ARMASR_VR_PATCH */)"),
        ],
    },
    {
        "file": "Engine/Source/Runtime/Engine/Private/GameViewportClient.cpp",
        "why": "Let the game viewport apply r.ScreenPercentage with Mobile LDR.",
        "edits": [
            ("before",
             "void UGameViewportClient::Draw(FViewport* InViewport, FCanvas* SceneCanvas)\n",
             helper("GameViewportClient")),
            ("replace",
             "const bool bIsMobileLDR = (ViewFamily.GetFeatureLevel() <= ERHIFeatureLevel::ES3_1 && !IsMobileHDR());",
             "const bool bIsMobileLDR = (ViewFamily.GetFeatureLevel() <= ERHIFeatureLevel::ES3_1 && !IsMobileHDR() && !ArmASRVR_IsMobileUpscaleEnabled_GameViewportClient() /* ARMASR_VR_PATCH */);"),
        ],
    },
    {
        "file": "Engine/Source/Runtime/Renderer/Private/SceneRendering.cpp",
        "why": "Keep temporal AA (jitter, velocity, upscaler) on mobile views without post-processing when a temporal upscaler is set.",
        "edits": [
            ("before",
             "void FSceneRenderer::PrepareViewRectsForRendering(FRHICommandListImmediate& RHICmdList)\n",
             helper("SceneRendering")),
            ("replace",
             "const bool bWillApplyTemporalAA = (IsPostProcessingEnabled(View) || View.bIsPlanarReflection || View.bSceneCaptureMainViewJitter)",
             "const bool bWillApplyTemporalAA = (IsPostProcessingEnabled(View) || View.bIsPlanarReflection || View.bSceneCaptureMainViewJitter\n"
             "\t\t\t\t// BEGIN ARMASR_VR_PATCH\n"
             "\t\t\t\t|| (View.GetFeatureLevel() <= ERHIFeatureLevel::ES3_1 && ViewFamily.GetTemporalUpscalerInterface() != nullptr && ArmASRVR_IsMobileUpscaleEnabled_SceneRendering())\n"
             "\t\t\t\t// END ARMASR_VR_PATCH\n"
             "\t\t\t\t)"),
        ],
    },
    {
        "file": "Engine/Source/Runtime/Renderer/Private/MobileShadingRenderer.cpp",
        "why": "Render into the (reduced resolution) scene colour instead of the back buffer when upscaling in Mobile LDR, "
               "and skip the scene velocity pass when Arm ASR reads the AppSpaceWarp motion vectors instead.",
        "edits": [
            ("before",
             "void FMobileSceneRenderer::InitViews(",
             helper("MobileShadingRenderer")
             + "// BEGIN ARMASR_VR_PATCH - with the SpaceWarp velocity shaders, the scene velocity holds raw signed values in a UNORM\n"
               "// target that Arm ASR cannot use: it reads the AppSpaceWarp motion vectors (or depth) instead, so the pass is wasted.\n"
               "static bool ArmASRVR_SkipSceneVelocity(const FSceneViewFamily& ViewFamily, EShaderPlatform ShaderPlatform)\n"
               "{\n"
               "\tstatic const TConsoleVariableData<int32>* CVarVelocitySource = nullptr;\n"
               "\tif (!CVarVelocitySource)\n"
               "\t{\n"
               "\t\tCVarVelocitySource = IConsoleManager::Get().FindTConsoleVariableDataInt(TEXT(\"r.ArmASR.VelocitySource\"));\n"
               "\t}\n"
               "\treturn ArmASRVR_IsMobileUpscaleEnabled_MobileShadingRenderer()\n"
               "\t\t&& ViewFamily.GetTemporalUpscalerInterface() != nullptr\n"
               "\t\t&& SupportsSpaceWarp(ShaderPlatform)\n"
               "\t\t&& CVarVelocitySource && CVarVelocitySource->GetValueOnAnyThread() != 1;\n"
               "}\n"
               "// END ARMASR_VR_PATCH\n"
               "\n"),
            ("replace",
             "bRenderToSceneColor = !bGammaSpace",
             "bRenderToSceneColor = !bGammaSpace\n"
             "\t\t\t\t\t\t|| (ViewFamily.GetTemporalUpscalerInterface() != nullptr && ArmASRVR_IsMobileUpscaleEnabled_MobileShadingRenderer()) /* ARMASR_VR_PATCH */"),
            ("replace",
             "\t\tif (bShouldRenderVelocities)\n\t\t{\n\t\t\t// Render the velocities of movable objects\n",
             "\t\tif (bShouldRenderVelocities && !ArmASRVR_SkipSceneVelocity(ViewFamily, ShaderPlatform) /* ARMASR_VR_PATCH */)\n\t\t{\n\t\t\t// Render the velocities of movable objects\n"),
        ],
    },
    {
        "file": "Engine/Source/Runtime/Renderer/Private/PostProcess/PostProcessing.cpp",
        "why": "Run the third party temporal upscaler when mobile post-processing is disabled (Mobile LDR).",
        "edits": [
            ("before",
             "void AddMobilePostProcessingPasses(FRDGBuilder& GraphBuilder, FScene* Scene,",
             helper("PostProcessing")),
            ("after",
             "\t\tPassSequence.SetEnabled(EPass::PostProcessMaterialAfterTonemapping, false);\n"
             "\t\tPassSequence.SetEnabled(EPass::FXAA, false);\n"
             "\t\tPassSequence.Finalize();\n",
             "\n"
             "\t\t// BEGIN ARMASR_VR_PATCH - temporal upscale without mobile post-processing (Mobile LDR).\n"
             "\t\tif (ArmASRVR_IsMobileUpscaleEnabled_PostProcessing()\n"
             "\t\t\t&& View.Family->GetTemporalUpscalerInterface() != nullptr\n"
             "\t\t\t&& IsTemporalAccumulationBasedMethod(View.AntiAliasingMethod)\n"
             "\t\t\t&& Velocity.Texture != nullptr)\n"
             "\t\t{\n"
             "\t\t\tFDefaultTemporalUpscaler::FInputs UpscalerPassInputs{};\n"
             "\t\t\tUpscalerPassInputs.SceneColor = FScreenPassTexture(SceneColor.Texture, View.ViewRect);\n"
             "\t\t\tUpscalerPassInputs.SceneDepth = FScreenPassTexture(SceneDepth.Texture, View.ViewRect);\n"
             "\t\t\tUpscalerPassInputs.SceneVelocity = FScreenPassTexture(Velocity.Texture, View.ViewRect);\n"
             "\n"
             "\t\t\tconst FDefaultTemporalUpscaler::FOutputs Outputs = AddThirdPartyTemporalUpscalerPasses(GraphBuilder, View, UpscalerPassInputs);\n"
             "\t\t\tSceneColor = FScreenPassTexture(Outputs.FullRes);\n"
             "\t\t}\n"
             "\t\t// END ARMASR_VR_PATCH\n"),
        ],
    },
]


# ---------------------------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------------------------

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), newline, bom


def write_text(path, text, newline, bom):
    data = text.replace("\n", newline).encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    make_writable(path)
    with open(path, "wb") as f:
        f.write(data)


def make_writable(path):
    if os.path.exists(path):
        mode = os.stat(path).st_mode
        if not mode & stat.S_IWRITE:
            os.chmod(path, mode | stat.S_IWRITE)


def engine_key(engine_root):
    name = os.path.basename(os.path.normpath(engine_root)) or "engine"
    digest = hashlib.sha1(os.path.normcase(os.path.abspath(engine_root)).encode("utf-8")).hexdigest()[:8]
    return "{}_{}".format(name, digest)


def backup_dir(engine_root):
    return os.path.join(SCRIPT_DIR, "Backups", engine_key(engine_root))


def manifest_path(engine_root):
    return os.path.join(backup_dir(engine_root), "manifest.json")


def load_manifest(engine_root):
    path = manifest_path(engine_root)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def engine_version(engine_root):
    path = os.path.join(engine_root, "Engine", "Build", "Build.version")
    try:
        with open(path, "r", encoding="utf-8") as f:
            v = json.load(f)
        return "{}.{}.{} ({})".format(v.get("MajorVersion"), v.get("MinorVersion"), v.get("PatchVersion"), v.get("BranchName", "?"))
    except (OSError, ValueError):
        return "unknown"


def apply_edits(text, edits, rel):
    """Returns the patched text, or raises ValueError describing the first anchor problem."""
    for kind, anchor, payload in edits:
        count = text.count(anchor)
        if count != 1:
            raise ValueError("{}: anchor found {} time(s) (expected 1):\n    {}".format(rel, count, anchor.splitlines()[0] if anchor else anchor))
        if kind == "before":
            text = text.replace(anchor, payload + anchor)
        elif kind == "after":
            text = text.replace(anchor, anchor + payload)
        elif kind == "replace":
            text = text.replace(anchor, payload)
        else:
            raise ValueError("unknown edit kind " + kind)
    return text


# ---------------------------------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------------------------------

def cmd_status(engine_root):
    manifest = load_manifest(engine_root)
    print("Engine : {}  [{}]".format(engine_root, engine_version(engine_root)))
    print("Backups: {}".format(backup_dir(engine_root)))
    if manifest is None:
        print("State  : NOT APPLIED (no manifest)")
    else:
        print("State  : APPLIED on {} (patch v{})".format(manifest.get("applied_at"), manifest.get("patch_version")))
    print()
    for patch in PATCHES:
        rel = patch["file"]
        path = os.path.join(engine_root, rel)
        if not os.path.isfile(path):
            print("  [missing ] " + rel)
            continue
        text, _, _ = read_text(path)
        has_marker = PATCH_ID in text
        entry = (manifest or {}).get("files", {}).get(rel)
        current = sha256(path)
        if entry and current == entry["patched_sha256"]:
            state = "patched "
        elif entry and current == entry["original_sha256"]:
            state = "original"
        elif entry:
            state = "CHANGED "
        else:
            state = "patched?" if has_marker else "original"
        print("  [{}] {}".format(state, rel))
    return 0


def cmd_apply(engine_root, dry_run):
    if load_manifest(engine_root) is not None:
        print("The patch is already applied to this engine (manifest found). Run 'revert' first.")
        return 1

    # Validate everything before touching a single file.
    planned = []
    errors = []
    for patch in PATCHES:
        rel = patch["file"]
        path = os.path.join(engine_root, rel)
        if not os.path.isfile(path):
            errors.append("{}: file not found".format(rel))
            continue
        text, newline, bom = read_text(path)
        if PATCH_ID in text:
            errors.append("{}: already contains {} markers but no manifest exists".format(rel, PATCH_ID))
            continue
        try:
            patched = apply_edits(text, patch["edits"], rel)
        except ValueError as e:
            errors.append(str(e))
            continue
        planned.append((rel, path, patched, newline, bom))

    if errors:
        print("Cannot apply the patch, nothing was modified:")
        for e in errors:
            print("  - " + e)
        return 1

    print("Engine: {}  [{}]".format(engine_root, engine_version(engine_root)))
    for patch in PATCHES:
        print("  + {}\n      {}".format(patch["file"], patch["why"]))
    if dry_run:
        print("\nDry run: all anchors found, nothing was modified.")
        return 0

    bdir = backup_dir(engine_root)
    manifest = {
        "patch_id": PATCH_ID,
        "patch_version": PATCH_VERSION,
        "engine_root": os.path.abspath(engine_root),
        "engine_version": engine_version(engine_root),
        "applied_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "files": {},
    }

    # Back up every original first, then write.
    for rel, path, _, _, _ in planned:
        dst = os.path.join(bdir, "files", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)
        manifest["files"][rel] = {"original_sha256": sha256(path)}
    os.makedirs(bdir, exist_ok=True)

    written = []
    try:
        for rel, path, patched, newline, bom in planned:
            write_text(path, patched, newline, bom)
            written.append(rel)
            manifest["files"][rel]["patched_sha256"] = sha256(path)
    except OSError as e:
        print("Write failed ({}), restoring the files already written...".format(e))
        for rel in written:
            shutil.copy2(os.path.join(bdir, "files", rel), os.path.join(engine_root, rel))
        return 1

    with open(manifest_path(engine_root), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("\nPatch applied to {} files. Originals saved in:\n  {}".format(len(written), bdir))
    print("Rebuild the engine (Engine + Renderer modules), then set r.ArmASR.MobileUpscale=1 to activate it.")
    return 0


def cmd_revert(engine_root, force):
    manifest = load_manifest(engine_root)
    if manifest is None:
        print("No manifest found: the patch is not applied to this engine (by this tool).")
        return 1

    bdir = backup_dir(engine_root)
    conflicts = []
    for rel, entry in manifest["files"].items():
        path = os.path.join(engine_root, rel)
        if os.path.isfile(path) and sha256(path) not in (entry.get("patched_sha256"), entry["original_sha256"]):
            conflicts.append(rel)

    if conflicts and not force:
        print("These files were modified after the patch was applied:")
        for rel in conflicts:
            print("  - " + rel)
        print("Nothing was restored. Re-run with --force to restore the originals anyway")
        print("(the current versions are kept next to them as <file>.armasr-conflict).")
        return 1

    for rel, entry in manifest["files"].items():
        path = os.path.join(engine_root, rel)
        src = os.path.join(bdir, "files", rel)
        if rel in conflicts:
            shutil.copy2(path, path + ".armasr-conflict")
        make_writable(path)
        shutil.copy2(src, path)
        if sha256(path) != entry["original_sha256"]:
            print("  ! {}: restored file does not match the original hash".format(rel))
        else:
            print("  - restored {}".format(rel))

    shutil.rmtree(bdir)
    print("\nPatch reverted, the original files are back. Rebuild the engine.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Apply / revert the Arm ASR VR engine patch.")
    parser.add_argument("command", choices=["status", "apply", "revert"])
    parser.add_argument("--engine", default=DEFAULT_ENGINE, help="Engine root (folder containing Engine/). Default: " + DEFAULT_ENGINE)
    parser.add_argument("--dry-run", action="store_true", help="apply: only check that every anchor is found")
    parser.add_argument("--force", action="store_true", help="revert: restore originals even if files changed after patching")
    args = parser.parse_args()

    engine_root = os.path.abspath(args.engine)
    if not os.path.isdir(os.path.join(engine_root, "Engine", "Source")):
        print("Not an engine source tree: " + engine_root)
        return 1

    if args.command == "status":
        return cmd_status(engine_root)
    if args.command == "apply":
        return cmd_apply(engine_root, args.dry_run)
    return cmd_revert(engine_root, args.force)


if __name__ == "__main__":
    sys.exit(main())
