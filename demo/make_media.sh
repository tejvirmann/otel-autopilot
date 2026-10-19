#!/usr/bin/env bash
# Turn a raw screen recording of the demo into a short README video (mp4) and GIF.
# Usage: demo/make_media.sh ~/Desktop/demo.mov
# Output: docs/media/demo.mp4 and docs/media/demo.gif
#
# Edit SEGMENTS to re-time a different recording:
#   "start_seconds end_seconds speed"      a slice of the recording at speed x
#   "img path seconds"                     a still image shown for N seconds
#   "black 0 seconds"                      a black card shown for N seconds
# Slow, boring parts (the AI working, traffic progress bars) are sped up.
#
# PRIVACY: a recording of your real browser shows your tab strip, profile photo and any tab
# you switch through. In the current recording the browser window flashes an unrelated tab
# for under a second when it opens (about 193.85s to 195.0s); that slice is replaced by a
# black card. The tab strip of the window is still visible while Grafana is on screen. If you
# re-record, use a clean browser profile or DEMO_NO_OPEN=1, and re-check the timestamps below.
set -euo pipefail
cd "$(dirname "$0")/.."
IN="${1:?usage: demo/make_media.sh <recording.mov>}"
OUT=docs/media
W=1000; H=1126      # output size (the recording is 1572x1770)
mkdir -p "$OUT"

SEGMENTS=(
  "0     46     3"                            # clone, colima, setup, first verify
  "46    62     1.5"                          # demo steps 1-3 and the "what the agent receives" box
  "62    150    6"                            # the agent working (the long wait)
  "150   162    1.5"                          # diff and AFTER verify (100/100)
  "162   193.85 6"                            # backend start + 30s traffic progress bar
  "black 0       0.5"                         # hides the unrelated tab that flashes as Chrome opens (see PRIVACY)
  "195.0  205.05 1.25"                        # the real Grafana window with the generated dashboard
  "205.5 216     2"                           # window closes, step 8 starts
  "216   238     3"                           # payoff: N+1 fix and comparison
)

inputs=(-i "$IN"); filters=""; labels=""; i=0; n_in=1
for seg in "${SEGMENTS[@]}"; do
  read -r a b c <<<"${seg%%#*}"
  if [ "$a" = black ]; then
    inputs+=(-f lavfi -t "$c" -i "color=c=black:s=${W}x${H}:r=30")
    filters+="[$n_in:v]fps=30,setsar=1,format=yuv420p[v$i];"
    n_in=$((n_in+1))
  elif [ "$a" = img ]; then
    inputs+=(-loop 1 -t "$c" -i "$b")
    filters+="[$n_in:v]scale=$W:$H:force_original_aspect_ratio=decrease,pad=$W:$H:(ow-iw)/2:(oh-ih)/2:color=0x111217,fps=30,setsar=1,format=yuv420p[v$i];"
    n_in=$((n_in+1))
  else
    filters+="[0:v]trim=start=$a:end=$b,setpts=(PTS-STARTPTS)/$c,fps=30,scale=$W:$H,setsar=1,format=yuv420p[v$i];"
  fi
  labels+="[v$i]"; i=$((i+1))
done
filters+="${labels}concat=n=$i:v=1:a=0[out]"

echo "encoding $OUT/demo.mp4 ..."
ffmpeg -v error -y "${inputs[@]}" -filter_complex "$filters" -map "[out]" -an \
  -c:v libx264 -crf 27 -preset slow -pix_fmt yuv420p -movflags +faststart "$OUT/demo.mp4"

# GIF: shrink until it is under ~10 MB (GitHub-friendly)
for cfg in "8 760 128" "6 680 96" "5 600 64"; do
  read -r fps w colors <<<"$cfg"
  echo "encoding $OUT/demo.gif (fps=$fps width=$w colors=$colors) ..."
  ffmpeg -v error -y -i "$OUT/demo.mp4" \
    -vf "fps=$fps,scale=$w:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=$colors[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" \
    "$OUT/demo.gif"
  size=$(stat -f%z "$OUT/demo.gif" 2>/dev/null || stat -c%s "$OUT/demo.gif")
  [ "$size" -lt 10000000 ] && break
done

dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/demo.mp4")
kb() { echo $(( $(stat -f%z "$1" 2>/dev/null || stat -c%s "$1") / 1024 )); }
printf 'done: demo.mp4 %.0fs, %s KB | demo.gif %s KB\n' "$dur" "$(kb "$OUT/demo.mp4")" "$(kb "$OUT/demo.gif")"
