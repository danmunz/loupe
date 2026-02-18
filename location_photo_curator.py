#!/usr/bin/env python3
"""
Location Photo Curator
======================

End-to-end pipeline: CSV of locations → 3 curated photos per location

Workflow:
1. Read CSV with location names
2. Search Google Places for each location
3. Download up to 10 photos per location to temp folder
4. Use local vision model (Qwen2.5-VL via Ollama) to analyze each photo
5. Select 3 diverse, high-quality photos per location
6. Copy winners to output folder

Requirements:
- Google Places API key
- Ollama running with a vision model (e.g., ingu627/Qwen2.5-VL-7B-Instruct-Q5_K_M)
- pip install requests

Usage:
  python location_photo_curator.py locations.csv ./output --api-key YOUR_KEY

Folder structure created:
  output/
  ├── curated/                    # Final picks (what you want)
  │   ├── Muir_Woods/
  │   │   ├── 01_exterior.jpg
  │   │   ├── 02_trail.jpg
  │   │   └── 03_scenic.jpg
  │   └── ...
  ├── all_downloads/              # Every photo downloaded (for manual review)
  │   ├── Muir_Woods/
  │   │   ├── photo_01.jpg
  │   │   ├── photo_02.jpg
  │   │   └── ...
  │   └── ...
  └── reports/
      ├── summary.json            # Overall stats
      └── Muir_Woods_analysis.json # Per-location AI reasoning
"""

import argparse
import csv
import json
import base64
import os
import re
import shutil
import sys
import time
import requests
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional


# === CONFIGURATION ===
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llava:13b"

# Google Places settings
PHOTO_MAX_WIDTH = 1200
MAX_PHOTOS_TO_DOWNLOAD = 10
PHOTOS_TO_SELECT = 3

# Rate limiting
REQUEST_DELAY = 0.25


# === DATA STRUCTURES ===
@dataclass
class PhotoAnalysis:
    filename: str
    quality_score: int
    category: str
    description: str
    represents_place: bool
    reasoning: str


@dataclass 
class LocationResult:
    name: str
    google_name: str
    google_address: str
    photos_downloaded: int
    photos_analyzed: int
    photos_selected: list
    status: str  # "success", "not_found", "no_photos", "analysis_failed"


# === UTILITIES ===
def sanitize_folder_name(name: str) -> str:
    """Convert location name to valid folder name."""
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized[:80]


def encode_image(image_path: Path) -> str:
    """Encode image to base64."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# === GOOGLE PLACES API ===
def search_place(name: str, api_key: str) -> Optional[dict]:
    """Search for a place by name."""
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "key": api_key,
        "query": f"{name} California",
        "location": "37.5,-120",
        "radius": 500000,
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("status") == "OK" and data.get("results"):
            return data["results"][0]
        return None
    except requests.RequestException as e:
        print(f"    ⚠ Search error: {e}")
        return None


def get_place_details(place_id: str, api_key: str) -> Optional[dict]:
    """Get place details including photo references."""
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "key": api_key,
        "place_id": place_id,
        "fields": "name,formatted_address,photos",
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("status") == "OK":
            return data.get("result")
        return None
    except requests.RequestException as e:
        print(f"    ⚠ Details error: {e}")
        return None


def download_photo(photo_reference: str, output_path: Path, api_key: str) -> bool:
    """Download a photo using its reference."""
    url = "https://maps.googleapis.com/maps/api/place/photo"
    params = {
        "key": api_key,
        "photo_reference": photo_reference,
        "maxwidth": PHOTO_MAX_WIDTH,
    }
    
    try:
        resp = requests.get(url, params=params, timeout=60, stream=True)
        resp.raise_for_status()
        
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except requests.RequestException:
        return False


# === OLLAMA VISION ANALYSIS ===
def check_ollama() -> bool:
    """Verify Ollama is running and model is available."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        if not any(OLLAMA_MODEL.replace(":latest", "") in m for m in models):
            print(f"ERROR: Model {OLLAMA_MODEL} not found in Ollama.")
            print(f"Available models: {models}")
            print(f"Install with: ollama pull {OLLAMA_MODEL}")
            return False
        return True
    except requests.RequestException:
        print("ERROR: Ollama not running. Start with: ollama serve")
        return False


def analyze_photo(image_path: Path, location_name: str) -> Optional[PhotoAnalysis]:
    """Send image to vision model for analysis."""
    
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

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "images": [encode_image(image_path)],
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        
        result = response.json()
        text = result.get("response", "").strip()
        
        # Extract JSON from response
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            json_str = text[json_start:json_end]
            data = json.loads(json_str)
            
            return PhotoAnalysis(
                filename=image_path.name,
                quality_score=int(data.get("quality_score", 5)),
                category=data.get("category", "other"),
                description=data.get("description", ""),
                represents_place=bool(data.get("represents_place", False)),
                reasoning=data.get("reasoning", ""),
            )
    except (json.JSONDecodeError, requests.RequestException, KeyError):
        pass
    
    return None


def select_diverse_photos(analyses: list[PhotoAnalysis], count: int = 3) -> list[PhotoAnalysis]:
    """Select top photos that are diverse in category and high quality."""
    
    # Filter to only photos that represent the place
    representative = [a for a in analyses if a.represents_place]
    if len(representative) < count:
        representative = analyses
    
    # Sort by quality
    sorted_photos = sorted(representative, key=lambda x: x.quality_score, reverse=True)
    
    selected = []
    used_categories = set()
    
    # First pass: pick highest quality from each unique category
    for photo in sorted_photos:
        if len(selected) >= count:
            break
        if photo.category not in used_categories:
            selected.append(photo)
            used_categories.add(photo.category)
    
    # Second pass: fill with highest quality remaining
    for photo in sorted_photos:
        if len(selected) >= count:
            break
        if photo not in selected:
            selected.append(photo)
    
    return selected


# === MAIN PIPELINE ===
def process_location(
    location_name: str,
    api_key: str,
    downloads_dir: Path,
    curated_dir: Path,
    reports_dir: Path,
) -> LocationResult:
    """Full pipeline for one location."""
    
    folder_name = sanitize_folder_name(location_name)
    download_folder = downloads_dir / folder_name
    curated_folder = curated_dir / folder_name
    
    print(f"\n{'─'*60}")
    print(f"📍 {location_name}")
    print(f"{'─'*60}")
    
    # Step 1: Search Google Places
    print("  🔍 Searching Google Places...", end=" ", flush=True)
    time.sleep(REQUEST_DELAY)
    search_result = search_place(location_name, api_key)
    
    if not search_result:
        print("not found")
        return LocationResult(
            name=location_name, google_name="", google_address="",
            photos_downloaded=0, photos_analyzed=0, photos_selected=[],
            status="not_found"
        )
    
    place_id = search_result["place_id"]
    google_name = search_result.get("name", "")
    google_address = search_result.get("formatted_address", "")
    print(f"found")
    print(f"     → {google_name}")
    
    # Step 2: Get photo references
    time.sleep(REQUEST_DELAY)
    details = get_place_details(place_id, api_key)
    
    if not details or not details.get("photos"):
        print("  📷 No photos available")
        return LocationResult(
            name=location_name, google_name=google_name, google_address=google_address,
            photos_downloaded=0, photos_analyzed=0, photos_selected=[],
            status="no_photos"
        )
    
    photos = details["photos"][:MAX_PHOTOS_TO_DOWNLOAD]
    print(f"  📷 Downloading {len(photos)} photos...", end=" ", flush=True)
    
    # Step 3: Download photos
    download_folder.mkdir(parents=True, exist_ok=True)
    downloaded = []
    
    for i, photo in enumerate(photos, 1):
        photo_ref = photo.get("photo_reference")
        if not photo_ref:
            continue
        
        output_path = download_folder / f"photo_{i:02d}.jpg"
        time.sleep(REQUEST_DELAY)
        
        if download_photo(photo_ref, output_path, api_key):
            downloaded.append(output_path)
    
    print(f"{len(downloaded)} downloaded")
    
    if not downloaded:
        return LocationResult(
            name=location_name, google_name=google_name, google_address=google_address,
            photos_downloaded=0, photos_analyzed=0, photos_selected=[],
            status="no_photos"
        )
    
    # Step 4: Analyze with vision model
    print(f"  🤖 Analyzing with AI...")
    analyses = []
    
    for i, img_path in enumerate(downloaded, 1):
        print(f"     [{i}/{len(downloaded)}] {img_path.name}...", end=" ", flush=True)
        analysis = analyze_photo(img_path, location_name)
        if analysis:
            analyses.append(analysis)
            print(f"score={analysis.quality_score}, {analysis.category}")
        else:
            print("failed")
    
    if not analyses:
        return LocationResult(
            name=location_name, google_name=google_name, google_address=google_address,
            photos_downloaded=len(downloaded), photos_analyzed=0, photos_selected=[],
            status="analysis_failed"
        )
    
    # Step 5: Select best diverse photos
    selected = select_diverse_photos(analyses, count=PHOTOS_TO_SELECT)
    
    print(f"  ✅ Selected {len(selected)} photos:")
    
    # Copy winners to curated folder
    curated_folder.mkdir(parents=True, exist_ok=True)
    selected_files = []
    
    for i, photo in enumerate(selected, 1):
        src = download_folder / photo.filename
        # Name includes rank and category for easy browsing
        dst = curated_folder / f"{i:02d}_{photo.category}.jpg"
        shutil.copy2(src, dst)
        selected_files.append(f"{i:02d}_{photo.category}.jpg")
        print(f"     {i}. {photo.category} (score: {photo.quality_score}/10)")
        print(f"        {photo.description[:60]}...")
    
    # Save detailed analysis report
    report = {
        "location": location_name,
        "google_name": google_name,
        "google_address": google_address,
        "selected": [asdict(a) for a in selected],
        "all_analyses": [asdict(a) for a in sorted(analyses, key=lambda x: x.quality_score, reverse=True)],
    }
    report_path = reports_dir / f"{folder_name}_analysis.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    
    return LocationResult(
        name=location_name, google_name=google_name, google_address=google_address,
        photos_downloaded=len(downloaded), photos_analyzed=len(analyses),
        photos_selected=selected_files, status="success"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and curate location photos using Google Places + local AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python location_photo_curator.py locations.csv ./output --api-key YOUR_KEY
  python location_photo_curator.py locations.csv ./output  # uses GOOGLE_PLACES_API_KEY env var
        """
    )
    parser.add_argument("csv_file", help="CSV file with 'Location' column")
    parser.add_argument("output_dir", help="Output directory for photos")
    parser.add_argument("--api-key", help="Google Places API key (or set GOOGLE_PLACES_API_KEY env var)")
    parser.add_argument("--model", default=OLLAMA_MODEL, help=f"Ollama model to use (default: {OLLAMA_MODEL})")
    
    args = parser.parse_args()
    
    # Get API key
    api_key = args.api_key or os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        print("ERROR: Google Places API key required.")
        print("Provide via --api-key or set GOOGLE_PLACES_API_KEY environment variable.")
        sys.exit(1)
    
    # Update model if specified
    global OLLAMA_MODEL
    OLLAMA_MODEL = args.model
    
    # Verify Ollama
    if not check_ollama():
        sys.exit(1)
    
    # Setup directories
    output_dir = Path(args.output_dir)
    downloads_dir = output_dir / "all_downloads"
    curated_dir = output_dir / "curated"
    reports_dir = output_dir / "reports"
    
    for d in [downloads_dir, curated_dir, reports_dir]:
        d.mkdir(parents=True, exist_ok=True)
    
    # Read CSV
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}")
        sys.exit(1)
    
    locations = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            locations.append(row["Location"])
    
    print(f"╔{'═'*58}╗")
    print(f"║  Location Photo Curator                                  ║")
    print(f"╠{'═'*58}╣")
    print(f"║  Locations: {len(locations):<45} ║")
    print(f"║  Output:    {str(output_dir):<45} ║")
    print(f"║  Model:     {OLLAMA_MODEL:<45} ║")
    print(f"╚{'═'*58}╝")
    
    # Process each location
    results = []
    for i, location in enumerate(locations, 1):
        print(f"\n[{i}/{len(locations)}]", end="")
        result = process_location(location, api_key, downloads_dir, curated_dir, reports_dir)
        results.append(result)
    
    # Summary
    print(f"\n\n{'═'*60}")
    print("SUMMARY")
    print(f"{'═'*60}")
    
    success = [r for r in results if r.status == "success"]
    not_found = [r for r in results if r.status == "not_found"]
    no_photos = [r for r in results if r.status == "no_photos"]
    failed = [r for r in results if r.status == "analysis_failed"]
    
    total_downloaded = sum(r.photos_downloaded for r in results)
    total_selected = sum(len(r.photos_selected) for r in results)
    
    print(f"  ✅ Success:      {len(success)}")
    print(f"  ❌ Not found:    {len(not_found)}")
    print(f"  📷 No photos:    {len(no_photos)}")
    print(f"  ⚠️  AI failed:    {len(failed)}")
    print(f"  ─────────────────────")
    print(f"  📥 Downloaded:   {total_downloaded} photos")
    print(f"  🏆 Curated:      {total_selected} photos")
    print(f"\n  Output: {output_dir}")
    print(f"  └── curated/     ← Your photos are here!")
    
    # Save summary
    summary = {
        "total_locations": len(locations),
        "success": len(success),
        "not_found": len(not_found),
        "no_photos": len(no_photos),
        "analysis_failed": len(failed),
        "total_downloaded": total_downloaded,
        "total_curated": total_selected,
        "results": [asdict(r) for r in results],
    }
    
    with open(reports_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    if not_found:
        print(f"\n  Locations not found on Google:")
        for r in not_found:
            print(f"    • {r.name}")


if __name__ == "__main__":
    main()
