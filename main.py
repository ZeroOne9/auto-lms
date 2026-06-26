import json
import os
import re
import threading
import time
import tkinter as tk
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from tkinter import filedialog, messagebox

import pyautogui
import pytesseract
import fitz
from PIL import Image, ImageFilter, ImageOps
from pypdf import PdfReader


CONFIG_FILE = Path("config.json")
ANSWER_BANK_FILE = Path("answer_bank.json")
ANSWER_KEYS = ["A", "B", "C", "D"]
DEFAULT_START_QUESTION = 1
ANSWER_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3}
BLUE_BUTTON_MIN_AREA = 250
RADIO_GROUP_MIN_COUNT = 2
REQUIRED_REGIONS = ["question", "A", "B", "C", "D"]
OPTIONAL_REGIONS = ["submit", "countdown", "popup"]
OPTIONAL_POINTS = ["next_page", "popup_click"]
REGION_LABELS = {
    "question": "Vung cau hoi",
    "A": "Vung dap an A",
    "B": "Vung dap an B",
    "C": "Vung dap an C",
    "D": "Vung dap an D",
    "submit": "Vung nut Submit/Next (bam Enter de bo qua)",
    "countdown": "Vung thoi gian dem nguoc (bam Enter de bo qua)",
    "popup": "Vung noi dung popup/thong bao (bam Enter de bo qua)",
    "next_page": "Diem nut trang ke tiep khi het gio (bam Enter de bo qua)",
    "popup_click": "Diem can click khi popup xuat hien (bam Enter de bo qua)",
}

def normalize_text_for_match(text):
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_option_text(text):
    text = re.sub(r"^\s*[A-Da-d1-4]\s*[\).:\-]\s*", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def similarity_score(left, right):
    left_norm = normalize_text_for_match(left)
    right_norm = normalize_text_for_match(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return 0.92
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def extract_question_number(text):
    patterns = [
        r"\b(?:câu|cau|question|ques|q)\s*\.?\s*(\d{1,4})\b",
        r"^\s*(\d{1,4})\s*[\).:-]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def parse_countdown_seconds(text):
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    time_match = re.search(r"(\d{1,2})\s*[:：]\s*(\d{1,2})(?:\s*[:：]\s*(\d{1,2}))?", cleaned)
    if time_match:
        parts = [int(part) for part in time_match.groups() if part is not None]
        if len(parts) == 2:
            minutes, seconds = parts
            return minutes * 60 + seconds
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return hours * 3600 + minutes * 60 + seconds

    number_match = re.search(r"\b(\d{1,5})\b", cleaned)
    if number_match:
        return int(number_match.group(1))
    return None


def is_radio_pixel(red, green, blue):
    near_gray = abs(red - green) < 25 and abs(green - blue) < 25
    return near_gray and 70 <= red <= 190


def is_blue_button_pixel(red, green, blue):
    return blue >= 140 and green >= 80 and red <= 90 and blue > red + 55


def connected_components_from_mask(mask):
    seen = set()
    components = []
    for point in list(mask):
        if point in seen:
            continue
        stack = [point]
        seen.add(point)
        xs = []
        ys = []
        while stack:
            x, y = stack.pop()
            xs.append(x)
            ys.append(y)
            for next_x in (x - 1, x, x + 1):
                for next_y in (y - 1, y, y + 1):
                    neighbor = (next_x, next_y)
                    if neighbor in mask and neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
        components.append(
            {
                "x1": min(xs),
                "y1": min(ys),
                "x2": max(xs),
                "y2": max(ys),
                "area": len(xs),
                "cx": (min(xs) + max(xs)) / 2,
                "cy": (min(ys) + max(ys)) / 2,
                "w": max(xs) - min(xs) + 1,
                "h": max(ys) - min(ys) + 1,
            }
        )
    return components


def find_radio_centers(image):
    width, height = image.size
    x_start = int(width * float(os.getenv("AUTO_RADIO_X_START_RATIO", "0.18")))
    x_end = int(width * float(os.getenv("AUTO_RADIO_X_END_RATIO", "0.70")))
    y_start = int(height * float(os.getenv("AUTO_RADIO_Y_START_RATIO", "0.28")))
    y_end = int(height * float(os.getenv("AUTO_RADIO_Y_END_RATIO", "0.88")))

    pixels = image.load()
    mask = set()
    for y in range(y_start, y_end):
        for x in range(x_start, x_end):
            red, green, blue = pixels[x, y]
            if is_radio_pixel(red, green, blue):
                mask.add((x, y))

    candidates = []
    for component in connected_components_from_mask(mask):
        ratio = component["w"] / max(component["h"], 1)
        if (
            10 <= component["w"] <= 34
            and 10 <= component["h"] <= 34
            and 0.65 <= ratio <= 1.45
            and 25 <= component["area"] <= 260
        ):
            candidates.append(component)

    groups = []
    for candidate in sorted(candidates, key=lambda item: item["cx"]):
        for group in groups:
            if abs(group["x"] - candidate["cx"]) <= 18:
                group["items"].append(candidate)
                group["x"] = sum(item["cx"] for item in group["items"]) / len(group["items"])
                break
        else:
            groups.append({"x": candidate["cx"], "items": [candidate]})

    groups = [
        group
        for group in groups
        if len(group["items"]) >= RADIO_GROUP_MIN_COUNT and width * 0.18 <= group["x"] <= width * 0.45
    ]
    if not groups:
        return []

    best_group = max(groups, key=lambda group: (len(group["items"]), -group["x"]))
    centers = sorted(
        [(int(item["cx"]), int(item["cy"])) for item in best_group["items"]],
        key=lambda point: point[1],
    )

    filtered = []
    for center in centers:
        if not filtered or abs(center[1] - filtered[-1][1]) >= 18:
            filtered.append(center)
    return filtered[:4]


def find_blue_button_center(image, below_y=0):
    width, height = image.size
    x_start = int(width * float(os.getenv("AUTO_BUTTON_X_START_RATIO", "0.45")))
    x_end = int(width * float(os.getenv("AUTO_BUTTON_X_END_RATIO", "0.98")))
    y_start = max(int(height * float(os.getenv("AUTO_BUTTON_Y_START_RATIO", "0.35"))), below_y)
    y_end = int(height * float(os.getenv("AUTO_BUTTON_Y_END_RATIO", "0.93")))

    pixels = image.load()
    mask = set()
    for y in range(y_start, y_end):
        for x in range(x_start, x_end):
            red, green, blue = pixels[x, y]
            if is_blue_button_pixel(red, green, blue):
                mask.add((x, y))

    candidates = []
    for component in connected_components_from_mask(mask):
        if (
            component["area"] >= BLUE_BUTTON_MIN_AREA
            and 25 <= component["w"] <= 260
            and 20 <= component["h"] <= 80
        ):
            candidates.append(component)

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item["cy"] < below_y, abs(item["cy"] - max(below_y, height * 0.70)), item["area"]))
    best = candidates[0]
    return int(best["cx"]), int(best["cy"])


def extract_pdf_text(pdf_path):
    reader = PdfReader(pdf_path)
    page_texts = []
    for page in reader.pages:
        page_texts.append(page.extract_text() or "")
    return "\n".join(page_texts)


def pdf_color_to_rgb(color):
    return (color >> 16) & 255, (color >> 8) & 255, color & 255


def is_green_pdf_color(color):
    red, green, blue = pdf_color_to_rgb(color)
    return green >= 90 and green > red + 20 and green >= blue + 15


def option_number_to_answer(option_number):
    number = int(option_number)
    if 1 <= number <= len(ANSWER_KEYS):
        return ANSWER_KEYS[number - 1]
    return None


def extract_question_number_from_pdf_line(text):
    normalized = normalize_text_for_match(text)
    match = re.match(r"^\s*(?:cau|question|q)\s*(\d{1,4})\s*/?\s*$", normalized)
    if match:
        return int(match.group(1))
    return None


def parse_color_marked_answer_pdf(pdf_path):
    entries = []
    seen_questions = set()
    current_question_number = None

    document = fitz.open(pdf_path)
    try:
        for page in document:
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    line_text = "".join(span.get("text", "") for span in spans).strip()
                    if not line_text:
                        continue

                    question_number = extract_question_number_from_pdf_line(line_text)
                    if question_number is not None:
                        current_question_number = question_number
                        continue

                    if current_question_number is None or current_question_number in seen_questions:
                        continue

                    has_green_text = any(
                        span.get("text", "").strip() and is_green_pdf_color(int(span.get("color", 0)))
                        for span in spans
                    )
                    if not has_green_text:
                        continue

                    option_match = re.search(r"(?:^|[^\d])([1-4])\s*[\).:-]", line_text)
                    if not option_match:
                        continue

                    answer = option_number_to_answer(option_match.group(1))
                    if answer:
                        entries.append(
                            {
                                "number": current_question_number,
                                "question": "",
                                "answer": answer,
                                "options": [],
                                "source": "green_option",
                            }
                        )
                        seen_questions.add(current_question_number)
    finally:
        document.close()

    return entries


def get_pdf_question_positions(page, scale):
    positions = []
    page_dict = page.get_text("dict")
    for block in page_dict.get("blocks", []):
        for line in block.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            question_number = extract_question_number_from_pdf_line(line_text)
            if question_number is not None:
                y_top = float(line.get("bbox", [0, 0, 0, 0])[1]) * scale
                positions.append({"number": question_number, "y": y_top})
    return sorted(positions, key=lambda item: item["y"])


def is_option_marker_pixel(red, green, blue):
    dark = red < 110 and green < 110 and blue < 110
    green_marker = green > 105 and green > red + 18 and green > blue + 8 and red < 190
    return dark or green_marker


def is_green_marker_pixel(red, green, blue):
    return green > 105 and green > red + 18 and green > blue + 8 and red < 190


def detect_option_markers(image):
    width, height = image.size
    # In this PDF family, radio/check markers sit in a narrow column before answers.
    # Row-band detection is much faster than connected components for large PDFs.
    x_start = int(width * float(os.getenv("PDF_MARKER_X_START_RATIO", "0.24")))
    x_end = int(width * float(os.getenv("PDF_MARKER_X_END_RATIO", "0.34")))
    x_start = max(0, min(x_start, width - 1))
    x_end = max(x_start + 1, min(x_end, width))

    pixels = image.load()
    rows = []
    for y in range(height):
        marker_count = 0
        green_count = 0
        for x in range(x_start, x_end):
            red, green, blue = pixels[x, y]
            if is_option_marker_pixel(red, green, blue):
                marker_count += 1
                if is_green_marker_pixel(red, green, blue):
                    green_count += 1
        if marker_count >= 4:
            rows.append({"y": y, "marker_count": marker_count, "green_count": green_count})

    row_bands = []
    for row in rows:
        if not row_bands or row["y"] > row_bands[-1]["end_y"] + 2:
            row_bands.append(
                {
                    "start_y": row["y"],
                    "end_y": row["y"],
                    "marker_count": row["marker_count"],
                    "green_count": row["green_count"],
                }
            )
        else:
            row_bands[-1]["end_y"] = row["y"]
            row_bands[-1]["marker_count"] += row["marker_count"]
            row_bands[-1]["green_count"] += row["green_count"]

    markers = []
    for band in row_bands:
        band_height = band["end_y"] - band["start_y"] + 1
        if 10 <= band_height <= 80 and band["marker_count"] >= 60:
            y_center = (band["start_y"] + band["end_y"]) / 2
            markers.append(
                {
                    "x": (x_start + x_end) / 2,
                    "y": y_center,
                    "bbox": (x_start, band["start_y"], x_end, band["end_y"]),
                    "green": band["green_count"] >= 20,
                    "green_count": band["green_count"],
                }
            )

    markers.sort(key=lambda item: (item["y"], item["x"]))
    return markers


def detect_answer_separator_lines(image):
    width, height = image.size
    x_start = int(width * float(os.getenv("PDF_ANSWER_LINE_X_START_RATIO", "0.30")))
    x_end = int(width * float(os.getenv("PDF_ANSWER_LINE_X_END_RATIO", "0.75")))
    x_start = max(0, min(x_start, width - 1))
    x_end = max(x_start + 1, min(x_end, width))

    pixels = image.load()
    line_rows = []
    min_line_pixels = int((x_end - x_start) * 0.70)
    for y in range(height):
        line_pixel_count = 0
        for x in range(x_start, x_end):
            red, green, blue = pixels[x, y]
            is_gray = abs(red - green) <= 5 and abs(green - blue) <= 5 and 195 <= red <= 245
            if is_gray:
                line_pixel_count += 1
        if line_pixel_count >= min_line_pixels:
            line_rows.append(y)

    grouped_lines = []
    for y in line_rows:
        if not grouped_lines or y > grouped_lines[-1]["end_y"] + 2:
            grouped_lines.append({"start_y": y, "end_y": y})
        else:
            grouped_lines[-1]["end_y"] = y

    return [(line["start_y"] + line["end_y"]) / 2 for line in grouped_lines]


def trim_answer_separator_lines(separator_lines):
    lines = sorted(separator_lines)
    max_initial_gap = float(os.getenv("PDF_ANSWER_INITIAL_GAP_MAX", "110"))
    while len(lines) >= 2 and lines[1] - lines[0] > max_initial_gap:
        lines.pop(0)
    if len(lines) > 5:
        lines = lines[-5:]
    return lines


def count_green_pixels_in_answer_row(image, y_start, y_end):
    width, height = image.size
    x_start = int(width * float(os.getenv("PDF_ANSWER_GREEN_X_START_RATIO", "0.24")))
    x_end = int(width * float(os.getenv("PDF_ANSWER_GREEN_X_END_RATIO", "0.82")))
    x_start = max(0, min(x_start, width - 1))
    x_end = max(x_start + 1, min(x_end, width))
    y_start = max(0, min(int(y_start), height - 1))
    y_end = max(y_start + 1, min(int(y_end), height))

    pixels = image.load()
    green_count = 0
    for y in range(y_start, y_end):
        for x in range(x_start, x_end):
            red, green, blue = pixels[x, y]
            if is_green_marker_pixel(red, green, blue):
                green_count += 1
    return green_count


def selected_answer_from_separator_lines(image, separator_lines, start_y, end_y, include_prefirst_row=False):
    lines = sorted(separator_lines)
    if not lines:
        return None

    selected_row_indexes = set()
    row_bounds = []
    first_line = lines[0]
    if include_prefirst_row and first_line - start_y > float(os.getenv("PDF_PRE_FIRST_ROW_MIN_HEIGHT", "35")):
        row_bounds.append((start_y, first_line))
    for row_index, row_start in enumerate(lines):
        row_end = lines[row_index + 1] if row_index + 1 < len(lines) else end_y
        row_bounds.append((row_start, row_end))

    for row_index, (row_start, row_end) in enumerate(row_bounds):
        green_count = count_green_pixels_in_answer_row(image, row_start + 1, row_end - 1)
        if green_count >= int(os.getenv("PDF_ANSWER_GREEN_MIN_PIXELS", "20")):
            selected_row_indexes.add(row_index)

    if len(selected_row_indexes) != 1:
        return None
    return option_number_to_answer(next(iter(selected_row_indexes)) + 1)


def build_answer_row_bounds(separator_lines, start_y, end_y, include_prefirst_row=False):
    lines = sorted(separator_lines)
    if not lines:
        return []

    row_bounds = []
    if include_prefirst_row and lines[0] - start_y > float(os.getenv("PDF_PRE_FIRST_ROW_MIN_HEIGHT", "35")):
        row_bounds.append((start_y, lines[0]))

    for row_index, row_start in enumerate(lines):
        row_end = lines[row_index + 1] if row_index + 1 < len(lines) else end_y
        row_bounds.append((row_start, row_end))
    return row_bounds[:4]


def ocr_pil_text(image, psm=6):
    image = image.convert("L")
    image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.SHARPEN)
    width, height = image.size
    if width < 700:
        ratio = 700 / max(width, 1)
        image = image.resize((int(width * ratio), int(height * ratio)), Image.Resampling.LANCZOS)
    text = pytesseract.image_to_string(
        image,
        lang=os.getenv("TESSERACT_LANG", "eng+vie"),
        config=f"--psm {psm}",
    )
    return re.sub(r"\s+", " ", text or "").strip()


def ocr_answer_rows_from_pdf_image(image, row_bounds):
    width, height = image.size
    x_start = int(width * float(os.getenv("PDF_OPTION_TEXT_X_START_RATIO", "0.26")))
    x_end = int(width * float(os.getenv("PDF_OPTION_TEXT_X_END_RATIO", "0.84")))
    options = []
    for row_start, row_end in row_bounds:
        y1 = max(0, int(row_start) + 1)
        y2 = min(height, int(row_end) - 1)
        if y2 <= y1:
            options.append("")
            continue
        crop = image.crop((x_start, y1, x_end, y2))
        try:
            options.append(clean_option_text(ocr_pil_text(crop, psm=6)))
        except Exception:
            options.append("")
    return options


def parse_visual_marked_answer_pdf(pdf_path):
    entries = []
    seen_questions = set()
    scale = float(os.getenv("PDF_RENDER_SCALE", "1.0"))

    document = fitz.open(pdf_path)
    try:
        for page in document:
            question_positions = get_pdf_question_positions(page, scale)
            if not question_positions:
                continue

            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            separator_lines = detect_answer_separator_lines(image)
            if not separator_lines:
                continue

            for index, question in enumerate(question_positions):
                number = question["number"]
                if number in seen_questions:
                    continue

                start_y = question["y"]
                end_y = question_positions[index + 1]["y"] if index + 1 < len(question_positions) else image.height
                question_separators = [
                    line_y for line_y in separator_lines if start_y + 20 <= line_y < end_y - 5
                ]
                if not question_separators:
                    continue

                question_separators.sort()
                answer_lines = question_separators
                include_prefirst_for_options = False
                answer = selected_answer_from_separator_lines(
                    image,
                    question_separators,
                    start_y + 20,
                    end_y,
                    include_prefirst_row=False,
                )
                if not answer:
                    trimmed_separators = trim_answer_separator_lines(question_separators)
                    if trimmed_separators != question_separators:
                        answer = selected_answer_from_separator_lines(
                            image,
                            trimmed_separators,
                            start_y + 20,
                            end_y,
                            include_prefirst_row=False,
                        )
                        if answer:
                            answer_lines = trimmed_separators
                if not answer:
                    answer = selected_answer_from_separator_lines(
                        image,
                        question_separators,
                        start_y + 20,
                        end_y,
                        include_prefirst_row=True,
                    )
                    if answer:
                        answer_lines = question_separators
                        include_prefirst_for_options = True
                if not answer:
                    continue

                row_bounds = build_answer_row_bounds(
                    answer_lines,
                    start_y + 20,
                    end_y,
                    include_prefirst_row=include_prefirst_for_options,
                )
                option_texts = ocr_answer_rows_from_pdf_image(image, row_bounds)
                entries.append(
                    {
                        "number": number,
                        "question": "",
                        "answer": answer,
                        "options": option_texts,
                        "source": "visual_marker",
                    }
                )
                seen_questions.add(number)
    finally:
        document.close()

    return entries


def merge_answer_entries(*entry_groups):
    merged = []
    by_number = {}
    seen = set()

    for entries in entry_groups:
        for entry in entries:
            number = entry.get("number")
            answer = entry.get("answer")
            question = entry.get("question", "")
            if number is not None and answer in ANSWER_KEYS:
                existing_index = by_number.get(number)
                if existing_index is not None:
                    existing = merged[existing_index]
                    if entry.get("source") == "green_option" and existing.get("answer") != answer:
                        merged[existing_index] = entry
                    continue
                by_number[number] = len(merged)
                merged.append(entry)
                continue

            key = (number, normalize_text_for_match(question), answer)
            if key not in seen and answer in ANSWER_KEYS:
                merged.append(entry)
                seen.add(key)

    return merged


def parse_answer_bank_pdf(pdf_path):
    visual_entries = parse_visual_marked_answer_pdf(pdf_path)
    visual_min_entries = int(os.getenv("PDF_VISUAL_MIN_ENTRIES", "20"))
    if len(visual_entries) >= visual_min_entries:
        return merge_answer_entries(visual_entries), "", 0, len(visual_entries)

    text_entries = []
    text = extract_pdf_text(pdf_path)
    if text.strip():
        text_entries = parse_answer_bank_text(text)

    color_entries = parse_color_marked_answer_pdf(pdf_path)
    return merge_answer_entries(visual_entries, color_entries, text_entries), text, len(color_entries), len(visual_entries)


def clean_imported_question(text):
    text = re.sub(r"(?is)\bA\s*[\).:-].*?\bB\s*[\).:-].*", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1000]


def parse_answer_bank_text(text):
    entries = []
    seen = set()

    labeled_answer_pattern = re.compile(
        r"\b(?:câu|cau|question|ques|q)\s*\.?\s*(\d{1,4})\b.{0,40}?"
        r"(?:đáp\s*án|dap\s*an|answer|ans|correct)\s*[:.\-)]?\s*([ABCD])\b",
        re.IGNORECASE,
    )
    compact_numbered_pattern = re.compile(
        r"(?m)^\s*(?:câu|cau|question|ques|q)\s*\.?\s*(\d{1,4})\s*[:.\-)]\s*([ABCD])\s*$",
        re.IGNORECASE,
    )
    plain_numbered_pattern = re.compile(r"(?m)^\s*(\d{1,4})\s*[\).:-]\s*([ABCD])\b", re.IGNORECASE)

    for pattern in [labeled_answer_pattern, compact_numbered_pattern, plain_numbered_pattern]:
        for match in pattern.finditer(text or ""):
            number = int(match.group(1))
            answer = match.group(2).upper()
            key = (number, "", answer)
            if key not in seen:
                entries.append({"number": number, "question": "", "answer": answer})
                seen.add(key)

    block_pattern = re.compile(
        r"(?is)(?:^|\n)\s*(?:câu|cau|question|q)?\s*\.?\s*(\d{1,4})?[\).:\-\s]*"
        r"(.{20,}?)"
        r"(?:\n|^)\s*(?:đáp\s*án|dap\s*an|answer|ans|correct)\s*[:.\-]?\s*([ABCD])\b",
    )
    for match in block_pattern.finditer(text or ""):
        number = int(match.group(1)) if match.group(1) else extract_question_number(match.group(2))
        question = clean_imported_question(match.group(2))
        answer = match.group(3).upper()
        normalized_question = normalize_text_for_match(question)
        key = (number, normalized_question, answer)
        if normalized_question and key not in seen:
            entries.append({"number": number, "question": question, "answer": answer})
            seen.add(key)

    return entries


class RegionSelector(tk.Toplevel):
    def __init__(self, master, on_done, on_cancel):
        super().__init__(master)
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.region_order = REQUIRED_REGIONS + OPTIONAL_REGIONS + OPTIONAL_POINTS
        self.current_index = 0
        self.regions = {}
        self.points = {}
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None

        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.28)
        self.configure(bg="black")
        self.cursor = "crosshair"

        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.info_text = self.canvas.create_text(
            30,
            30,
            anchor="nw",
            fill="white",
            font=("Arial", 18, "bold"),
            text="",
        )
        self.update_instruction()

        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.bind("<Escape>", lambda _event: self.cancel())
        self.bind("<Return>", lambda _event: self.skip_optional())

    def update_instruction(self):
        key = self.region_order[self.current_index]
        self.canvas.itemconfig(
            self.info_text,
            text=(
                f"{self.current_action_text(key)}: {REGION_LABELS[key]}\n"
                "Esc: huy | Cac buoc tuy chon co the bo qua bang Enter"
            ),
        )

    @staticmethod
    def current_action_text(key):
        if key in OPTIONAL_POINTS:
            return "Click chuot de chon diem"
        return "Keo chuot de chon"

    def on_mouse_down(self, event):
        self.start_x = event.x_root
        self.start_y = event.y_root
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        key = self.region_order[self.current_index]
        if key in OPTIONAL_POINTS:
            size = 8
            self.rect_id = self.canvas.create_oval(
                event.x - size,
                event.y - size,
                event.x + size,
                event.y + size,
                outline="#00ff88",
                width=3,
            )
            return
        self.rect_id = self.canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline="#00ff88",
            width=3,
        )

    def on_mouse_drag(self, event):
        key = self.region_order[self.current_index]
        if key in OPTIONAL_POINTS:
            return
        if self.rect_id:
            self.canvas.coords(
                self.rect_id,
                self.start_x,
                self.start_y,
                event.x_root,
                event.y_root,
            )

    def on_mouse_up(self, event):
        key = self.region_order[self.current_index]
        if key in OPTIONAL_POINTS:
            self.points[key] = {"x": event.x_root, "y": event.y_root}
            self.next_region()
            return

        x1, y1 = self.start_x, self.start_y
        x2, y2 = event.x_root, event.y_root
        x = min(x1, x2)
        y = min(y1, y2)
        width = abs(x2 - x1)
        height = abs(y2 - y1)

        if width < 10 or height < 10:
            messagebox.showwarning("Vung qua nho", "Hay chon vung lon hon 10x10 pixel.")
            return

        self.regions[key] = {"x": x, "y": y, "w": width, "h": height}
        self.next_region()

    def skip_optional(self):
        key = self.region_order[self.current_index]
        if key in OPTIONAL_REGIONS or key in OPTIONAL_POINTS:
            self.next_region()

    def next_region(self):
        self.current_index += 1
        if self.current_index >= len(self.region_order):
            self.on_done(self.regions, self.points)
            self.destroy()
            return

        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
        self.update_instruction()

    def cancel(self):
        self.on_cancel()
        self.destroy()


class AutoQuizApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Auto LMS Multiple Choice")
        self.root.geometry("820x560")
        self.root.minsize(720, 460)

        self.config = self.load_config()
        self.answer_bank = self.load_answer_bank()
        self.stop_event = threading.Event()
        self.worker_thread = None
        self.is_running = False

        self.build_ui()
        self.log("San sang. Hay import PDF de co text dap an, roi Run Once/Auto Run.")

    def build_ui(self):
        toolbar = tk.Frame(self.root, padx=10, pady=10)
        toolbar.pack(fill=tk.X)

        self.import_pdf_button = tk.Button(toolbar, text="Import PDF", command=self.import_answer_pdf, width=14)
        self.run_once_button = tk.Button(toolbar, text="Run Once", command=self.run_once, width=14)
        self.auto_button = tk.Button(toolbar, text="Auto Run", command=self.auto_run, width=14)
        self.stop_button = tk.Button(toolbar, text="Stop", command=self.stop_auto, width=14, state=tk.DISABLED)

        self.import_pdf_button.pack(side=tk.LEFT, padx=4)
        self.run_once_button.pack(side=tk.LEFT, padx=4)
        self.auto_button.pack(side=tk.LEFT, padx=4)
        self.stop_button.pack(side=tk.LEFT, padx=4)

        status_frame = tk.Frame(self.root, padx=10)
        status_frame.pack(fill=tk.X)
        self.status_var = tk.StringVar(value=self.config_status_text())
        tk.Label(status_frame, textvariable=self.status_var, anchor="w").pack(fill=tk.X)

        log_frame = tk.Frame(self.root, padx=10, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=20)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def config_status_text(self):
        answer_count = len(self.answer_bank.get("entries", [])) if hasattr(self, "answer_bank") else 0
        option_count = sum(1 for entry in self.answer_bank.get("entries", []) if entry.get("options"))
        return f"Answer PDF: {answer_count} muc | Co text dap an: {option_count} muc | Che do: match dap an tren man hinh."

    def load_config(self):
        if not CONFIG_FILE.exists():
            return {"regions": {}}
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict) or not isinstance(data.get("regions"), dict):
                raise ValueError("config.json khong dung dinh dang")
            if "points" not in data or not isinstance(data.get("points"), dict):
                data["points"] = {}
            return data
        except Exception as exc:
            messagebox.showwarning("Loi config", f"Khong doc duoc config.json: {exc}")
            return {"regions": {}}

    def save_config(self):
        with CONFIG_FILE.open("w", encoding="utf-8") as file:
            json.dump(self.config, file, ensure_ascii=False, indent=2)

    def load_answer_bank(self):
        if not ANSWER_BANK_FILE.exists():
            return {"source_pdf": "", "entries": []}
        try:
            with ANSWER_BANK_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
                raise ValueError("answer_bank.json khong dung dinh dang")
            return data
        except Exception as exc:
            messagebox.showwarning("Loi answer bank", f"Khong doc duoc answer_bank.json: {exc}")
            return {"source_pdf": "", "entries": []}

    def save_answer_bank(self):
        with ANSWER_BANK_FILE.open("w", encoding="utf-8") as file:
            json.dump(self.answer_bank, file, ensure_ascii=False, indent=2)

    def get_first_answer_bank_number(self):
        numbers = [
            entry.get("number")
            for entry in self.answer_bank.get("entries", [])
            if isinstance(entry.get("number"), int)
        ]
        return min(numbers) if numbers else None

    def has_required_regions(self):
        regions = self.config.get("regions", {})
        return all(key in regions for key in REQUIRED_REGIONS)

    def set_regions(self):
        if self.is_running:
            messagebox.showwarning("Dang chay", "Hay bam Stop truoc khi cau hinh lai vung.")
            return
        self.root.iconify()
        self.root.after(500, lambda: RegionSelector(self.root, self.on_regions_done, self.on_regions_cancel))

    def on_regions_done(self, regions, points):
        self.root.deiconify()
        self.config = {"regions": regions, "points": points}
        self.save_config()
        self.status_var.set(self.config_status_text())
        self.log("Da luu toa do vao config.json.")

    def on_regions_cancel(self):
        self.root.deiconify()
        self.log("Da huy chon vung.")

    def import_answer_pdf(self):
        if self.is_running:
            messagebox.showwarning("Dang chay", "Hay bam Stop truoc khi import PDF.")
            return

        pdf_path = filedialog.askopenfilename(
            title="Chon file PDF bo dap an",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not pdf_path:
            return

        self.import_pdf_button.config(state=tk.DISABLED)
        self.log(f"Dang import PDF: {pdf_path}")
        thread = threading.Thread(target=self.import_answer_pdf_worker, args=(pdf_path,), daemon=True)
        thread.start()

    def import_answer_pdf_worker(self, pdf_path):
        try:
            entries, text, color_entry_count, visual_entry_count = parse_answer_bank_pdf(pdf_path)
            if not entries:
                if not text.strip():
                    raise RuntimeError(
                        "PDF khong co text de trich xuat. Neu PDF la ban scan/anh, can OCR PDF truoc roi import lai."
                    )
                raise RuntimeError(
                    "Khong tim thay dap an trong PDF. Ho tro 'Cau 1: A', block 'Dap an: C', "
                    "hoac option 1/2/3/4 duoc to mau xanh."
                )

            self.answer_bank = {
                "source_pdf": str(pdf_path),
                "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "entries": entries,
            }
            self.save_answer_bank()
            self.root.after(0, lambda: self.status_var.set(self.config_status_text()))
            self.log(
                f"Import PDF thanh cong: {len(entries)} muc dap an "
                f"({visual_entry_count} muc doc tu marker/check xanh, "
                f"{color_entry_count} muc doc tu option mau xanh text). Da luu vao answer_bank.json."
            )
        except Exception as exc:
            error_message = str(exc)
            self.log(f"Import PDF that bai: {error_message}")
            self.root.after(0, lambda: messagebox.showerror("Import PDF that bai", error_message))
        finally:
            self.root.after(0, lambda: self.import_pdf_button.config(state=tk.NORMAL))

    def run_once(self):
        if self.is_running:
            self.log("Auto Run dang chay, bo qua Run Once.")
            return
        thread = threading.Thread(target=self.safe_process_once, daemon=True)
        thread.start()

    def auto_run(self):
        if self.is_running:
            return
        if not self.answer_bank.get("entries"):
            self.log("Loi: Chua import PDF dap an.")
            messagebox.showerror("Thieu PDF dap an", "Hay bam Import PDF truoc khi Auto Run.")
            return
        if not self.has_option_text_entries():
            messagebox.showerror("Thieu text dap an", "Hay Import PDF lai sau khi cai Tesseract OCR.")
            return

        self.stop_event.clear()
        self.is_running = True
        self.set_running_buttons(True)
        self.worker_thread = threading.Thread(target=self.auto_loop, daemon=True)
        self.worker_thread.start()
        self.log("Bat dau Auto Run.")

    def stop_auto(self):
        self.stop_event.set()
        self.log("Dang dung Auto Run an toan...")

    def auto_loop(self):
        try:
            while not self.stop_event.is_set():
                try:
                    self.process_once()
                except Exception as exc:
                    self.log(f"Loi vong auto: {exc}")
                for _ in range(20):
                    if self.stop_event.is_set():
                        break
                    time.sleep(0.1)
        finally:
            self.is_running = False
            self.root.after(0, lambda: self.set_running_buttons(False))
            self.log("Da dung Auto Run.")

    def safe_process_once(self):
        try:
            self.process_once()
        except Exception as exc:
            self.log(f"Loi: {exc}")

    def process_once(self):
        if not self.answer_bank.get("entries"):
            raise RuntimeError("Chua import PDF dap an. Hay bam Import PDF truoc khi chay.")
        if not self.has_option_text_entries():
            raise RuntimeError("Answer bank chua co text dap an. Hay Import PDF lai sau khi cai Tesseract OCR.")

        screenshot = pyautogui.screenshot()
        radio_centers = find_radio_centers(screenshot)
        if not radio_centers:
            raise RuntimeError("Khong tim thay cac nut tron dap an tren man hinh.")

        screen_options = self.ocr_screen_options(screenshot, radio_centers)
        self.log("Dap an OCR tren man hinh:")
        for index, text in enumerate(screen_options, start=1):
            self.log(f"{index}. {text or '[rong]'}")

        matched_entry, match_score = self.find_answer_by_screen_options(screen_options)
        if not matched_entry:
            raise RuntimeError("Khong tim thay cau khop trong PDF theo cac dap an tren man hinh.")

        answer = matched_entry["answer"]
        answer_index = ANSWER_INDEX[answer]
        if answer_index >= len(radio_centers):
            raise RuntimeError(
                f"Dap an {answer} can vi tri {answer_index + 1}, "
                f"nhung man hinh chi tim thay {len(radio_centers)} lua chon."
            )

        selected_point = radio_centers[answer_index]
        self.log(
            f"Khớp PDF câu {matched_entry.get('number')} "
            f"(score {match_score:.2f}): dap an {answer}, click lua chon thu {answer_index + 1}."
        )
        self.click_xy(selected_point[0], selected_point[1], f"Dap an {answer}")
        time.sleep(0.35)

        screenshot_after_answer = pyautogui.screenshot()
        below_y = max(point[1] for point in radio_centers) + 20
        next_button = find_blue_button_center(screenshot_after_answer, below_y=below_y)
        if not next_button:
            raise RuntimeError("Khong tim thay nut Tiep mau xanh sau khi chon dap an.")

        self.click_xy(next_button[0], next_button[1], "Tiep")
        time.sleep(0.8)

    def is_popup_visible(self, regions):
        if "popup" not in regions:
            return False

        text = self.ocr_region(regions["popup"])
        self.log(f"Popup OCR: {text or '[rong]'}")
        normalized_text = normalize_text_for_match(text)
        if not normalized_text:
            return False

        keywords = [
            normalize_text_for_match(keyword)
            for keyword in os.getenv("POPUP_KEYWORDS", "").split(",")
            if keyword.strip()
        ]
        if keywords:
            matched = any(keyword and keyword in normalized_text for keyword in keywords)
            if matched:
                self.log("Phat hien popup theo tu khoa.")
            return matched

        try:
            min_len = int(os.getenv("POPUP_MIN_TEXT_LEN", "3"))
        except ValueError:
            min_len = 3
        visible = len(normalized_text) >= min_len
        if visible:
            self.log("Phat hien popup theo OCR co noi dung.")
        return visible

    def is_countdown_expired(self, regions):
        if "countdown" not in regions:
            return False
        text = self.ocr_region(regions["countdown"])
        seconds = parse_countdown_seconds(text)
        self.log(f"Countdown OCR: {text or '[rong]'}")
        if seconds is None:
            self.log("Khong parse duoc countdown, tiep tuc xu ly cau hoi.")
            return False
        self.log(f"Countdown con lai: {seconds} giay.")
        return seconds <= 0

    def has_option_text_entries(self):
        return any(entry.get("options") for entry in self.answer_bank.get("entries", []))

    def ocr_screen_options(self, screenshot, radio_centers):
        width, height = screenshot.size
        option_texts = []
        if len(radio_centers) >= 2:
            median_gap = sorted(
                radio_centers[index + 1][1] - radio_centers[index][1]
                for index in range(len(radio_centers) - 1)
            )[len(radio_centers) // 2 - 1]
        else:
            median_gap = 48

        x_start = min(width - 1, max(0, radio_centers[0][0] + 22))
        x_end = int(width * float(os.getenv("SCREEN_OPTION_TEXT_X_END_RATIO", "0.82")))
        x_end = max(x_start + 50, min(x_end, width))

        for index, (radio_x, radio_y) in enumerate(radio_centers):
            if index == 0:
                y_start = int(radio_y - median_gap * 0.45)
            else:
                y_start = int((radio_centers[index - 1][1] + radio_y) / 2)

            if index + 1 < len(radio_centers):
                y_end = int((radio_y + radio_centers[index + 1][1]) / 2)
            else:
                y_end = int(radio_y + median_gap * 0.75)

            y_start = max(0, y_start)
            y_end = min(height, max(y_start + 20, y_end))
            crop = screenshot.crop((x_start, y_start, x_end, y_end))
            text = clean_option_text(ocr_pil_text(crop, psm=6))
            option_texts.append(text)
        return option_texts

    def find_answer_by_screen_options(self, screen_options):
        best_entry = None
        best_score = 0.0
        screen_options = [clean_option_text(option) for option in screen_options]

        for entry in self.answer_bank.get("entries", []):
            bank_options = [clean_option_text(option) for option in entry.get("options", [])]
            pair_count = min(len(screen_options), len(bank_options))
            if pair_count < 2:
                continue

            pair_scores = []
            for index in range(pair_count):
                pair_scores.append(similarity_score(screen_options[index], bank_options[index]))

            useful_scores = [score for score in pair_scores if score > 0]
            if len(useful_scores) < max(2, pair_count - 1):
                continue

            score = sum(pair_scores) / pair_count
            if score > best_score:
                best_score = score
                best_entry = entry

        threshold = float(os.getenv("SCREEN_OPTION_MATCH_THRESHOLD", "0.58"))
        if best_entry and best_score >= threshold:
            return best_entry, best_score
        if best_entry:
            self.log(f"Ung vien PDF gan nhat cau {best_entry.get('number')} score {best_score:.2f}, chua du nguong.")
        return None, best_score

    def find_answer_in_bank(self, texts):
        entries = self.answer_bank.get("entries", [])
        if not entries:
            return None

        question = texts.get("question", "")
        question_number = extract_question_number(question)
        if question_number is not None:
            for entry in entries:
                if entry.get("number") == question_number and entry.get("answer") in ANSWER_KEYS:
                    self.log(f"Tim thay dap an trong PDF theo so cau {question_number}.")
                    return entry["answer"]

        normalized_question = normalize_text_for_match(question)
        if not normalized_question:
            return None

        best_entry = None
        best_score = 0.0
        for entry in entries:
            entry_question = normalize_text_for_match(entry.get("question", ""))
            if not entry_question:
                continue
            score = SequenceMatcher(None, normalized_question, entry_question).ratio()
            if normalized_question in entry_question or entry_question in normalized_question:
                score = max(score, 0.92)
            if score > best_score:
                best_score = score
                best_entry = entry

        threshold = float(os.getenv("ANSWER_BANK_MATCH_THRESHOLD", "0.72"))
        if best_entry and best_score >= threshold and best_entry.get("answer") in ANSWER_KEYS:
            self.log(f"Tim thay dap an trong PDF theo noi dung cau hoi, do khop {best_score:.2f}.")
            return best_entry["answer"]

        if best_entry:
            self.log(f"PDF co ung vien gan nhat nhung chua du nguong: {best_score:.2f}.")
        return None

    def ocr_region(self, region):
        try:
            image = pyautogui.screenshot(region=(region["x"], region["y"], region["w"], region["h"]))
            image = self.preprocess_image(image)
            text = pytesseract.image_to_string(image, lang=os.getenv("TESSERACT_LANG", "eng+vie"))
            return self.clean_text(text)
        except Exception as exc:
            raise RuntimeError(f"OCR loi tai vung {region}: {exc}") from exc

    def ocr_region_safe(self, region, label):
        try:
            return self.ocr_region(region)
        except Exception as exc:
            self.log(f"OCR dap an {label} loi, bo qua log text: {exc}")
            return ""

    @staticmethod
    def preprocess_image(image):
        image = image.convert("L")
        image = ImageOps.autocontrast(image)
        image = image.filter(ImageFilter.SHARPEN)
        width, height = image.size
        if width < 900:
            ratio = 900 / max(width, 1)
            image = image.resize((int(width * ratio), int(height * ratio)), Image.Resampling.LANCZOS)
        return image

    @staticmethod
    def clean_text(text):
        return re.sub(r"\s+", " ", text or "").strip()

    def click_region(self, region, label):
        try:
            x = region["x"] + region["w"] // 2
            y = region["y"] + region["h"] // 2
            pyautogui.click(x=x, y=y)
            self.log(f"Click {label}: thanh cong tai ({x}, {y}).")
        except Exception as exc:
            self.log(f"Click {label}: that bai - {exc}")
            raise

    def click_xy(self, x, y, label):
        try:
            pyautogui.moveTo(x=x, y=y, duration=0.12)
            pyautogui.click(button="left")
            self.log(f"Click {label}: thanh cong tai ({x}, {y}).")
        except Exception as exc:
            self.log(f"Click {label}: that bai - {exc}")
            raise

    def click_point(self, point, label):
        try:
            x = int(point["x"])
            y = int(point["y"])
            pyautogui.moveTo(x=x, y=y, duration=0.15)
            pyautogui.click(button="left")
            self.log(f"Click {label}: thanh cong tai ({x}, {y}).")
        except Exception as exc:
            self.log(f"Click {label}: that bai - {exc}")
            raise

    def set_running_buttons(self, running):
        self.import_pdf_button.config(state=tk.DISABLED if running else tk.NORMAL)
        self.run_once_button.config(state=tk.DISABLED if running else tk.NORMAL)
        self.auto_button.config(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.config(state=tk.NORMAL if running else tk.DISABLED)

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")

        def append():
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)

        self.root.after(0, append)


def main():
    pyautogui.FAILSAFE = True
    root = tk.Tk()
    app = AutoQuizApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: on_close(root, app))
    root.mainloop()


def on_close(root, app):
    app.stop_event.set()
    root.destroy()


if __name__ == "__main__":
    main()
