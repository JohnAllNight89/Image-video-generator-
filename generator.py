import os
import json
from datetime import datetime

# Local prompt templates and brand storage
BRAND_GUIDELINES = {
    "default_style": "ultra photorealistic, hyper detailed, 8k resolution, cinematic lighting, accurate physics and textures",
    "negative": "blurry, low quality, deformed, cartoonish, text errors, artifacts, overexposed"
}

def load_or_create_brand(file="brand.json"):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    else:
        with open(file, "w") as f:
            json.dump(BRAND_GUIDELINES, f, indent=2)
        print("Created brand.json - edit this file to customize your style!")
        return BRAND_GUIDELINES

def create_image_prompt(user_request, style="photorealistic"):
    brand = load_or_create_brand()
    base = f"{user_request}, {brand['default_style']}, {style} quality"
    prompt = f"""
=== IMAGE PROMPT ===
{base}

**Variation 1:** {base} --ar 16:9 --v 6 --stylize 750 --q 2
**Variation 2:** {base} dramatic lighting, golden hour, sharp focus
**Variation 3:** {base} minimalist composition, studio lighting

**Negative Prompts:** {brand['negative']}, watermark, text mistakes
"""
    return prompt

def create_video_prompt(user_request, duration="10"):
    brand = load_or_create_brand()
    prompt = f"""
=== VIDEO PROMPT ({duration}s) ===
{user_request}, {brand['default_style']}, smooth cinematic camera movements, dynamic pacing

**Full Prompt for Kling/Runway:**
{user_request}, photorealistic motion, {duration} second clip, detailed environment, natural physics

**Negative:** {brand['negative']}
"""
    return prompt

def save_output(content, prefix="output"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}.txt"
    with open(filename, "w") as f:
        f.write(content)
    print(f"\n✅ Saved to: {filename}")

if __name__ == "__main__":
    print("=== Local Image & Video Prompt Generator (Standalone) ===")
    print("Type 'quit' to exit.\n")

    while True:
        mode = input("Image (i) or Video (v)? (or quit): ").lower()
        if mode == "quit":
            break
        request = input("Describe exactly what you want: ")

        if mode == "i":
            style = input("Style (photorealistic / logo / branding / custom): ") or "photorealistic"
            result = create_image_prompt(request, style)
        else:
            duration = input("Duration in seconds: ") or "10"
            result = create_video_prompt(request, duration)

        print("\n=== GENERATED PROMPT READY TO COPY ===\n")
        print(result)
        save_output(result)
