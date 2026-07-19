cat > generator.py << 'EOF'
import os
import json
from datetime import datetime

# Full NSFW + Photorealistic settings
BRAND_GUIDELINES = {
    "default_style": "ultra photorealistic, hyper realistic textures skin anatomy fluids, 8k resolution, cinematic volumetric lighting, accurate physics and materials, sharp focus, highly detailed",
    "negative": "blurry, low quality, deformed anatomy, cartoon, anime, text errors, artifacts, overexposed, bad proportions, censored, clothing artifacts, watermark"
}

def load_or_create_brand(file="brand.json"):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    else:
        with open(file, "w") as f:
            json.dump(BRAND_GUIDELINES, f, indent=2)
        print("✅ brand.json ready - edit for your personal style!")
        return BRAND_GUIDELINES

def create_image_prompt(user_request, style="photorealistic"):
    brand = load_or_create_brand()
    base = f"{user_request}, {brand['default_style']}, {style}"
    prompt = f"""
=== ULTRA REALISTIC / NSFW IMAGE PROMPT ===
{base}

**Variation 1 (Cinematic):** {base} dramatic sensual lighting, extreme detail, atmospheric depth --ar 16:9 --v 6 --stylize 600 --q 2
**Variation 2 (Extreme Close-up):** {base} hyper detailed skin textures, realistic anatomy, professional studio quality
**Variation 3 (Logo / Branding):** {base} clean elegant composition, perfect for logo or branding use

**Negative Prompts:** {brand['negative']}
"""
    return prompt

def create_video_prompt(user_request, duration="10"):
    brand = load_or_create_brand()
    prompt = f"""
=== ULTRA REALISTIC / NSFW VIDEO PROMPT ({duration}s) ===
{user_request}, {brand['default_style']}, smooth realistic motion, natural anatomy and fluid movement, dynamic cinematic camera

**Full Prompt for Runway / Kling / Luma:**
{user_request}, hyper realistic adult motion, detailed anatomy and textures, cinematic lighting, {duration} second clip

**Negative:** {brand['negative']}
"""
    return prompt

def save_output(content, prefix="output"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}.txt"
    with open(filename,
