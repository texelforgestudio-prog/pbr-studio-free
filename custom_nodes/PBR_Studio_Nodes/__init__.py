"""
PBR Studio Nodes v2.1  -  helper nodes for the PBR Studio All-in-One ComfyUI workflows.

Pure numpy math (wrap-around / tile-safe everywhere) with thin torch wrappers.
Install: copy this folder into  ComfyUI/custom_nodes/  and restart ComfyUI.
No extra pip packages needed (numpy + Pillow ship with ComfyUI).
"""
import os
import re
import numpy as np
from PIL import Image

try:
    import torch
except ImportError:  # only for offline unit tests
    torch = None

CATEGORY = "PBR Studio"
EPS = 1e-6


# ----------------------------------------------------------------- helpers
def _to_np(t):
    if hasattr(t, "detach"):
        t = t.detach().cpu().numpy()
    return np.asarray(t, dtype=np.float32)


def _to_t(a):
    a = np.clip(a, 0.0, 1.0).astype(np.float32)
    return torch.from_numpy(a) if torch is not None else a


def lum(img):
    return img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114


def gray3(g):
    return np.repeat(g[..., None], 3, axis=-1)


def circ_blur(a, sigma):
    """Gaussian blur with wrap-around borders (exact for tileable textures). a: (H,W) or (H,W,C)."""
    if sigma < 0.05:
        return a
    H, W = a.shape[:2]
    fy = np.fft.fftfreq(H)[:, None]
    fx = np.fft.rfftfreq(W)[None, :]
    g = np.exp(-2.0 * (np.pi ** 2) * (sigma ** 2) * (fx ** 2 + fy ** 2)).astype(np.float32)
    if a.ndim == 3:
        g = g[..., None]
    f = np.fft.rfft2(a, axes=(0, 1))
    return np.fft.irfft2(f * g, s=(H, W), axes=(0, 1)).astype(np.float32)


def norm01(a, lo=1.0, hi=99.0):
    l, h = np.percentile(a, [lo, hi])
    return np.clip((a - l) / max(h - l, EPS), 0.0, 1.0)


def resize_gray(a, H, W):
    if a.shape[:2] == (H, W):
        return a
    im = Image.fromarray(a.astype(np.float32), mode="F").resize((W, H), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(e1 - e0, EPS), 0, 1)
    return t * t * (3 - 2 * t)


# ----------------------------------------------------------------- core math
def make_seamless(a, overlap):
    """Photoshop-style offset + cross-blend. Result tiles perfectly (edges come from the shifted copy)."""
    H, W = a.shape[:2]

    def ramp(n):
        x = (np.arange(n) + 0.5) / n
        d = np.minimum(x, 1 - x) * 2.0          # 0 at the edge -> 1 at the centre
        return smoothstep(0.0, max(overlap, 1e-3), d)

    w = ramp(H)[:, None] * ramp(W)[None, :]
    if a.ndim == 3:
        w = w[..., None]
    shifted = np.roll(a, (H // 2, W // 2), axis=(0, 1))
    return a * w + shifted * (1 - w)


def periodic_component(u):
    """Moisan periodic + smooth decomposition: returns a version of u that tiles perfectly,
    with no ghosting or centre seams (only a smooth, low-frequency correction is removed)."""
    u = u.astype(np.float64)
    H, W = u.shape[:2]
    v = np.zeros_like(u)
    v[0] += u[-1] - u[0]
    v[-1] += u[0] - u[-1]
    v[:, 0] += u[:, -1] - u[:, 0]
    v[:, -1] += u[:, 0] - u[:, -1]
    q = np.arange(H)[:, None]
    r = np.arange(W)[None, :]
    den = 2.0 * np.cos(2 * np.pi * q / H) + 2.0 * np.cos(2 * np.pi * r / W) - 4.0
    den[0, 0] = 1.0
    if u.ndim == 3:
        den = den[..., None]
    S = np.fft.fft2(v, axes=(0, 1)) / den
    S[0, 0] = 0
    s = np.real(np.fft.ifft2(S, axes=(0, 1)))
    return (u - s).astype(np.float32)


def delight(img, strength, scale, tone):
    """Remove baked-in lighting: divide by the (wrap-around) low-frequency luminance, then compress shadows/highlights."""
    H, W = img.shape[:2]
    L = lum(img)
    low = circ_blur(L, scale * max(H, W))
    gain = np.clip(L.mean() / np.maximum(low, 1e-3), 0.4, 2.5)
    gain = 1.0 + (gain - 1.0) * strength
    out = img * gain[..., None]
    if tone > 0:
        L2 = lum(out)
        m = L2.mean()
        target = m + (L2 - m) * (1.0 - tone)
        ratio = np.clip(target / np.maximum(L2, 1e-3), 0.5, 2.5)
        out = out * ratio[..., None]
    return np.clip(out, 0, 1)


def _grad_mag(x):
    dx = np.roll(x, -1, 1) - np.roll(x, 1, 1)
    dy = np.roll(x, -1, 0) - np.roll(x, 1, 0)
    return np.sqrt(dx * dx + dy * dy)


def depth_agreement(g, d, flat_sigma, m):
    """How well the depth edges line up with the texture's own edges (-1..1). Low = depth is guessing (e.g. flat wood)."""
    gb = circ_blur(g, 0.004 * m) - circ_blur(g, flat_sigma)
    db = circ_blur(d, 0.004 * m) - circ_blur(d, flat_sigma)
    A = circ_blur(_grad_mag(gb), 0.01 * m)
    D = circ_blur(_grad_mag(db), 0.01 * m)
    A = (A - A.mean()) / (A.std() + EPS)
    D = (D - D.mean()) / (D.std() + EPS)
    return float((A * D).mean())


SURFACES = ["auto", "rough (stone, brick, concrete)", "flat (wood, fabric, plaster)", "polished (marble, tile, metal, glass)"]
_POLISHED = ("marble", "polished", "glazed", "ceramic", "porcelain", "glass", "chrome", "stainless", "brushed_steel", "terrazzo", "lacquer")
_FLAT = ("wood", "plank", "oak", "walnut", "pine", "parquet", "fabric", "linen", "cotton", "leather", "plaster", "paper", "carpet", "velvet", "denim")


RELIEF = {"polished": 0.25, "flat": 0.7}


def resolve_surface(surface, name):
    if not surface.startswith("auto"):
        return surface.split(" ")[0]
    n = (name or "").lower()
    if any(k in n for k in _POLISHED):
        return "polished"
    if any(k in n for k in _FLAT):
        return "flat"
    return "auto"


def build_height(albedo, depth, depth_w, detail_w, detail_scale, depth_flatten, invert, tile_depth, auto_depth=True, surface="auto"):
    H, W = albedo.shape[:2]
    m = max(H, W)
    if surface == "polished":        # v2.1: veins/patterns are colour, not relief
        depth_w, detail_w = depth_w * 0.1, detail_w * 0.35
    elif surface == "flat":
        depth_w = depth_w * 0.3
    elif surface == "rough":
        auto_depth = False
    g = lum(albedo)
    detail = g - circ_blur(g, detail_scale * m)
    detail = detail / (np.percentile(np.abs(detail), 99) + EPS)
    h = detail * detail_w
    if depth is not None and depth_w > 0:
        d = depth if depth.ndim == 2 else depth[..., :3].mean(-1)
        d = norm01(resize_gray(d, H, W), 0.5, 99.5)
        if tile_depth:
            d = periodic_component(d)                    # v2.1: seam-free tiling (old offset-blend left a centre cross)
        if auto_depth:                                   # v2.1: fade out depth that does not follow the texture
            a = depth_agreement(g, d, depth_flatten * m, m)
            depth_w = depth_w * float(np.clip((a - 0.25) / 0.20, 0.0, 1.0))
        d = d - circ_blur(d, depth_flatten * m)          # kill slopes / bulges (v2.1 default 0.04)
        d = d / (np.percentile(np.abs(d), 99) + EPS)
        h = h + d * depth_w
    h = norm01(h, 1, 99)
    return 1.0 - h if invert else h


def height_to_normal(h, strength, opengl, smooth_px):
    if smooth_px > 0:
        h = circ_blur(h, smooth_px)
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5     # rows go DOWN in an image
    ref = np.percentile(np.sqrt(dx * dx + dy * dy), 95) + 1e-8
    k = strength * 0.5 / ref                               # strength 1 -> steep areas ~ 27 degrees
    nx = -dx * k
    ny = dy * k if opengl else -dy * k                     # OpenGL: green +Y up | DirectX: green flipped
    nz = np.ones_like(nx)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    return np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5


def height_to_ao(h, radius, strength):
    m = max(h.shape[:2])
    occ = 0.0
    for r, wt in ((radius, 0.55), (radius * 3.0, 0.45)):
        cav = np.maximum(circ_blur(h, r * m) - h, 0)
        occ = occ + wt * np.clip(cav / (np.percentile(cav, 99) + EPS), 0, 1)
    return 1.0 - np.clip(occ * strength, 0, 1)


def roughness_from(albedo, base, variation, invert):
    g = norm01(circ_blur(lum(albedo), 1.0), 1, 99)
    d = (1.0 - g) if invert else g
    return np.clip(base + variation * (d - 0.5) * 2.0, 0, 1)


def metallic_from(albedo, value, mode, threshold, softness):
    if mode == "constant":
        return np.full(albedo.shape[:2], value, np.float32)
    g = norm01(lum(albedo), 1, 99)
    return (value * smoothstep(threshold - softness, threshold + softness, g)).astype(np.float32)


def pack_orm(ao, rough, metal):
    ch = lambda x: x if x.ndim == 2 else x[..., :3].mean(-1)
    return np.stack([ch(ao), ch(rough), ch(metal)], -1)


def seam_cross(image, band, softness):
    """Roll the image by half so the wrap-around seam sits in the centre, and build a soft cross-shaped mask over it."""
    H, W = image.shape[:2]
    rolled = np.roll(image, (H // 2, W // 2), axis=(0, 1))
    def axis(n):
        d = np.abs(np.arange(n) + 0.5 - n / 2.0)            # distance from the seam line
        hw = max(band * n / 2.0, 1.0)
        return 1.0 - smoothstep(hw * (1.0 - softness), hw, d)
    m = np.maximum(axis(H)[:, None], axis(W)[None, :]).astype(np.float32)
    return rolled, m


def wrap_pad(a, pad):
    pad = int(min(pad, a.shape[0] - 1, a.shape[1] - 1))
    return np.pad(a, ((pad, pad), (pad, pad), (0, 0)), mode="wrap")


def wrap_crop(a, pad, scale):
    c = int(pad * scale)
    return a[c:a.shape[0] - c, c:a.shape[1] - c] if c > 0 else a


def parse_materials(text):
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


def slug(text, maxlen=60):
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return (s[:maxlen].strip("_")) or "material"


def _out_dir():
    try:
        import folder_paths
        return folder_paths.get_output_directory()
    except Exception:
        return os.environ.get("PBR_OUTPUT_DIR", os.path.join(os.getcwd(), "output"))


def _unique_dir(base, name):
    d = os.path.join(base, name); k = 1
    while os.path.exists(os.path.join(d, name + "_BaseColor.png")):
        k += 1; d = os.path.join(base, "%s_%d" % (name, k))
    return d


# ----------------------------------------------------------------- nodes
def _batch(fn, *imgs, **kw):
    n = max(i.shape[0] for i in imgs if i is not None)
    out = []
    for b in range(n):
        args = [None if i is None else i[min(b, i.shape[0] - 1)] for i in imgs]
        out.append(fn(*args, **kw))
    return np.stack(out, 0)


class PBR_MakeSeamless:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "image": ("IMAGE",),
            "blend_overlap": ("FLOAT", {"default": 0.6, "min": 0.05, "max": 1.0, "step": 0.05}),
            "method": (["smooth (no seams)", "offset blend (classic)"], {"default": "smooth (no seams)"}),
        }}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("seamless_image",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, blend_overlap, method="smooth (no seams)"):
        if method.startswith("smooth"):
            f = lambda a: np.clip(periodic_component(a), 0.0, 1.0)
        else:
            f = lambda a: make_seamless(a, blend_overlap)
        return (_to_t(_batch(f, _to_np(image))),)


class PBR_Delight:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "image": ("IMAGE",),
            "strength": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.05}),
            "light_scale": ("FLOAT", {"default": 0.12, "min": 0.01, "max": 0.5, "step": 0.01}),
            "shadow_highlight_compress": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.05}),
        }}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("albedo",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, strength, light_scale, shadow_highlight_compress):
        return (_to_t(_batch(lambda a: delight(a, strength, light_scale, shadow_highlight_compress), _to_np(image))),)


class PBR_Height:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "albedo": ("IMAGE",),
            "depth_weight": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 3.0, "step": 0.05}),
            "detail_weight": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 3.0, "step": 0.05}),
            "detail_scale": ("FLOAT", {"default": 0.01, "min": 0.001, "max": 0.1, "step": 0.001}),
            "depth_flatten": ("FLOAT", {"default": 0.04, "min": 0.01, "max": 0.5, "step": 0.01}),
            "invert": ("BOOLEAN", {"default": False}),
            "make_depth_tileable": ("BOOLEAN", {"default": True}),
            "auto_depth": ("BOOLEAN", {"default": True, "tooltip": "Use less depth when it does not follow the texture (flat wood, fabric)."}),
            "surface": (SURFACES, {"default": "auto", "tooltip": "auto reads the material name (marble, tile, wood...) when one is connected."}),
        }, "optional": {"depth": ("IMAGE",), "material_name": ("STRING", {"forceInput": True})}}
    RETURN_TYPES = ("IMAGE", "FLOAT")
    RETURN_NAMES = ("height", "relief")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, albedo, depth_weight, detail_weight, detail_scale, depth_flatten, invert, make_depth_tileable, auto_depth=True, surface="auto", depth=None, material_name=None):
        kind = resolve_surface(surface, material_name)
        relief = RELIEF.get(kind, 1.0)
        f = lambda a, d: gray3(0.5 + (build_height(a, d, depth_weight, detail_weight, detail_scale, depth_flatten, invert, make_depth_tileable, auto_depth, kind) - 0.5) * relief)
        return (_to_t(_batch(f, _to_np(albedo), None if depth is None else _to_np(depth))), float(relief))


class PBR_Normal:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "height": ("IMAGE",),
            "strength": ("FLOAT", {"default": 1.5, "min": 0.1, "max": 8.0, "step": 0.1}),
            "format": (["OpenGL (Blender, Unity, glTF)", "DirectX (Unreal, 3ds Max)"],),
            "smooth_px": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 16.0, "step": 0.25}),
        }, "optional": {"relief": ("FLOAT", {"forceInput": True})}}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("normal",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, height, strength, format, smooth_px, relief=None):
        gl = format.startswith("OpenGL")
        if relief is not None:
            strength = strength * float(relief)
        f = lambda h: height_to_normal(h[..., :3].mean(-1), strength, gl, smooth_px)
        return (_to_t(_batch(f, _to_np(height))),)


class PBR_AmbientOcclusion:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "height": ("IMAGE",),
            "radius": ("FLOAT", {"default": 0.01, "min": 0.002, "max": 0.1, "step": 0.002}),
            "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 3.0, "step": 0.05}),
        }, "optional": {"relief": ("FLOAT", {"forceInput": True})}}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("ambient_occlusion",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, height, radius, strength, relief=None):
        if relief is not None:
            strength = strength * float(relief)
        f = lambda h: gray3(height_to_ao(h[..., :3].mean(-1), radius, strength))
        return (_to_t(_batch(f, _to_np(height))),)


class PBR_Roughness:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "albedo": ("IMAGE",),
            "base_roughness": ("FLOAT", {"default": 0.65, "min": 0.0, "max": 1.0, "step": 0.01}),
            "variation": ("FLOAT", {"default": 0.25, "min": 0.0, "max": 1.0, "step": 0.01}),
            "invert": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("roughness",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, albedo, base_roughness, variation, invert):
        return (_to_t(_batch(lambda a: gray3(roughness_from(a, base_roughness, variation, invert)), _to_np(albedo))),)


class PBR_Metallic:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "albedo": ("IMAGE",),
            "mode": (["constant", "bright_areas_only"],),
            "metallic_value": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05}),
            "threshold": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0, "step": 0.01}),
            "softness": ("FLOAT", {"default": 0.1, "min": 0.01, "max": 0.5, "step": 0.01}),
        }}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("metallic",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, albedo, mode, metallic_value, threshold, softness):
        return (_to_t(_batch(lambda a: gray3(metallic_from(a, metallic_value, mode, threshold, softness)), _to_np(albedo))),)


class PBR_PackORM:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"ambient_occlusion": ("IMAGE",), "roughness": ("IMAGE",), "metallic": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("ORM",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, ambient_occlusion, roughness, metallic):
        return (_to_t(_batch(pack_orm, _to_np(ambient_occlusion), _to_np(roughness), _to_np(metallic))),)


class PBR_TilePreview:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"image": ("IMAGE",), "tiles": ("INT", {"default": 3, "min": 2, "max": 6})}}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("tiled_preview",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, tiles):
        a = _to_np(image)
        return (_to_t(np.tile(a, (1, tiles, tiles, 1))),)


class PBR_SeamRepairPrep:
    """For Flux/any non-tiling model: shift the image by half and output a cross-shaped mask over the old seam.
    Feed image -> VAE Encode -> Set Latent Noise Mask (mask) -> KSampler (denoise ~0.7) to repair the seam."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "image": ("IMAGE",),
            "band_width": ("FLOAT", {"default": 0.22, "min": 0.05, "max": 0.6, "step": 0.01}),
            "softness": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
        }}
    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("shifted_image", "seam_mask")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, band_width, softness):
        a = _to_np(image); imgs, masks = [], []
        for b in range(a.shape[0]):
            r, m = seam_cross(a[b], band_width, softness); imgs.append(r); masks.append(m)
        return (_to_t(np.stack(imgs)), _to_t(np.stack(masks)))


class PBR_WrapPad:
    """Pad a tileable image with its own wrapped-around edges (use before a model upscaler so the tiling survives)."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"image": ("IMAGE",), "pad_px": ("INT", {"default": 32, "min": 4, "max": 256, "step": 4})}}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("padded",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, pad_px):
        return (_to_t(_batch(lambda a: wrap_pad(a, pad_px), _to_np(image))),)


class PBR_WrapCrop:
    """Remove the wrap padding after upscaling. scale = the upscaler's factor (4 for RealESRGAN x4plus)."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"image": ("IMAGE",), "pad_px": ("INT", {"default": 32, "min": 4, "max": 256, "step": 4}),
                             "scale": ("INT", {"default": 4, "min": 1, "max": 8})}}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("cropped",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, pad_px, scale):
        return (_to_t(_batch(lambda a: wrap_crop(a, pad_px, scale), _to_np(image))),)


def resize_long_side(a, long_side, tile_safe):
    """Resize so the longest side = long_side, keeping the aspect ratio. tile_safe: wrap-pad first so edges stay seamless."""
    H, W = a.shape[:2]
    s = long_side / float(max(H, W))
    nH, nW = max(1, int(round(H * s))), max(1, int(round(W * s)))
    if (nH, nW) == (H, W):
        return a
    pad = 8 if tile_safe else 0
    src = np.pad(a, ((pad, pad), (pad, pad), (0, 0)), mode="wrap") if pad else a
    pH, pW = int(round(pad * nH / H)), int(round(pad * nW / W))
    tH, tW = nH + 2 * pH, nW + 2 * pW
    chans = [np.asarray(Image.fromarray(src[..., c].astype(np.float32), mode="F").resize((tW, tH), Image.LANCZOS))
             for c in range(src.shape[2])]
    out = np.stack(chans, -1)
    return np.clip(out[pH:pH + nH, pW:pW + nW], 0.0, 1.0).astype(np.float32)


class PBR_ResizeLongSide:
    """v2.1: resize keeping the aspect ratio (longest side = long_side). Tile-safe. Replaces stretch-to-square."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"image": ("IMAGE",),
                             "long_side": ("INT", {"default": 4096, "min": 256, "max": 8192, "step": 64}),
                             "tile_safe": ("BOOLEAN", {"default": True})}}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, long_side, tile_safe):
        return (_to_t(_batch(lambda a: resize_long_side(a, long_side, tile_safe), _to_np(image))),)


class PBR_PromptPicker:
    """Batch mode: one material per line. Each queued run uses the next line (seed = line number, set to 'increment').
    Set the Queue 'batch count' to the number of lines."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "materials": ("STRING", {"multiline": True, "default": "weathered red brick wall\nmossy cobblestone pavement\ndark oak wood planks"}),
            "prefix": ("STRING", {"multiline": True, "default": "seamless tileable texture of "}),
            "suffix": ("STRING", {"multiline": True, "default": ", top-down flat orthographic view, flat even diffuse lighting, no shadows, no highlights, albedo base color texture, highly detailed, sharp focus, 4k"}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
        }}
    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("prompt", "name", "total")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, materials, prefix, suffix, seed):
        items = parse_materials(materials)
        if not items:
            raise ValueError("PBR Studio Prompt Picker: the 'materials' list is empty. Write one material per line.")
        line = items[int(seed) % len(items)]
        return (prefix + line + suffix, slug(line), len(items))


class PBR_SaveMaterial:
    """Saves a whole material set into  output/<folder>/<name>/  with engine-friendly names (+ optional 16-bit height)."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "albedo": ("IMAGE",), "normal": ("IMAGE",), "height": ("IMAGE",), "ambient_occlusion": ("IMAGE",),
            "roughness": ("IMAGE",), "metallic": ("IMAGE",), "orm": ("IMAGE",),
            "output_folder": ("STRING", {"default": "PBR_Batch"}),
            "material_name": ("STRING", {"default": "material"}),
            "height_16bit": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = ()
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    def run(self, albedo, normal, height, ambient_occlusion, roughness, metallic, orm, output_folder, material_name, height_16bit):
        base_folder = "/".join(p for p in re.split(r"[\\/]+", output_folder) if p and p != "..") or "PBR_Batch"
        name = slug(material_name)
        base = os.path.join(_out_dir(), *base_folder.split("/"))
        folder = _unique_dir(base, name)
        os.makedirs(folder, exist_ok=True)
        final = os.path.basename(folder)
        maps = [("BaseColor", albedo), ("Normal", normal), ("Height", height), ("AO", ambient_occlusion),
                ("Roughness", roughness), ("Metallic", metallic), ("ORM", orm)]
        count = _to_np(albedo).shape[0]
        for label, t in maps:
            arr = _to_np(t)
            for b in range(arr.shape[0]):
                suffix = "" if count == 1 else "_%d" % (b + 1)
                path = os.path.join(folder, "%s_%s%s.png" % (final, label, suffix))
                a = np.clip(arr[b], 0, 1)
                if label == "Height" and height_16bit:
                    g = (a[..., :3].mean(-1) * 65535.0 + 0.5).astype(np.uint16)
                    Image.fromarray(g).save(path)
                else:
                    Image.fromarray((a * 255.0 + 0.5).astype(np.uint8)).save(path)
        sub = "/".join(base_folder.split("/") + [final])
        return {"ui": {"images": [{"filename": "%s_BaseColor%s.png" % (final, "" if count == 1 else "_1"), "subfolder": sub, "type": "output"}]}}


NODE_CLASS_MAPPINGS = {
    "PBR_MakeSeamless": PBR_MakeSeamless, "PBR_Delight": PBR_Delight, "PBR_Height": PBR_Height,
    "PBR_Normal": PBR_Normal, "PBR_AmbientOcclusion": PBR_AmbientOcclusion, "PBR_Roughness": PBR_Roughness,
    "PBR_Metallic": PBR_Metallic, "PBR_PackORM": PBR_PackORM, "PBR_TilePreview": PBR_TilePreview,
    "PBR_SeamRepairPrep": PBR_SeamRepairPrep, "PBR_WrapPad": PBR_WrapPad, "PBR_WrapCrop": PBR_WrapCrop,
    "PBR_PromptPicker": PBR_PromptPicker, "PBR_SaveMaterial": PBR_SaveMaterial,
    "PBR_ResizeLongSide": PBR_ResizeLongSide,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PBR_MakeSeamless": "PBR Studio: Make Seamless (photo)", "PBR_Delight": "PBR Studio: De-light (Albedo)",
    "PBR_Height": "PBR Studio: Height Map", "PBR_Normal": "PBR Studio: Normal Map",
    "PBR_AmbientOcclusion": "PBR Studio: Ambient Occlusion", "PBR_Roughness": "PBR Studio: Roughness",
    "PBR_Metallic": "PBR Studio: Metallic", "PBR_PackORM": "PBR Studio: Pack ORM",
    "PBR_TilePreview": "PBR Studio: Tile Preview",
    "PBR_SeamRepairPrep": "PBR Studio: Seam Repair Prep (shift + mask)", "PBR_WrapPad": "PBR Studio: Wrap Pad (before upscale)",
    "PBR_WrapCrop": "PBR Studio: Wrap Crop (after upscale)", "PBR_PromptPicker": "PBR Studio: Batch Prompt Picker",
    "PBR_SaveMaterial": "PBR Studio: Save Material Set",
    "PBR_ResizeLongSide": "PBR Studio: Resize (keep aspect, tile-safe)",
}
