# -*- coding: utf-8 -*-
"""
FAST PROMPT TEMPLATE LIBRARY – V3 MAXIMUM EXTREME EDITION
One‑click generation for the absolute filthiest, highest quality AI images.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import random

# ---------------------------------------------------------------------------
# Global quality booster – appended to EVERY prompt for photorealistic output
# ---------------------------------------------------------------------------
_MAXIMUM_QUALITY = (
    ", ultra realistic, 8k, masterpiece, award winning photography, "
    "cinematic lighting, sharp focus, intricate details, natural skin texture, "
    "subsurface scattering, ray tracing, RAW photo, photorealistic"
)

# ---------------------------------------------------------------------------
# The ultimate prompt library – categorised, labelled, ready to fire
# ---------------------------------------------------------------------------
PROMPT_TEMPLATE_CATEGORIES: list[dict] = [
    # ================================================================
    # 🩱 BASIC NUDE
    # ================================================================
    {
        "title": "🩱 Basic Nude",
        "templates": [
            (
                "Full Natural Nude",
                "Same exact pose and place as reference, completely naked, all clothes removed, "
                "huge natural tits, thick juicy ass, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Huge Soft Tits Nude",
                "Exact same pose, fully nude, remove every piece of clothing, massive soft hanging tits, "
                "thick ass, natural body, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Thick Ass Focus",
                "Same reference pose, total nudity, big hanging tits, extremely thick juicy ass, "
                "natural dark asshole, shiny skin, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Wet & Ready Nude",
                "Reference image but fully naked, same body shape, massive soft tits, thick ass "
                "glistening with moisture, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Simple Stripped",
                "Same girl, same pose, completely naked, huge tits and massive ass, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Golden Hour Nude",
                "Exact pose, fully nude, sunset backlighting, warm highlights on huge tits and thick ass, "
                "NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Mirror Selfie Nude",
                "Same girl naked, facing a full‑length mirror, reflection shows massive tits and thick ass, "
                "NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 🍑 ASS & TITS FOCUS
    # ================================================================
    {
        "title": "🍑 Ass & Tits",
        "templates": [
            (
                "Jiggly Ass Cheeks",
                "Same pose, fully nude, close‑up on thick ass cheeks jiggling, slight motion blur, "
                "natural dark asshole visible, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Tit Drop Overhead",
                "Top‑down view, same girl naked, huge soft tits hanging down, areolas visible, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Underboob & Sideboob",
                "Exact same girl, fully naked, side angle highlighting huge sagging tits, underboob curve, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Ass Spread Wide",
                "Same pose, full nudity, hands spreading massive ass cheeks apart, exposed dark butthole, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Titfuck Ready",
                "Same girl, huge tits pressed together, deep cleavage, precum dripping on chest, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 💦 WET & OILED
    # ================================================================
    {
        "title": "💦 Wet & Oiled",
        "templates": [
            (
                "Shiny Oil Full Body",
                "Exact pose, fully naked, body covered in shimmering oil, huge tits and thick ass glossy, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Soapy Shower Nude",
                "Same girl, shower water running over massive tits and thick ass, soap suds, wet skin, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Oil Dripping Ass",
                "Close‑up of thick oiled ass, oil dripping down crack, dark asshole shiny, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Poolside Wet",
                "Same girl naked, emerging from pool, water droplets on huge tits, wet hair, thick ass, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 🧘 POSE CHANGE
    # ================================================================
    {
        "title": "🧘 Pose Change",
        "templates": [
            (
                "Mating Press Legs Up",
                "Same girl, lying on her back, legs raised high and spread wide, soles of bare feet facing viewer, "
                "hands gripping ankles, tight ass fully exposed from outside, low angle, fully naked, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Face Down Ass Up",
                "Face down ass up position, same girl fully naked, huge ass pushed back, arched back, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "All Fours Deep Arch",
                "Same girl now on all fours, back arched, massive ass up high, fully naked, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Sideways Spread",
                "Lying on side, top leg raised, fingers spreading pussy, fully nude, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Chair Reverse Cowgirl",
                "Same girl naked, squatting on a chair, massive ass facing camera, thick thighs, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Wall Lean Arch",
                "Standing with hands against wall, back arched, ass pushed out, fully nude, looking back, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 👥 PARTNER & GROUP
    # ================================================================
    {
        "title": "👥 Partner & Group",
        "templates": [
            (
                "Big Black Behind",
                "Same girl fully naked, behind her muscular huge black man with massive erect penis "
                "about to fuck her, hands on hips, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Ass Hug Cock Press",
                "Exact same pose, hung black man hugging from behind, his huge cock pressed between "
                "her thick ass cheeks near tight ass, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Standing Doggy Fuck",
                "Same naked girl being fucked from behind by muscular man with enormous cock, massive ass bouncing, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Double Penetration",
                "Same girl, two muscular men, one in pussy one in tight ass, all naked, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Face Fuck POV",
                "POV, huge erect cock pushing into same girl’s mouth, tears, eye contact, fully naked, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Orgy Pile",
                "Same girl in centre of a pile of naked bodies, multiple cocks and pussies, sweat, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 🍆 FUTA & DICKGIRL
    # ================================================================
    {
        "title": "🍆 Futa & Dickgirl",
        "templates": [
            (
                "Natural Futa",
                "Same pose, futanari with huge thick veiny cock hanging naturally downward, heavy balls, "
                "massive tits, tight ass behind cock, fully naked, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Soft Hanging Futa",
                "Exact reference, futanari with massive soft hanging penis dangling, big tits and plump ass, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Futa Self Suck",
                "Same futa, bending forward to suck her own massive cock, huge tits squished, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Futa Huge Cumshot",
                "Exact same futa, erect massive cock ejaculating thick ropes of cum onto her own face and tits, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Futa Girl on Girl",
                "Same futa fucking another naked girl from behind, massive cock deep in ass, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 💩 SCAT & TOILET
    # ================================================================
    {
        "title": "💩 Scat & Toilet",
        "templates": [
            (
                "Long Thick Log",
                "Same exact pose, fully naked, pushing out long thick brown shit from her tight ass, "
                "shit coiling on ground, messy ass cheeks, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Soft Creamy Shit",
                "Naked same pose, soft creamy log slowly coming out of her ass, detailed texture, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Explosive Diarrhea",
                "Exact pose, full nudity, explosive diarrhea spraying from tight ass, brown mess everywhere, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Bent Over Shitting",
                "Same girl fully naked, bent over, shitting long rope from her dark inside butt while looking back, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Toilet Slave Mouth",
                "Same girl on all fours, mouth open as toilet, shit falling directly into her mouth, fully naked, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Scat Covered Body",
                "Same pose, fully naked, body smeared with shit, shit in hair, on face, huge tits, ass, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 💧 PISS & SQUIRTING
    # ================================================================
    {
        "title": "💧 Piss & Squirting",
        "templates": [
            (
                "Golden Shower Self",
                "Same girl, fully naked, pissing on her own huge tits and face, stream of urine, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Squirting Pussy",
                "Exact pose, full nudity, powerful squirting from pussy, clear liquid spray, ahegao, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Piss Pool Floor",
                "Same girl, squatting, piss gushing onto floor forming a puddle, thick ass visible, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Piss Drinking",
                "Same girl, mouth open catching piss stream from another person, soaking wet, fully naked, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 💦 CUM & CREAMPIE
    # ================================================================
    {
        "title": "💦 Cum & Creampie",
        "templates": [
            (
                "Full Body Cum Dump",
                "Same exact naked pose, covered in thick white cum on face, tits and ass, "
                "cum leaking near tight ass, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Creampie Overflow",
                "Fully naked same pose, massive creampie dripping from pussy, cum running over tight ass, "
                "ahegao, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Bukkake Gang",
                "Exact same girl, surrounded by faceless figures, huge cum ropes covering her entire body, "
                "face dripping, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Deep Ass Creampie",
                "Same girl, cum oozing from tight ass, gaping hole, cum puddle on floor, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 🤯 EXTREME COMBOS
    # ================================================================
    {
        "title": "🤯 Extreme Combos",
        "templates": [
            (
                "Full Fluid Explosion",
                "Same exact pose, fully naked, shitting from tight asshole, pissing and squirting "
                "at the same time, total messy orgasm, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Futa Self Fuck Mess",
                "Exact reference, futanari with massive thick cock fucking her own ass, shitting "
                "and lactating, nasty mess, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Mindless Toilet",
                "Reference turned into public cum piss shit toilet, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Lactating & Pissing",
                "Same girl, milk spraying from huge tits, pissing simultaneously, fully naked, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Scat Bukkake",
                "Same girl covered in cum and shit simultaneously, multiple streams, messy face, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 🤖 SCI‑FI / CYBORG
    # ================================================================
    {
        "title": "🤖 Sci‑Fi / Cyborg",
        "templates": [
            (
                "Cyborg Nude",
                "Same girl but as a cyborg, metal limbs, glowing neon ports, huge natural tits exposed, "
                "thick ass with metallic plating, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Alien Queen",
                "Same girl transformed into alien queen, blue skin, extra breasts, tentacles, massive ass, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Futuristic Brothel",
                "Same girl in a neon‑lit cyberpunk brothel, fully naked, holographic tattoos, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Robot Futa",
                "Futa version of same girl, robotic penis with glowing circuits, heavy metal balls, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 🧝 FANTASY
    # ================================================================
    {
        "title": "🧝 Fantasy",
        "templates": [
            (
                "Elf Queen Nude",
                "Same girl as high elf, pointed ears, ethereal glow, huge tits, thick ass, naked, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Succubus Demon",
                "Same girl as succubus, red skin, horns, tail, massive tits and ass, wings, fully naked, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Orc Breeding",
                "Same girl being bred by huge orc, naked, exaggerated proportions, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Fairy Tiny Big Tits",
                "Same girl as tiny fairy with disproportionately huge tits and ass, wings, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
    # ================================================================
    # 📸 REALISTIC / PHOTOREAL
    # ================================================================
    {
        "title": "📸 Realistic / Photoreal",
        "templates": [
            (
                "DSLR Photo Nude",
                "DSLR photograph, same girl fully naked, huge natural tits, thick ass, sharp details, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Polaroid 90s Nude",
                "Vintage polaroid, same girl naked, flash photography, big tits and ass, NSFW"
                + _MAXIMUM_QUALITY,
            ),
            (
                "Smartphone Selfie",
                "Mirror selfie, smartphone in hand, same girl naked, huge tits, thick ass, messy room, NSFW"
                + _MAXIMUM_QUALITY,
            ),
        ],
    },
]

# ---------------------------------------------------------------------------
# Keyboard builders – fully dynamic, works with any number of categories
# ---------------------------------------------------------------------------
def get_mode_keyboard() -> InlineKeyboardMarkup:
    """Start menu: single-image modes only (bulk temporarily disabled)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Single Image", callback_data="mode_single")],
        [InlineKeyboardButton("🥭 Guava 1.5 Enhanced", callback_data="mode_guava15")],
        [InlineKeyboardButton("🥭 Mango 3", callback_data="mode_mango3")],
        [InlineKeyboardButton("🎨 GPT Image 2", callback_data="mode_gpt_image")],
        [InlineKeyboardButton("🧘 Posing", callback_data="mode_posing")],
        [InlineKeyboardButton("🎬 Video", callback_data="mode_video")],
    ])



def get_bulk_done_keyboard(count: int) -> InlineKeyboardMarkup:
    """Bulk mode: confirm or cancel after adding prompts."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ Done ({count} image{'s' if count != 1 else ''})",
            callback_data="bulk_done"
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data="bulk_cancel")],
    ])


def get_prompt_mode_keyboard() -> InlineKeyboardMarkup:
    """Choose how to supply the prompt: auto, custom, or template."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤖 Auto", callback_data="prompt_auto"),
            InlineKeyboardButton("✏️ Custom", callback_data="prompt_custom"),
        ],
        [InlineKeyboardButton("📚 Templates", callback_data="prompt_templates")],
        [InlineKeyboardButton("🎲 Random Template", callback_data="prompt_random")],
    ])


def get_category_keyboard() -> InlineKeyboardMarkup:
    """Show all template categories in a 2‑column grid, plus back button."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, cat in enumerate(PROMPT_TEMPLATE_CATEGORIES):
        row.append(InlineKeyboardButton(cat["title"], callback_data=f"tplcat:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="tplback:menu")])
    return InlineKeyboardMarkup(rows)


def get_template_keyboard(cat_idx: int) -> InlineKeyboardMarkup:
    """Show all templates inside a category, with navigation."""
    cat = PROMPT_TEMPLATE_CATEGORIES[cat_idx]
    rows: list[list[InlineKeyboardButton]] = []
    for tpl_idx, (label, _) in enumerate(cat["templates"]):
        rows.append([
            InlineKeyboardButton(label, callback_data=f"tplpick:{cat_idx}:{tpl_idx}")
        ])
    rows.append([
        InlineKeyboardButton("⬅️ Categories", callback_data="tplback:cats"),
        InlineKeyboardButton("🏠 Menu", callback_data="tplback:menu"),
    ])
    return InlineKeyboardMarkup(rows)


def get_template_prompt(cat_idx: int, tpl_idx: int) -> tuple[str, str]:
    """Retrieve the (label, prompt) for a given template."""
    cat = PROMPT_TEMPLATE_CATEGORIES[cat_idx]
    label, prompt = cat["templates"][tpl_idx]
    return label, prompt


def get_random_template() -> tuple[str, str, int, int]:
    """Return a random template label, prompt, and its indices."""
    cat_idx = random.randint(0, len(PROMPT_TEMPLATE_CATEGORIES) - 1)
    cat = PROMPT_TEMPLATE_CATEGORIES[cat_idx]
    tpl_idx = random.randint(0, len(cat["templates"]) - 1)
    label, prompt = cat["templates"][tpl_idx]
    return label, prompt, cat_idx, tpl_idx


# ---------------------------------------------------------------------------
# Video prompts & related helper functions
# ---------------------------------------------------------------------------
_VIDEO_PROMPTS = {
    "kiss": (
        "A muscular black man with dark skin, short black hair, and a completely naked, shiny oily body came from back and passionately making out with intense deep kissing. He is holding her and his strong hands greedily roaming and squeezing all over her body — gripping her ass, sliding up her back, cupping her breasts, and pulling her tightly against him. Their lips are locked in a hungry, sloppy, tongue-filled kiss as he explores her curves with lustful hands. His oily muscular body glistens under the existing reference light, abs and biceps flexing while he presses his hard cock against her. Heavy breathing, sensual moaning, slow grinding hips mixed with strong passionate squeezes, erotic oil reflections on his dark skin, highly explicit, intense love and desire, close-ups, NSFW, ultra-detailed, 4K. Exact pose as reference, exact same face."
    ),
    "sex": (
        "A muscular, dark-skinned, naked man with short black hair and a fully oily body came from back and bent her down and started making sex and love with her. He has his strong hands firmly gripping her. He is passionately fucking her with powerful, rhythmic thrusts, sliding his cock deep inside her. His body is sweaty and shiny from oil, muscles flexing with every thrust. He looks at her with intense love and lust, kissing her neck and lips as he fucks her hard and deep. Sensual oily skin sliding, strong movements, intense pleasure, highly explicit, NSFW, identical lighting and background to reference throughout, 4K. Exact pose as reference, exact same face."
    ),
    "teasing": (
        "A stunning naked woman with an extremely seductive expression, looking directly at the camera with same exact face and expressions and biting her lip. She is in same position to the camera, her oily glistening skin shining under the same lighting as reference. She slowly runs her hands over her breasts, squeezing and pinching her nipples. Very explicit, slow-motion teasing movements, erotic oil reflections on her skin, heavy breathing, seductive moaning, extremely arousing and playful, ultra-detailed, NSFW, 5-second clip, close-ups, 4K. Exact pose as reference, exact same face."
    ),
}


def get_video_prompt_keyboard() -> InlineKeyboardMarkup:
    """Returns a keyboard for choosing video prompt styles or custom."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💋 Kissing", callback_data="video_prompt:kiss")],
        [InlineKeyboardButton("🔞 Sex", callback_data="video_prompt:sex")],
        [InlineKeyboardButton("😏 Teasing", callback_data="video_prompt:teasing")],
        [InlineKeyboardButton("✏️ Custom Prompt", callback_data="video_prompt:custom")],
    ])


def get_video_prompt(key: str) -> str:
    """Retrieve video prompt by key."""
    return _VIDEO_PROMPTS.get(key, "")


def get_video_prompt_texts() -> list[str]:
    """Retrieve list of all video prompt texts."""
    return list(_VIDEO_PROMPTS.values())


def get_default_video_prompt() -> str:
    """Returns the default video prompt (kiss)."""
    return _VIDEO_PROMPTS["kiss"]


def get_guava_version_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard to select image engine tier."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Guava Pro Fast (Standard)", callback_data="guava_v1")],
        [InlineKeyboardButton("🔵 Guava Pro 1.5 (Enhanced)", callback_data="guava_v2")],
    ])