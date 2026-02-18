# Loupe - A Location Photo Curator

Automatically fetch and curate high-quality, diverse photos for a list of locations using Google Places API and local AI vision models.

**The problem:** You have a list of places (restaurants, trails, landmarks) and need representative photos for each. Google Places has photos, but they're unranked and often include food close-ups, selfies, or duplicates.

**The solution:** Loupe downloads candidate photos, then uses a local vision model to select the best 3 that are high-quality, representative of the place, and visually diverse (e.g., exterior, interior, scenic view — not three shots of the same angle).

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/danmunz/loupe.git
cd loupe

# 2. Install dependencies
pip install -r requirements.txt

# 3. Make sure Ollama is running with a vision model
ollama pull llava:13b

# 4. Run it
python location_photo_curator.py locations.csv ./output --api-key YOUR_GOOGLE_KEY
```

## Requirements

- Python 3.10+
- [Ollama](https://ollama.ai) with a vision-capable model
- Google Places API key

## Setup

### 1. Install Ollama

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Start the server
ollama serve
```

### 2. Choose and Pull a Vision Model

Any Ollama model with vision capabilities will work. Options from fastest to most capable:

| Model | Size | Speed | Quality | Command |
|-------|------|-------|---------|---------|
| LLaVA 7B | 4.7 GB | ⚡ Fast | Good | `ollama pull llava:7b` |
| LLaVA 13B | 8 GB | Medium | Better | `ollama pull llava:13b` |
| Qwen2.5-VL 7B | 5.4 GB | Medium | Better | `ollama pull qwen2.5-vl:7b-instruct` |

For Macs with 16GB+ RAM, `llava:13b` or `qwen2.5-vl` are recommended. For 8GB, stick with `llava:7b`.

**Using a custom/community model:**

If you pull a model from a community source (e.g., `ingu627/Qwen2.5-VL-7B-Instruct-Q5_K_M`), use the full name:

```bash
ollama pull ingu627/Qwen2.5-VL-7B-Instruct-Q5_K_M
python location_photo_curator.py locations.csv ./output \
  --model "ingu627/Qwen2.5-VL-7B-Instruct-Q5_K_M:latest" \
  --api-key YOUR_KEY
```

To see what models you have installed:
```bash
ollama list
```

### 3. Get a Google Places API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Navigate to **APIs & Services → Library**
4. Search for and enable **Places API** (the original, not "Places API (New)")
5. Go to **APIs & Services → Credentials**
6. Click **Create Credentials → API Key**
7. (Recommended) Restrict the key to Places API only

**Cost:** Google gives you $200/month free credit. Each location uses ~2-12 API calls depending on photos available. A 50-location run typically costs $1-3.

You can provide the key via command line or environment variable:
```bash
# Option A: Command line
python location_photo_curator.py locations.csv ./output --api-key YOUR_KEY

# Option B: Environment variable
export GOOGLE_PLACES_API_KEY="YOUR_KEY"
python location_photo_curator.py locations.csv ./output
```

## Usage

### Basic Usage

```bash
python location_photo_curator.py <csv_file> <output_dir> --api-key <key>
```

### Input CSV Format

Your CSV needs a column named `Location`:

```csv
Location
Muir Woods National Monument
The French Laundry
Yosemite Valley
Bixby Creek Bridge
```

### Output Structure

```
output/
├── curated/                      # ✨ Your final photos
│   ├── Muir_Woods_National_Monument/
│   │   ├── 01_landscape.jpg
│   │   ├── 02_trail.jpg
│   │   └── 03_exterior.jpg
│   └── Yosemite_Valley/
│       ├── 01_scenic_view.jpg
│       ├── 02_landscape.jpg
│       └── 03_exterior.jpg
├── all_downloads/                # Every photo downloaded
│   └── ...
└── reports/
    ├── summary.json              # Overall statistics
    └── Muir_Woods_analysis.json  # Per-location AI reasoning
```

### Command Line Options

```
python location_photo_curator.py --help

positional arguments:
  csv_file              CSV file with 'Location' column
  output_dir            Output directory for photos

options:
  --api-key KEY         Google Places API key (or set GOOGLE_PLACES_API_KEY)
  --model MODEL         Ollama model to use (default: llava:13b)
```

## Example Output

```
============================================================
📍 Cook's Meadow Loop
============================================================
  Found 10 images
  [1/10] Analyzing photo_01.jpg... score=7, cat=scenic_view
  [2/10] Analyzing photo_02.jpg... score=8, cat=scenic_view
  [3/10] Analyzing photo_03.jpg... score=6, cat=landscape
  [4/10] Analyzing photo_04.jpg... score=7, cat=scenic_view
  [5/10] Analyzing photo_05.jpg... score=7, cat=scenic_view
  [6/10] Analyzing photo_06.jpg... score=7, cat=scenic_view
  [7/10] Analyzing photo_07.jpg... score=7, cat=scenic_view
  [8/10] Analyzing photo_08.jpg... score=7, cat=scenic_view
  [9/10] Analyzing photo_09.jpg... score=8, cat=scenic_view
  [10/10] Analyzing photo_10.jpg... score=7, cat=scenic_view

  ✓ Selected 3 photos:
    1. photo_02.jpg
       Score: 8/10 | Category: scenic_view
       A vibrant view of Cook's Meadow Loop with diverse flora, a walking path curving through the landscape.
    2. photo_03.jpg
       Score: 6/10 | Category: landscape
       A wide shot of a meadow with scattered trees, overcast skies, and distant mountains.
    3. photo_09.jpg
       Score: 8/10 | Category: scenic_view
       A panoramic view of a meadow with trees and a visible path winding through it.
```

## Configuration

To customize behavior, edit the constants at the top of `location_photo_curator.py`:

### Photo Counts

```python
# How many photos to download per location (candidates for AI to review)
MAX_PHOTOS_TO_DOWNLOAD = 10

# How many winners to select per location
PHOTOS_TO_SELECT = 3
```

**Trade-offs:**
- More downloads = better selection pool, but slower and more API calls
- Fewer downloads = faster, but might miss good shots
- Recommended: 10 downloads → 3 selected works well for most cases

### Photo Size

```python
# Maximum dimension in pixels (Google allows up to 1600)
PHOTO_MAX_WIDTH = 1200
```

Larger = better quality but bigger files. 1200px is a good balance.

### Rate Limiting

```python
# Seconds between API requests
REQUEST_DELAY = 0.25
```

Increase if you hit rate limits. Decrease if you're impatient (but be careful).

### Geographic Bias

The script defaults to searching with a California bias. To change this, edit the `search_place` function:

```python
params = {
    "key": api_key,
    "query": f"{name} California",  # Change region here
    "location": "37.5,-120",         # Lat/lng center point
    "radius": 500000,                # Radius in meters
}
```

For international locations, remove the region suffix and adjust coordinates:
```python
params = {
    "key": api_key,
    "query": name,  # No region suffix
    # Remove location/radius for worldwide search
}
```

## Customizing the AI Selection Criteria

The AI prompt determines what makes a "good" photo. Edit the `analyze_photo` function to change criteria:

```python
prompt = f"""You are evaluating a photo that should represent "{location_name}" for a travel photo collection.

Analyze this image and respond with ONLY a JSON object (no other text):

{{
  "quality_score": <1-10 rating for image quality, composition, lighting>,
  "category": "<one of: exterior, interior, landscape, scenic_view, trail, signage, detail, food, people, other>",
  "description": "<brief description of what's shown>",
  "represents_place": <true if it shows the actual location/setting, false if it's just food, selfies, or generic content>,
  "reasoning": "<why this would or wouldn't be a good representative photo>"
}}

Be strict: food close-ups, selfies, and generic shots score low. Exteriors, scenic views, interiors showing ambiance, and landscape shots score high."""
```

### Example Customizations

**For restaurants (include food photos):**
```python
"category": "<one of: exterior, interior, dining_room, dish, bar, patio, other>",
# ...
"Be balanced: include one exterior, one interior ambiance shot, and one signature dish."
```

**For hiking trails (prioritize views):**
```python
"category": "<one of: trailhead, trail_path, scenic_view, summit, wildlife, signage, other>",
# ...
"Prioritize dramatic landscape views and trail conditions. Avoid photos that are just trees."
```

**For architecture (focus on building details):**
```python
"category": "<one of: facade, entrance, interior, detail, aerial, context, other>",
# ...
"Prioritize architectural details, interesting angles, and good lighting. Include both wide establishing shots and interesting details."
```

### Changing the Diversity Algorithm

The `select_diverse_photos` function picks winners. By default it:
1. Filters out photos where `represents_place` is False
2. Picks the highest-scoring photo from each unique category
3. Fills remaining slots with highest-scoring photos

To change this logic, edit the function:

```python
def select_diverse_photos(analyses: list[PhotoAnalysis], count: int = 3) -> list[PhotoAnalysis]:
    # Example: Require minimum quality score
    qualified = [a for a in analyses if a.quality_score >= 6]
    
    # Example: Prioritize certain categories
    priority_categories = ["exterior", "scenic_view", "landscape"]
    
    # ... your custom logic
```

## Troubleshooting

### "Model not found" error

Check installed models and use the exact name:
```bash
ollama list
# Use the full name from the NAME column, including any prefix
```

### "Ollama not running" error

Start the Ollama server:
```bash
ollama serve
```

### "externally-managed-environment" error (pip)

On newer macOS/Linux:
```bash
pip install requests --break-system-packages
```

Or use a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install requests
```

### Slow performance

- Use a smaller/faster model (`llava:7b` vs `llava:13b`)
- Reduce `MAX_PHOTOS_TO_DOWNLOAD`
- Ensure Ollama is using GPU (check with `ollama ps`)

### Wrong locations found

The script adds "California" to searches by default. If your locations are elsewhere:
1. Edit the `search_place` function (see Geographic Bias section)
2. Or make your CSV more specific: "The French Laundry, Yountville, CA"

### API quota exceeded

- Increase `REQUEST_DELAY`
- Check your [Google Cloud quotas](https://console.cloud.google.com/apis/api/places-backend.googleapis.com/quotas)
- The free tier ($200/month) is generous; you likely have a per-minute limit

## How It Works

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│   CSV of    │────▶│  Google Places  │────▶│   Download   │────▶│  Local AI   │
│  Locations  │     │  Text Search    │     │   Photos     │     │  Analysis   │
└─────────────┘     └─────────────────┘     └──────────────┘     └─────────────┘
                            │                      │                     │
                            ▼                      ▼                     ▼
                      Get place_id           10 JPGs per         Score, categorize,
                      & photo refs            location           assess relevance
                                                                        │
                                                                        ▼
                                                               ┌─────────────┐
                                                               │   Select    │
                                                               │  diverse 3  │
                                                               └─────────────┘
```

1. **Search**: Each location name is searched via Google Places Text Search API
2. **Fetch**: Place Details API returns photo references (not actual images)
3. **Download**: Photo references are exchanged for actual JPGs
4. **Analyze**: Each photo is sent to the local vision model with a structured prompt
5. **Select**: Top 3 diverse photos are chosen based on quality score and category variety

## License

MIT

## Contributing

PRs welcome! Some ideas:
- [ ] Support for other photo sources (Unsplash, Yelp, etc.)
- [ ] Web UI for reviewing/overriding AI selections
- [ ] Batch processing with resume capability
- [ ] Support for non-English locations
