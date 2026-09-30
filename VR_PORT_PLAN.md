# Arm ASR → VR (Meta Quest) — plan et état

Guide d'utilisation et de test : [VR_QUEST.md](VR_QUEST.md).

Cible : **Unreality** (fork Meta `oculus-5.5.3`), mobile forward Vulkan, multiview, avec le choix **HDR ou LDR**.
Ensuite : UE 5.8, puis évaluation du mobile deferred sur Quest.

## État

| Étape | État |
|---|---|
| Stéréo : accepter une paire de vues, historique et frame index par œil | ✅ codé, compile |
| Multiview : traitement par couche de texture array, matrices de l'œil droit (vue instanciée) | ✅ codé, compile |
| Side-by-side : copie couleur/profondeur de l'œil décalé pendant la conversion des motion vectors | ✅ codé, compile |
| Patch moteur (HDR : désactiver le tonemap subpass ; LDR : screen %, TAA, scene color, appel upscaler) | ✅ outil apply/revert testé sur une copie des fichiers |
| Test sur casque (LDR multiview, HDR multiview, side-by-side) | ⏳ à faire |
| Mesures de perf vs MSAA 4x | ⏳ à faire |
| Motion vectors AppSpaceWarp comme source de vélocité (éviter la passe de vélocité UE) | 💡 piste |
| Exposition fixe à 1.0 en LDR, permutation `ARMASR_LDR_INPUT` (sans tonemap HDR) | ✅ codé, compile |
| CVar `r.ArmASR.MobileUpscale` dans les Project Settings | ✅ |
| Portage UE 5.8 (plugin + ancres du patch moteur) | ⏳ après validation 5.5 |
| Mobile deferred sur Quest (réactiver le reactive mask GBuffer) | ⏳ selon perf |

## Constats moteur (fork Meta 5.5)

- Le post-process mobile appelle bien les upscalers tiers (`AddThirdPartyTemporalUpscalerPasses`).
- **Mais** `IsMobileTonemapSubpassEnabled()` renvoie vrai dès que Mobile HDR est actif (section META) :
  la chaîne de post-process est remplacée par `AddMobileCustomResolvePass` et l'upscaler n'est jamais appelé.
- En LDR : `SupportsScreenPercentage()` est faux, `IsPostProcessingEnabled()` est faux (donc AA = None), et on rend dans le backbuffer.
- En multiview, seule la vue principale fait le post-process (`ShouldRenderView`), pour les deux couches à la fois.
- La vélocité mobile est rendue en multiview (texture array) dès que le TAA est actif.

## Portage 5.8 — à prévoir
- Les ancres du patch moteur seront à revalider (`armasr_engine_patch.py apply --dry-run --engine <5.8>`),
  et le tableau `PATCHES` pourra être décliné par version.
- API RDG/ITemporalUpscaler à vérifier (déjà `#if ENGINE_MINOR_VERSION` dans le plugin).
