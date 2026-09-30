# Arm ASR sur Meta Quest (VR, mobile forward, Vulkan)

Branche `vr-quest`. Cible : moteur **Unreality** (fork Meta `oculus-5.5.3`), renderer mobile forward, Vulkan, multiview.

L'idée : rendre chaque œil à résolution réduite (`r.ScreenPercentage`), puis reconstruire la pleine résolution
avec Arm ASR (upscaling temporel). L'anti-aliasing temporel de l'upscaler remplace le MSAA.

## Ce qui a changé dans le plugin

- **Stéréo** : le plugin accepte une paire de vues VR (avant : désactivé dès qu'il y avait plus d'une vue).
- **Multiview** : les deux yeux sont dans les couches d'une texture array. Le plugin traite chaque couche
  (SRV par couche, sortie écrite couche par couche) et utilise les matrices de l'œil droit (vue instanciée).
- **Side-by-side** (multiview désactivé) : l'œil droit ne commence pas en (0,0). Couleur et profondeur sont
  copiées vers des textures alignées pendant la conversion des motion vectors.
- **Historique par œil** (le compteur de frames global a été supprimé, il est maintenant dans l'historique).
- Reactive mask désactivé en stéréo (il lit la GBuffer de la vue principale, inexistante en forward).
- Nouvelle CVar `r.ArmASR.MobileUpscale` (lue par le patch moteur, voir plus bas).

## Pourquoi un patch moteur

Dans le fork Meta, le renderer mobile forward **ne lance jamais la chaîne de post-process** :
- en **HDR**, le tonemapping est fait dans un *subpass* (`IsMobileTonemapSubpassEnabled` renvoie vrai dès que Mobile HDR est actif) ;
- en **LDR**, il n'y a pas de post-process du tout, on rend directement dans le backbuffer, et le screen percentage est interdit.

Or l'upscaler temporel est appelé depuis la chaîne de post-process. Le patch (6 fichiers, ~100 lignes) :

| Fichier | Rôle |
|---|---|
| `Engine/Private/SceneUtils.cpp` | Désactive le tonemap subpass → la chaîne de post-process normale tourne (HDR) |
| `Engine/Private/SceneView.cpp` | Autorise le screen percentage en Mobile LDR |
| `Engine/Private/GameViewportClient.cpp` | Applique `r.ScreenPercentage` au viewport de jeu en Mobile LDR |
| `Renderer/Private/SceneRendering.cpp` | Garde le TAA (jitter, vélocité, upscaler) sans post-process quand un upscaler est présent |
| `Renderer/Private/MobileShadingRenderer.cpp` | Rend dans la scene color (basse résolution) au lieu du backbuffer en LDR |
| `Renderer/Private/PostProcess/PostProcessing.cpp` | Appelle l'upscaler quand le post-process mobile est désactivé (LDR) |

**Tout est conditionné par `r.ArmASR.MobileUpscale`** : tant qu'elle vaut 0, le moteur patché se comporte
exactement comme l'original.

### Appliquer / retirer le patch

```
EnginePatch\ArmASR_EnginePatch.bat            (menu interactif)
EnginePatch\ArmASR_EnginePatch.bat status
EnginePatch\ArmASR_EnginePatch.bat dryrun     (vérifie sans rien modifier)
EnginePatch\ArmASR_EnginePatch.bat apply
EnginePatch\ArmASR_EnginePatch.bat revert     (remet les fichiers d'origine, octet pour octet)
```
ou `python EnginePatch/armasr_engine_patch.py <status|apply|revert> --engine J:\_AtlasXRInc\Unreality`.

- Les originaux sont sauvegardés dans `EnginePatch/Backups/<moteur>/` avec un manifest (SHA-256 original / patché).
- `apply` vérifie **toutes** les ancres avant d'écrire quoi que ce soit (tout ou rien).
- `revert` refuse de restaurer un fichier modifié par quelqu'un d'autre après le patch (sauf `--force`,
  qui garde alors la version courante en `<fichier>.armasr-conflict`).
- Après apply/revert : recompiler le moteur (modules Engine + Renderer).

## Installation dans le projet

1. Copier le dossier du plugin dans `<Projet>/Plugins/ArmASR` (ou lien symbolique vers ce repo).
2. Appliquer le patch moteur et recompiler Unreality.
3. Config (`Config/DefaultEngine.ini`) :

```ini
[/Script/Engine.RendererSettings]
r.AntiAliasingMethod=2            ; temporal → active l'upscaler
r.Mobile.AntiAliasing=2
r.MSAACount=1                     ; l'upscaler remplace le MSAA
r.Mobile.SupportsGen4TAA=1        ; nécessaire pour le TAA/vélocité sur mobile
r.ScreenPercentage=70             ; résolution de rendu par œil (50-80)
r.ArmASR.MobileUpscale=1          ; active le patch moteur
r.ArmASR.ShaderQuality=3          ; 3 = Performance, 4 = Ultra Performance (recommandé pour commencer sur Quest)
r.ArmASR.Sharpness=0.3            ; optionnel, compense le flou
vr.MobileMultiView=1
; Choisir l'un des deux :
r.MobileHDR=False                 ; mode LDR
; r.MobileHDR=True                ; mode HDR (post-process complet)
```

## Protocole de test

1. **Éditeur, preview mobile Vulkan + VR preview** : vérifier que `ShowFlag.VisualizeTemporalUpscaler 1`
   indique "Arm ASR" et les résolutions d'entrée/sortie attendues.
2. **Quest, LDR multiview** (config cible) : image nette dans les deux yeux, pas d'œil noir/dupliqué,
   pas de ghosting excessif en tournant la tête.
3. **Quest, HDR multiview**.
4. **Multiview désactivé** (`vr.MobileMultiView=0`) : contrôle du chemin side-by-side.
5. **Perf** : OVR Metrics Tool / RenderDoc — comparer MSAA 4x à 100 % vs ASR à 60-70 %.
   Les passes apparaissent sous `ThirdParty Arm ASR` (`ArmASR Eye0` / `ArmASR Eye1` en multiview).

`r.ArmASR.Enable 0` coupe le plugin à chaud pour comparer.

## Points à surveiller (non testés sur casque)

- **Validé** : le code C++ du plugin compile contre Unreality (Win64). Les shaders sont compilés au lancement :
  surveiller le log au premier démarrage.
- **Vélocité / SpaceWarp** : le plugin utilise la vélocité de scène UE. Le buffer de motion vectors de l'AppSpaceWarp
  n'est pas utilisé (autre format, autre résolution).
- **Foveated rendering (FDM)** : non pris en compte par l'upscaler. La densité variable réduit la qualité en périphérie
  mais ne casse pas les coordonnées.
- **Exposition en LDR** : l'upscaler lit l'eye adaptation du moteur (normalement 1.0 en LDR).
  Si l'image est trop sombre ou trop claire, essayer `r.ArmASR.AutoExposure 1` pour comparer.
- **Tonemap subpass** : le patch le désactive globalement quand `r.ArmASR.MobileUpscale=1`. En HDR, le tonemapping
  redevient une passe séparée : c'est un coût en plus, à comparer au gain de l'upscaling.
- **Changer `r.ArmASR.MobileUpscale` à chaud** est possible mais peut déclencher des compilations de PSO :
  préférer l'ini.
