from __future__ import annotations

import subprocess
import time
import random
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from threading import Event
import yaml
from pynput import keyboard
import io
import re
from typing import Optional, List

from PIL import ImageGrab, ImageOps, ImageEnhance, Image
import Vision
import Quartz
import Foundation

NUM_PATTERN = re.compile(r"\d+")

# 保持和你单独脚本一致
SCALE = 2
ALL_SCREENS = True

OCR_SCALE = 10
OCR_CONTRAST = 1.2
OCR_SHARPNESS = 1.6
OCR_INVERT = False


def grab_full():
    try:
        return ImageGrab.grab(all_screens=ALL_SCREENS)
    except TypeError:
        return ImageGrab.grab()


def preprocess_for_vision(img: Image.Image) -> Image.Image:
    img = ImageOps.grayscale(img)
    try:
        resample = Image.Resampling.LANCZOS
    except Exception:
        resample = Image.LANCZOS
    img = img.resize((img.size[0] * OCR_SCALE, img.size[1] * OCR_SCALE), resample=resample)
    img = ImageEnhance.Contrast(img).enhance(OCR_CONTRAST)
    img = ImageEnhance.Sharpness(img).enhance(OCR_SHARPNESS)
    if OCR_INVERT:
        img = ImageOps.invert(img)
    return img


def vision_ocr_text(pil_img: Image.Image) -> str:
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    raw = buf.getvalue()

    data = Foundation.NSData.dataWithBytes_length_(raw, len(raw))
    src = Quartz.CGImageSourceCreateWithData(data, None)
    cg_img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)
    # 可选：更偏向数字 UI
    try:
        req.setRecognitionLanguages_(["en-US"])
    except Exception:
        pass

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_img, None)
    ok, _ = handler.performRequests_error_([req], None)
    if not ok:
        return ""

    results = req.results() or []
    texts: List[str] = []
    for r in results:
        top = r.topCandidates_(1)
        if top and len(top) > 0:
            texts.append(str(top[0].string()))
    return " ".join(texts)


def normalize_vision_text(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("O", "0")
            .replace("o", "0")
            .replace("I", "1")
            .replace("l", "1")
    )


def parse_single_number(text: str) -> Optional[int]:
    """
    只要一个数字：取 OCR 文本里第一个数字
    你这种情况 "4" => 4； "12/45" => 12
    """
    nums = NUM_PATTERN.findall(text or "")
    if not nums:
        return None
    return int(nums[0])


# 这里假设你的 Rect 类有 left/top/right/bottom
def read_percent(percent_rect) -> Optional[int]:
    """
    percent_rect：逻辑坐标（和你 cliclick 测点同一套坐标）
    内部严格按你单独脚本：bbox = (left*SCALE, top*SCALE, right*SCALE, bottom*SCALE)
    """
    full = grab_full()

    left, top, right, bottom = percent_rect.left, percent_rect.top, percent_rect.right, percent_rect.bottom
    bbox = (left * SCALE, top * SCALE, right * SCALE, bottom * SCALE)

    roi = full.crop(bbox)
    roi.save("percent_roi_raw.png")   # 调试：确认裁剪位置
    proc = preprocess_for_vision(roi)
    proc.save("percent_roi_proc.png") # 调试：确认预处理效果

    text = vision_ocr_text(proc)
    text = normalize_vision_text(text)

    value = parse_single_number(text)
    print(f"[read_percent] bbox={bbox} OCR={text!r} -> value={value}")
    return value




# ============================================================
# Global stop (ESC)
# ============================================================
STOP_EVENT = Event()


def start_esc_listener():
    def on_press(key):
        if key == keyboard.Key.esc:
            print("\n[KEYBOARD] ESC pressed -> stopping")
            STOP_EVENT.set()
            return False
    listener = keyboard.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()


def safe_sleep(seconds: float, tick: float = 0.05):
    end = time.time() + max(0.0, seconds)
    while time.time() < end:
        if STOP_EVENT.is_set():
            raise KeyboardInterrupt("Stopped by ESC")
        time.sleep(min(tick, end - time.time()))


# ============================================================
# Geometry
# ============================================================
@dataclass(frozen=True)
class Point:
    x: int
    y: int

    def scaled(self, scale: float) -> "Point":
        return Point(int(round(self.x * scale)), int(round(self.y * scale)))


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @staticmethod
    def from_two_points(p1: Point, p2: Point) -> "Rect":
        return Rect(
            min(p1.x, p2.x),
            min(p1.y, p2.y),
            max(p1.x, p2.x),
            max(p1.y, p2.y),
        )

    def scaled(self, scale: float) -> "Rect":
        return Rect(
            int(round(self.left * scale)),
            int(round(self.top * scale)),
            int(round(self.right * scale)),
            int(round(self.bottom * scale)),
        )

    def random_point(self, margin: int, rng: random.Random) -> Point:
        l = self.left + margin
        t = self.top + margin
        r = self.right - margin
        b = self.bottom - margin
        if r <= l or b <= t:
            return Point((self.left + self.right) // 2, (self.top + self.bottom) // 2)
        return Point(rng.randint(l, r - 1), rng.randint(t, b - 1))

    @property
    def width(self) -> int:
        return max(1, self.right - self.left)

    @property
    def height(self) -> int:
        return max(1, self.bottom - self.top)


# ============================================================
# Config
# ============================================================
def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_point(v) -> Point:
    if not (isinstance(v, list) and len(v) == 2):
        raise ValueError(f"Invalid point: {v}")
    return Point(int(v[0]), int(v[1]))


def parse_rect(v) -> Rect:
    if not (isinstance(v, dict) and "p1" in v and "p2" in v):
        raise ValueError(f"Invalid rect: {v}")
    return Rect.from_two_points(parse_point(v["p1"]), parse_point(v["p2"]))


# ============================================================
# cliclick
# ============================================================
class Clicker:
    def click(self, p: Point):
        subprocess.run(["cliclick", f"c:{p.x},{p.y}"], check=True)
        subprocess.run(["cliclick", f"du:{p.x},{p.y}"], check=True)


# ============================================================
# Pixel / Screenshot helpers
# ============================================================
def screenshot_region_to_png(rect: Rect, out_path: str) -> None:
    subprocess.run(
        ["screencapture", "-x", "-R", f"{rect.left},{rect.top},{rect.width},{rect.height}", out_path],
        check=True
    )


def get_pixel_rgb(p: Point) -> Tuple[int, int, int]:
    """
    Capture 1x1 pixel at (x,y) and return RGB.
    """
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "px.png")
        rect = Rect(p.x, p.y, p.x + 1, p.y + 1)
        screenshot_region_to_png(rect, out_path)
        img = Image.open(out_path).convert("RGB")
        return img.getpixel((0, 0))


def color_close(rgb: Tuple[int, int, int], target: Tuple[int, int, int], tol: int) -> bool:
    return (
        abs(rgb[0] - target[0]) <= tol and
        abs(rgb[1] - target[1]) <= tol and
        abs(rgb[2] - target[2]) <= tol
    )


# ============================================================
# Percent OCR stub (留空给你接 Vision/OCR)
# ============================================================


def parse_percent_text(text: str) -> Optional[int]:
    m = re.search(r"(\d{1,3})\s*%?", text)
    if not m:
        return None
    val = int(m.group(1))
    return val if 0 <= val <= 100 else None


# ============================================================
# Bot
# ============================================================
class Bot:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

        scale = float(cfg["screen"].get("scale", 1.0))

        # random
        seed = cfg["screen"]["random_click"].get("seed", None)
        self.rng = random.Random(seed)
        self.margin = int(cfg["screen"]["random_click"].get("margin", 3))

        # timing ranges
        self.click_gap_range = cfg["timing"]["click_gap_range"]
        self.poll_interval_range = cfg["timing"]["poll_interval_range"]
        self.after_places_wait = float(cfg["timing"]["after_places_wait_sec"])
        self.percent_timeout = float(cfg["timing"]["percent_wait_timeout_sec"])
        self.start_fight_gap_range = cfg["timing"]["home_start_fight_gap_range"]

        # click regions
        self.click_regions: Dict[str, Rect] = {
            k: parse_rect(v).scaled(scale) for k, v in cfg["click_regions"].items()
        }

        # detect points (home/battle)
        self.detect_points: Dict[str, Point] = {
            k: parse_point(v).scaled(scale) for k, v in cfg["detect_points"].items()
        }

        # expected colors for detect points
        exp = cfg.get("detect_points_expected_color", {})
        self.detect_expected: Dict[str, Tuple[int, int, int]] = {
            "home": tuple(exp.get("home", [255, 255, 255])),
            "battle": tuple(exp.get("battle", [255, 255, 255])),
        }
        self.detect_tol = int(cfg.get("detect_points_color_tolerance", 18))

        # detect regions (percent)
        self.detect_regions: Dict[str, Rect] = {
            k: parse_rect(v).scaled(scale) for k, v in cfg["detect_regions"].items()
        }

        self.clicker = Clicker()
        self._validate()

    def _validate(self):
        required_click = [
            "start", "fight",
            "select_1", "select_2", "select_3", "select_4", "select_5",
            "place_1", "place_2", "place_3", "place_4", "place_5", "place_6", "place_7", "place_8",
            "cancel", "confirm", "back", "collect", "collect_confirm", "collect_cancel"
        ]
        for k in required_click:
            if k not in self.click_regions:
                raise KeyError(f"Missing click_regions.{k}")

        for k in ["home", "battle"]:
            if k not in self.detect_points:
                raise KeyError(f"Missing detect_points.{k}")

        if "percent" not in self.detect_regions:
            raise KeyError("Missing detect_regions.percent")

    def rand_delay(self, r):
        return float(self.rng.uniform(r[0], r[1]))

    def _check_stop(self):
        if STOP_EVENT.is_set():
            raise KeyboardInterrupt("Stopped by ESC")

    def random_click(self, name: str):
        self._check_stop()
        p = self.click_regions[name].random_point(self.margin, self.rng)
        self.clicker.click(p)
        safe_sleep(self.rand_delay(self.click_gap_range))

    # ---- detect home/battle by pixel color ----
    def is_home_true(self) -> bool:
        p = self.detect_points["home"]
        rgb = get_pixel_rgb(p)
        ok = color_close(rgb, self.detect_expected["home"], self.detect_tol)
        print(f"[detect] home pixel {p} rgb={rgb} target={self.detect_expected['home']} tol={self.detect_tol} -> {ok}")
        return ok

    def is_battle_true(self) -> bool:
        p = self.detect_points["battle"]
        rgb = get_pixel_rgb(p)
        ok = color_close(rgb, self.detect_expected["battle"], self.detect_tol)
        print(f"[detect] battle pixel {p} rgb={rgb} target={self.detect_expected['battle']} tol={self.detect_tol} -> {ok}")
        return ok

    # ---- flow ----
    def run_one_loop(self):
        # 1) if home true -> click start then fight
        if self.is_home_true():
            self.random_click("start")
            safe_sleep(self.rand_delay(self.start_fight_gap_range))
            self.random_click("fight")

        while not self.is_battle_true():
            if self.is_home_true(): return
            self._check_stop()
            safe_sleep(self.rand_delay(self.poll_interval_range))

        # 3) random select 1..5
        self.random_click(self.rng.choice([f"select_{i}" for i in range(1, 6)]))

        # 4) places random order
        places = [f"place_{i}" for i in range(1, 9)]
        self.rng.shuffle(places)
        for p in places:
            self.random_click(p)

        # 5) wait 3 sec
        safe_sleep(self.after_places_wait)

        # 6) select in order
        for i in range(1, 6):
            self.random_click(f"select_{i}")

        # 7) percent logic
        percent_rect = self.detect_regions["percent"]

        p = read_percent(percent_rect)
        print(f"[detect] percent={p}")

        if p is not None and p < 20:
            print("[rule] percent < 20 -> cancel now")
            self.cancel_flow()
            return

        start_time = time.time()
        while True:
            self._check_stop()
            if time.time() - start_time > self.percent_timeout:
                print("[rule] timeout -> cancel")
                break

            safe_sleep(self.rand_delay(self.poll_interval_range))
            p = read_percent(percent_rect)
            print(f"[detect] percent={p}")
            if p is not None and p > 60:
                print("[rule] percent > 60 -> cancel")
                break

        self.cancel_flow()

    def cancel_flow(self):
        while not self.is_home_true():
            time.sleep(1)
            self.random_click("cancel")
            time.sleep(0.5)
            self.random_click("confirm")
            time.sleep(0.5)
            self.random_click("back")
            time.sleep(3)

    def collect_flow(self):
        self.random_click("collect")
        time.sleep(0.5)
        self.random_click("collect_confirm")
        time.sleep(0.5)
        self.random_click("collect_cancel")

    def run_forever(self):
        i = 0
        while not STOP_EVENT.is_set():
            i += 1
            print(f"\n===== LOOP {i} =====")
            if i%5 == 0:
                self.collect_flow()
                print(f"WATER COLLECTED IN LOOP {i}")
            try:
                self.run_one_loop()
                time.sleep(5)
            except KeyboardInterrupt as e:
                print(f"[STOP] {e}")
                break
            except subprocess.CalledProcessError as e:
                print(f"[error] cliclick failed: {e}")
                safe_sleep(1.0)
            except Exception as e:
                print(f"[error] {type(e).__name__}: {e}")
                safe_sleep(1.0)

        print("[EXIT] stopped cleanly")


def main():
    cfg = load_config("config.yaml")
    start_esc_listener()
    Bot(cfg).run_forever()


if __name__ == "__main__":
    main()
