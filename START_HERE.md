# PBR STUDIO v2.1 (FREE: workflow 01)

> This free download contains workflow **01 Text to PBR**. Photo to PBR (02), Batch (05) and the 4K Upgrade (04) are in the full PBR Studio bundle on Gumroad.

Turn a text prompt or a photo into a complete, tileable PBR material inside ComfyUI:
BaseColor, Normal (OpenGL or DirectX), 16-bit Height, AO, Roughness, Metallic and a packed ORM map.
One workflow, one node pack, one installer. Runs on an 8 GB GPU.

---

## 1. The lineup

| # | Workflow file | What it does | Needs | VRAM |
|---|---|---|---|---|
| 01 | `01_PBR_Text_SDXL_Standard.json` | Text prompt to a tileable texture, then all PBR maps | SDXL, Depth Anything, Seamless Tiling | 8 GB |
| 02 | `02_PBR_Photo_Standard.json` | Your surface photo, made seamless and de-lit, then all PBR maps | Depth Anything | 4-6 GB |
| 04 | `04_PBR_Upgrade_to_4K.json` | Any albedo to a tile-safe 4K (or 2K) PBR set, same aspect ratio as the input | RealESRGAN, Depth Anything | 6-8 GB |
| 05 | `05_PBR_Batch_SDXL.json` | A list of materials, one full set saved per material | same as 01 | 8 GB |

(Numbers 03 and 06 are reserved for a future version.)

**Which one should I use?**
- One specific material, or a regular pattern (bricks, planks, tiles): **01**.
- Copying a real surface you photographed: **02**.
- You need it at 4K: make the albedo with 01, 02 or 05, then run **04**.
- Ten, twenty or fifty materials in one go: **05**.

---

## 2. First 5 minutes: test your install

Open `examples/TEST_PROMPTS.md`. It has:
- 14 tested prompts for 01.

If these give you good maps, your install is correct. Then use your own materials.

---

## 3. Install

**Easy way:** `python install_pbr_studio.py --comfy "C:\path\to\ComfyUI"`
It copies the node pack and the workflow (they appear under Workflows > PBR_Studio) and clones the two other custom nodes.
Then follow the "next steps" it prints.

**ComfyUI Desktop users:** your ComfyUI folder is usually
`C:\Users\<you>\AppData\Local\Comfy-Desktop\ComfyUI-Installs\<instance>\ComfyUI`. You can also install the two custom nodes through the Manager instead of git.

**Manual way:**
1. Copy `custom_nodes/PBR_Studio_Nodes` into `ComfyUI/custom_nodes/`.
2. `git clone https://github.com/kijai/ComfyUI-DepthAnythingV2` into `custom_nodes`, then `pip install -r requirements.txt` with ComfyUI's own Python.
3. `git clone https://github.com/spinagon/ComfyUI-seamless-tiling` into `custom_nodes` (needed by 01 and 05).
4. Download the models below. Restart ComfyUI and press R.

### Model downloads

| Model | Used by | Put it in | Link |
|---|---|---|---|
| Depth Anything V2 Small (99 MB, auto-downloads on first run) | all | `models/depthanything/` | https://huggingface.co/Kijai/DepthAnythingV2-safetensors/resolve/main/depth_anything_v2_vits_fp32.safetensors |
| SDXL base 1.0 (6.9 GB) | 01, 05 | `models/checkpoints/` | https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors |
| RealESRGAN x4plus (67 MB) | 04 | `models/upscale_models/` | https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth |

The file must be named exactly `sd_xl_base_1.0.safetensors`. If your browser saved it as `sd_xl_base_1.0 (1).safetensors` or similar, rename it, or pick your file in the *Load Checkpoint* node.

---

## 4. How it works

1. **Tileable image.** SDXL tiles through circular padding in the model and the VAE. Photos are made seamless with a "smooth" periodic decomposition (no ghosting, no centre cross).
2. **De-light.** Removes large-scale light and compresses shadows and highlights, giving the BaseColor.
3. **Depth.** Depth Anything V2 estimates the surface shape. It is wrap-padded so the edges tile.
4. **Height.** Depth (big shapes) plus albedo detail (fine detail). The **surface** setting in the Height node controls relief:
   - `rough`: stone, brick, concrete, soil (full relief)
   - `flat`: wood, fabric, plaster (gentle relief)
   - `polished`: marble, glazed tile, chrome (almost flat, no fake cracks)
   - `auto`: reads the material name in batch mode, otherwise fades out depth that doesn't match the texture.
5. **Maps.** Normal (OpenGL or DirectX), AO, Roughness and Metallic are made from the height and albedo. ORM packs R = AO, G = Roughness, B = Metallic.
6. **4K (04).** Wrap-pad, RealESRGAN x4, wrap-crop, resize on the long side. Tiling and aspect ratio are kept.
7. **Saving.** Each material goes into its own folder with engine-ready names. Height is saved as 16-bit PNG. Re-runs get `_2`, `_3`, so nothing is overwritten.

### Output folders
- 01, 02: `ComfyUI/output/PBR_Material/<name>/`
- 05: `ComfyUI/output/PBR_Batch/<material>/`
- 04: `ComfyUI/output/PBR_4K/<name>/`

### Import into your engine
- **Blender:** BaseColor to Base Color (sRGB). Normal through a Normal Map node, Non-Color, OpenGL. Roughness and Metallic Non-Color. Height to a Displacement node (scale around 0.03-0.05).
- **Unreal:** Normal format DirectX. ORM with sRGB off, compression Masks.
- **3ds Max / V-Ray / Corona:** DirectX normal, other maps as non-color.
- **Unity URP / glTF:** OpenGL normal. (Unity HDRP uses a different mask layout than ORM.)

---

## 5. Honest limits

- Height, AO and roughness are **estimates from an image**, not scanned data. Great for ArchViz, games, product renders and previews. Not "physically measured".
- De-lighting is a heuristic. Hard baked shadows in a photo can survive.
- SDXL base does not do every material well. Leather, terracotta roof tiles and clay ground looked fake in our tests: use a photo (02) for those.
- Photo mode works best on random surfaces (soil, concrete, plaster, gravel). On strict patterns the rows may not line up at the tile edge.
- The 4K upscaler smooths a little. Fine detail comes from the albedo and height blend.

## 6. Tested on

- Windows 11, ComfyUI Desktop (core 0.44), RTX 5060 Laptop 8 GB, 32 GB RAM.
- All 4 workflows run end to end. Batch of 5 and batch of 12 materials completed. Maps rendered in Blender 5 (Cycles) with no visible seams on a 2x2 tiled wall.
- Roughly 20-25 s per material for 01/05 on that GPU.

## 7. Licenses

- **PBR Studio nodes and workflows:** for use in your own personal and commercial projects. The textures you make are yours to use. Do not resell or redistribute the workflows or node pack.
- **Sample images in `examples/`:** generated by the author with SDXL. Use them for testing and in your projects, but do not resell them as a texture pack.
- **Third-party parts are not included, you download them yourself:** SDXL base 1.0 (CreativeML Open RAIL++-M, commercial use of outputs allowed), Depth Anything V2 Small (Apache 2.0), RealESRGAN (BSD-3), ComfyUI-seamless-tiling (GPL-3.0), ComfyUI-DepthAnythingV2. Check each license yourself.

## 8. Help

Red nodes: install the missing custom nodes, restart ComfyUI, press R.
Seam visible: new seed (01/05) or check the photo is straight-on (02).
Normal looks inverted: switch OpenGL / DirectX in the Normal Map node.
Still stuck: open a GitHub issue with a screenshot of the error.
